from dataclasses import dataclass

from app.schemas.estimation import Usage

# The reason every provider gives exhausted credits or spend limits; the fallback router keys on it.
QUOTA = "insufficient_quota"


@dataclass(frozen=True)
class Attempt:
    """One provider call within a request, numbered from 1; `fallback` when not the primary."""

    provider: str
    model: str
    number: int = 1
    fallback: bool = False


class LLMError(Exception):
    """Domain failure from an LLM provider, mapped to HTTP by the API layer."""

    status_code = 502
    code = "upstream_error"
    message = "The LLM provider rejected the request."

    def __init__(
        self, message: str | None = None, *, reason: str | None = None, usage: Usage | None = None
    ) -> None:
        super().__init__(message or self.message)
        self.reason = reason
        self.usage = usage  # a failed call's usage, when the provider reported it; None if unknown
        self.attempt: Attempt | None = None  # set by the fallback router: which call raised it

    @property
    def cause(self) -> str | None:
        """What failed, for logs only: an explicit stop condition or the chained error's class."""
        return self.reason or (type(self.__cause__).__name__ if self.__cause__ else None)

    @property
    def upstream_status(self) -> int | None:
        """The upstream's HTTP error status; None for an error inside a 200 stream (Anthropic's
        SDK raises it as a status error that carries the stream's 200)."""
        status = getattr(self.__cause__, "status_code", None)
        return status if isinstance(status, int) and status >= 400 else None


class UpstreamRateLimited(LLMError):
    status_code = 429
    code = "upstream_rate_limited"
    message = "The LLM provider is rate limiting requests. Try again later."


class UpstreamUnavailable(LLMError):
    status_code = 503
    code = "upstream_unavailable"
    message = "The LLM provider is unavailable or timed out. Try again later."


class InvalidModelOutput(LLMError):
    status_code = 502
    code = "invalid_model_output"
    message = "The model did not return a valid estimation."


class UpstreamError(LLMError):
    pass


def from_status(status_code: int) -> LLMError:
    if status_code == 429:
        return UpstreamRateLimited()
    if status_code == 408 or status_code >= 500:
        return UpstreamUnavailable()
    return UpstreamError()
