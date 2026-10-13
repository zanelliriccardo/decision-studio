class DecisionStudioError(Exception):
    """Base exception for Decision Studio."""


class PipelineError(DecisionStudioError):
    """Raised when a pipeline stage fails."""


class LLMError(DecisionStudioError):
    """Raised when an LLM API call fails."""


class DAGError(DecisionStudioError):
    """Raised when graph construction or validation fails."""


# DEAD-CODE-CANDIDATE DC-14: never raised or caught. See docs/DEAD_CODE_REPORT.md
class ValidationError(DecisionStudioError):
    """Raised when input validation fails."""
