"""Insert docstrings, keyed by (file, function).

Written because 118 functions needed one and hand-editing that many by line
number invites off-by-one errors that a test suite would not catch. Uses the AST
to find the insertion point, so it cannot land inside a string or a comment.

Not part of the application. Run once, kept in the repository so the next person
adding a batch does not write it again.
"""

from __future__ import annotations

import ast
import pathlib
import sys


def insert(path: pathlib.Path, docs: dict[str, str]) -> int:
    """Add a docstring to each named function that lacks one.

    Functions already documented are left alone, so re-running is safe and a
    hand-written docstring is never overwritten by a generated one.
    """
    source = path.read_text()
    lines = source.splitlines(keepends=True)

    targets = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in docs or ast.get_docstring(node):
            continue
        # The body's first statement is where the docstring goes, and its
        # indentation is the body's — not the def's, which differs for methods.
        first = node.body[0]
        indent = " " * (first.col_offset)
        targets.append((first.lineno - 1, indent, docs[node.name]))

    # Descending, so earlier insertions do not shift later line numbers.
    for lineno, indent, text in sorted(targets, reverse=True):
        body = "\n".join(
            f"{indent}{line}" if line.strip() else "" for line in text.splitlines()
        )
        lines.insert(lineno, f'{indent}"""{text.splitlines()[0]}\n'
                     if len(text.splitlines()) == 1 else "")
        lines[lineno] = (
            f'{indent}"""{text}"""\n'
            if "\n" not in text
            else f'{indent}"""{text.splitlines()[0]}\n'
                 + "\n".join(body.splitlines()[1:])
                 + f'\n{indent}"""\n'
        )

    path.write_text("".join(lines))
    return len(targets)


if __name__ == "__main__":
    print("Import and call insert(); see the batch scripts.", file=sys.stderr)
