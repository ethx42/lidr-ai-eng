"""The LLM call: CAG prompt -> provider -> computed totals -> grounding -> markdown."""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import aclosing

from app.observability import log_llm_call
from app.prompts.loader import PromptBundle, build_user_message
from app.schemas.estimation import (
    CallMetrics,
    EstimateRequest,
    EstimateResponse,
    EstimationBreakdown,
)
from app.schemas.stream import PartialEvent, StatusEvent
from app.services.errors import InvalidModelOutput, LLMError
from app.services.estimation_math import enrich
from app.services.grounding import check_grounding
from app.services.pricing import cost_usd
from app.services.providers.base import LLMProvider, LLMResult, ProviderSwitch, TextDelta
from app.services.rendering import render_markdown
from app.services.streaming import PartialSnapshotter

logger = logging.getLogger(__name__)

StreamItem = StatusEvent | PartialEvent | EstimateResponse


def _ms_since(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


class EstimationService:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        prompt: PromptBundle,
        weekly_capacity_hours: float,
        hourly_rate: float | None,
    ) -> None:
        self.provider = provider
        self.prompt = prompt
        self.weekly_capacity_hours = weekly_capacity_hours
        self.hourly_rate = hourly_rate
        # Provider-side prompt-cache routing key (OpenAI `prompt_cache_key`), not a response cache.
        self.prompt_cache_key = f"estimator-{prompt.version}"

    def _log_call(
        self,
        result: LLMResult[EstimationBreakdown] | None,
        latency_ms: int,
        error: LLMError | None = None,
        *,
        stream: bool = False,
        ttft_ms: int | None = None,
    ) -> None:
        log_llm_call(
            provider=result.provider if result else self.provider.name,
            model=result.model if result else self.provider.model,
            prompt_version=self.prompt.version,
            usage=result.usage if result else None,
            latency_ms=latency_ms,
            outcome=error.code if error else "ok",
            cause=error.cause if error else None,
            upstream_status=error.upstream_status if error else None,
            stream=stream,
            ttft_ms=ttft_ms,
            cost_usd=cost_usd(result.model, result.usage) if result else None,
            attempt=result.attempts if result else 1,
            fallback=result.fallback_used if result else False,
        )

    def _log_cancelled(self, latency_ms: int, ttft_ms: int | None) -> None:
        log_llm_call(
            provider=self.provider.name,
            model=self.provider.model,
            prompt_version=self.prompt.version,
            usage=None,
            latency_ms=latency_ms,
            outcome="cancelled",
            stream=True,
            ttft_ms=ttft_ms,
        )

    def _respond(
        self,
        result: LLMResult[EstimationBreakdown],
        request: EstimateRequest,
        *,
        stream: bool = False,
        ttft_ms: int | None = None,
    ) -> EstimateResponse:
        self._log_call(result, result.latency_ms, stream=stream, ttft_ms=ttft_ms)
        breakdown = enrich(
            result.parsed,
            weekly_capacity_hours=self.weekly_capacity_hours,
            hourly_rate=self.hourly_rate,
        )
        grounding = check_grounding(result.parsed, request.transcription)
        if grounding.ungrounded_requirement_ids or grounding.tasks_without_valid_basis:
            logger.warning(
                "grounding_warnings",
                extra={"fields": grounding.model_dump(exclude={"requirements_grounded"})},
            )
        return EstimateResponse(
            estimation=render_markdown(breakdown, grounding),
            breakdown=breakdown,
            grounding=grounding,
            model=result.model,
            provider=result.provider,
            prompt_version=self.prompt.version,
            usage=result.usage,
            metrics=CallMetrics(
                latency_ms=result.latency_ms,
                ttft_ms=ttft_ms,
                cost_usd=cost_usd(result.model, result.usage),
                attempts=result.attempts,
                fallback_used=result.fallback_used,
            ),
        )

    async def estimate(self, request: EstimateRequest) -> EstimateResponse:
        start = time.perf_counter()
        try:
            result = await self.provider.generate(
                system=self.prompt.system_text,
                user=build_user_message(request.transcription, request.output_language),
                schema=EstimationBreakdown,
                cache_key=self.prompt_cache_key,
            )
        except LLMError as exc:
            self._log_call(None, _ms_since(start), exc)
            raise
        return self._respond(result, request)

    async def estimate_stream(self, request: EstimateRequest) -> AsyncGenerator[StreamItem]:
        user = build_user_message(request.transcription, request.output_language)
        start = time.perf_counter()
        snapshotter = PartialSnapshotter()
        snapshot, ttft_ms, result = "", None, None
        yield StatusEvent(
            phase="calling_llm", provider=self.provider.name, model=self.provider.model
        )
        try:
            async with aclosing(
                self.provider.stream(
                    system=self.prompt.system_text,
                    user=user,
                    schema=EstimationBreakdown,
                    cache_key=self.prompt_cache_key,
                )
            ) as events:
                async for event in events:
                    match event:
                        case TextDelta():
                            ttft_ms = _ms_since(start) if ttft_ms is None else ttft_ms
                            snapshot = event.snapshot
                            if partial := snapshotter.feed(snapshot):
                                yield partial
                        case ProviderSwitch():
                            yield StatusEvent(
                                phase="fallback", provider=event.provider, model=event.model
                            )
                        case LLMResult():
                            result = event
            if result is None:
                raise InvalidModelOutput(reason="no_final_result")
        except LLMError as exc:
            self._log_call(None, _ms_since(start), exc, stream=True, ttft_ms=ttft_ms)
            raise
        # Disconnect mid-await (CancelledError) or aclose() while parked at a yield (GeneratorExit).
        # Sync logging only: any await here would be cancelled again.
        except (asyncio.CancelledError, GeneratorExit):
            self._log_cancelled(_ms_since(start), ttft_ms)
            raise
        # Built (and logged) before the trailing events: the upstream call is complete, so a client
        # leaving now must still leave exactly one llm_call record.
        response = self._respond(result, request, stream=True, ttft_ms=ttft_ms)
        if partial := snapshotter.flush(snapshot):
            yield partial
        yield StatusEvent(phase="validating")
        yield response
