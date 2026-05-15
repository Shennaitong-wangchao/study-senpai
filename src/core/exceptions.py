class ShenZhiweiError(Exception):
    """Base application error."""


class ConfigurationError(ShenZhiweiError):
    """Raised when required configuration is missing."""


class LLMClientError(ShenZhiweiError):
    """Raised when the configured LLM backend fails."""
