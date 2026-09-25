class DecisionStudioError(Exception):
    """Base exception for Decision Studio."""


class PipelineError(DecisionStudioError):
    """Raised when a pipeline stage fails."""


class LLMError(DecisionStudioError):
    """Raised when an LLM API call fails."""


class DAGError(DecisionStudioError):
    """Raised when graph construction or validation fails."""


class ValidationError(DecisionStudioError):
    """Raised when input validation fails."""
