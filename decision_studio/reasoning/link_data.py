"""Testing a causal link against the decider's own numbers.

The pipeline has always had a statistical validator, but it needs ``metric_data``
and nothing ever supplied any, so every link was supported by text and model
judgement alone. This is the smallest way in: paste two columns — the cause and
the effect, one row per period or per case — against one link hypothesis.

What the numbers can and cannot say is kept honest:

* Rows in time order and enough of them: a Granger test, forward and reverse.
  Past values of the cause helping predict the effect, and not the other way
  round, is the closest a small table gets to direction.
* Otherwise: a rank correlation (Spearman), with the sign the link predicts
  (negative for an inhibiting link).
* A significant result the right way round counts as **held**; a significant
  one the wrong way round (or reverse direction stronger) as **refuted**.
  Nothing significant is **inconclusive**, never refuted: with a small table,
  absence of a correlation is mostly absence of power. And "held" is support,
  not proof — the default likelihood ratio already says so.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass

import numpy as np
from scipy import stats

from decision_studio.statistical.granger import granger_test

ALPHA = 0.05
MIN_ROWS = 8
#: Enough rows for a lagged test at lag up to 3 (granger_test needs max_lag + 10).
MIN_ROWS_TIME_SERIES = 13
MAX_ROWS = 5000


class TableError(ValueError):
    """The pasted table cannot be read as two numeric columns."""


@dataclass
class DataVerdict:
    result: str  # held, refuted or inconclusive
    method: str  # granger or spearman
    n: int
    statistic: float | None
    p_value: float | None
    summary: str


def _number(cell: str) -> float | None:
    cleaned = cell.strip().replace("%", "").replace(" ", "")
    if not cleaned:
        return None
    # "1.234,5" and "1,234.5": whichever separator comes last is the decimal.
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def parse_table(text: str) -> tuple[np.ndarray, np.ndarray]:
    """Two numeric columns from pasted CSV / TSV / semicolon text.

    A header row is skipped; when a row has more than two numeric cells, the
    last two are used (a leading date or label column is common).

    Raises:
        TableError: fewer than MIN_ROWS usable rows, or too many.
    """
    sample = text.strip()
    if not sample:
        raise TableError("The table is empty.")
    delimiter = "\t" if "\t" in sample else (";" if ";" in sample else ",")
    cause: list[float] = []
    effect: list[float] = []
    for row in csv.reader(io.StringIO(sample), delimiter=delimiter):
        numbers = [n for n in (_number(cell) for cell in row) if n is not None]
        if len(numbers) < 2:
            continue  # header, blank or incomplete row
        cause.append(numbers[-2])
        effect.append(numbers[-1])
    if len(cause) < MIN_ROWS:
        raise TableError(
            f"Found {len(cause)} usable row(s); at least {MIN_ROWS} are needed, "
            "each with a number for the cause and one for the effect."
        )
    if len(cause) > MAX_ROWS:
        raise TableError(f"At most {MAX_ROWS} rows.")
    return np.array(cause), np.array(effect)


def analyse(
    cause: np.ndarray, effect: np.ndarray, *, inhibiting: bool = False, time_ordered: bool = True
) -> DataVerdict:
    """What two columns say about "cause drives effect"."""
    n = len(cause)
    expected = "falls" if inhibiting else "rises"
    if np.std(cause) == 0 or np.std(effect) == 0:
        return DataVerdict("inconclusive", "spearman", n, None, None,
                           "One of the columns does not vary, so nothing can be read from it.")

    if time_ordered and n >= MIN_ROWS_TIME_SERIES:
        max_lag = min(3, n - 10)
        forward = granger_test(cause, effect, max_lag=max_lag, alpha=ALPHA)
        reverse = granger_test(effect, cause, max_lag=max_lag, alpha=ALPHA)
        if forward is not None:
            rho = stats.spearmanr(cause[:-forward.lag], effect[forward.lag:]).statistic
            right_sign = (rho < 0) if inhibiting else (rho > 0)
            if reverse is not None and reverse.p_value < ALPHA and reverse.p_value < forward.p_value:
                return DataVerdict(
                    "refuted", "granger", n, reverse.f_statistic, reverse.p_value,
                    f"Over {n} periods the effect predicts the cause better than the "
                    f"reverse (p={reverse.p_value:.3f}): the direction looks backwards.",
                )
            if forward.p_value < ALPHA and right_sign:
                return DataVerdict(
                    "held", "granger", n, forward.f_statistic, forward.p_value,
                    f"Over {n} periods, past values of the cause help predict the effect "
                    f"at a lag of {forward.lag} (p={forward.p_value:.3f}), and it {expected} "
                    "as the link says.",
                )
            if forward.p_value < ALPHA:
                return DataVerdict(
                    "refuted", "granger", n, forward.f_statistic, forward.p_value,
                    f"Over {n} periods the cause predicts the effect (p={forward.p_value:.3f}) "
                    f"but in the opposite direction: the link says it {expected}.",
                )
            return DataVerdict(
                "inconclusive", "granger", n, forward.f_statistic, forward.p_value,
                f"Over {n} periods no lagged relationship was found (p={forward.p_value:.2f}). "
                "With a small table that is mostly a lack of power, not a refutation.",
            )

    result = stats.spearmanr(cause, effect)
    rho, p = float(result.statistic), float(result.pvalue)
    right_sign = (rho < 0) if inhibiting else (rho > 0)
    if p < ALPHA and right_sign:
        verdict, text = "held", (
            f"Across {n} rows the two move together as the link says "
            f"(rank correlation {rho:+.2f}, p={p:.3f}). Correlation, not proof of cause."
        )
    elif p < ALPHA:
        verdict, text = "refuted", (
            f"Across {n} rows they move the opposite way to the link "
            f"(rank correlation {rho:+.2f}, p={p:.3f}); the link says the effect {expected}."
        )
    else:
        verdict, text = "inconclusive", (
            f"Across {n} rows no clear relationship (rank correlation {rho:+.2f}, p={p:.2f}). "
            "With a small table that is mostly a lack of power, not a refutation."
        )
    return DataVerdict(verdict, "spearman", n, rho, p, text)
