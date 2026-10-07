"""The LLM call: rendered prompt -> cache lookup -> provider -> computed totals -> grounding ->
markdown -> cache write. `run`/`stream_run` are the core; the single-shot wrappers render one user
message and use the cache, the conversation service sends its history and bypasses it."""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator, Sequence
from contextlib import aclosing

import anyio

from app.observability import llm_logger, log_llm_call, prompt_version_var
from app.prompts.loader import RenderedPrompt, render
from app.schemas.estimation import (
    CallMetrics,
    EstimateRequest,
    EstimateResponse,
    EstimationBreakdown,
)
from app.schemas.stream import PartialEvent, StatusEvent
from app.services.cache import CacheStatus, ResponseCache, cache_key
from app.services.errors import Attempt, InvalidModelOutput, LLMError
from app.services.estimation_math import enrich
from app.services.grounding import check_grounding
from app.services.pricing import cost_usd
from app.services.providers.base import (
    ChatMessage,
    LLMProvider,
    LLMResult,
    ProviderSwitch,
    TextDelta,
)
from app.services.rendering import render_markdown
from app.services.streaming import PartialSnapshotter

logger = logging.getLogger(__name__)

StreamItem = StatusEvent | PartialEvent | EstimateResponse


def _ms_since(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


def routing_key(prompt: RenderedPrompt) -> str:
    """Provider-side prompt-cache routing key (OpenAI `prompt_cache_key`), not a response cache."""
    return f"estimator-{prompt.version}"


class EstimationService:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        prompt_version: str,
        weekly_capacity_hours: float,
        hourly_rate: float | None,
        cache: ResponseCache,
        cache_scope: str,
    ) -> None:
        self.provider = provider
        self.prompt_version = prompt_version
        self.weekly_capacity_hours = weekly_capacity_hours
        self.hourly_rate = hourly_rate
        self.cache = cache
        self.cache_scope = cache_scope
        self.primary_attempt = Attempt(provider.name, provider.model)

    def _prepare(self, request: EstimateRequest, prompt_version: str | None) -> RenderedPrompt:
        """The single-turn prompt: one path for both endpoints and cache_key_for."""
        return render(request, self.prompt_version if prompt_version is None else prompt_version)

    def _key(self, prompt: RenderedPrompt) -> str:
        return cache_key(
            prompt_version=prompt.version,
            system=prompt.system,
            user=prompt.user,
            scope=self.cache_scope,
            schema_name=EstimationBreakdown.__name__,
        )

    def cache_key_for(self, request: EstimateRequest, prompt_version: str | None = None) -> str:
        return self._key(self._prepare(request, prompt_version))

    def _start(self, prompt: RenderedPrompt, use_cache: bool) -> str | None:
        """The cache key, or None when this call bypasses the cache."""
        # Before any provider call: the router's llm_fallback records read it.
        prompt_version_var.set(prompt.version)
        return self._key(prompt) if use_cache else None

    def _log_call(
        self,
        result: LLMResult[EstimationBreakdown] | None,
        latency_ms: int,
        error: LLMError | None = None,
        *,
        version: str,
        cache: CacheStatus,
        attempt: Attempt | None = None,
        stream: bool = False,
        ttft_ms: int | None = None,
    ) -> None:
        """`attempt` names the call that failed or was cancelled; a result names its own. A failure
        logs the usage (and cost) the provider reported for it; unknown usage logs 0 tokens and a
        null cost."""
        attempt = (
            Attempt(result.provider, result.model, result.attempts, result.fallback_used)
            if result
            else attempt or self.primary_attempt
        )
        usage = result.usage if result else error.usage if error else None
        log_llm_call(
            provider=attempt.provider,
            model=attempt.model,
            prompt_version=version,
            usage=usage,
            latency_ms=latency_ms,
            outcome=error.code if error else "ok",
            cause=error.cause if error else None,
            upstream_status=error.upstream_status if error else None,
            stream=stream,
            ttft_ms=ttft_ms,
            cost_usd=cost_usd(attempt.model, usage) if usage else None,
            attempt=attempt.number,
            fallback=attempt.fallback,
            cache=cache,
        )

    def _log_cancelled(
        self,
        attempt: Attempt,
        latency_ms: int,
        ttft_ms: int | None,
        cache: CacheStatus,
        version: str,
    ) -> None:
        log_llm_call(
            provider=attempt.provider,
            model=attempt.model,
            prompt_version=version,
            usage=None,
            latency_ms=latency_ms,
            outcome="cancelled",
            stream=True,
            ttft_ms=ttft_ms,
            attempt=attempt.number,
            fallback=attempt.fallback,
            cache=cache,
        )

    def _respond(
        self,
        result: LLMResult[EstimationBreakdown],
        request: EstimateRequest,
        grounding_source: str,
        *,
        version: str,
        cache: CacheStatus,
        stream: bool = False,
        ttft_ms: int | None = None,
    ) -> EstimateResponse:
        self._log_call(
            result, result.latency_ms, version=version, cache=cache, stream=stream, ttft_ms=ttft_ms
        )
        breakdown = enrich(
            result.parsed,
            weekly_capacity_hours=self.weekly_capacity_hours,
            hourly_rate=self.hourly_rate,
        )
        grounding = check_grounding(result.parsed, grounding_source)
        if grounding.ungrounded_requirement_ids or grounding.tasks_without_valid_basis:
            logger.warning(
                "grounding_warnings",
                extra={"fields": grounding.model_dump(exclude={"requirements_grounded"})},
            )
        return EstimateResponse(
            estimation=render_markdown(breakdown, grounding, request.output_format),
            breakdown=breakdown,
            grounding=grounding,
            model=result.model,
            provider=result.provider,
            prompt_version=version,
            usage=result.usage,
            metrics=CallMetrics(
                latency_ms=result.latency_ms,
                ttft_ms=ttft_ms,
                cost_usd=cost_usd(result.model, result.usage),
                attempts=result.attempts,
                fallback_used=result.fallback_used,
            ),
        )

    async def _lookup(
        self, key: str | None, *, version: str, refresh: bool, stream: bool
    ) -> tuple[EstimateResponse | None, CacheStatus]:
        """A hit carries this request's metrics: no LLM call, so no cost, attempts or TTFT."""
        if key is None or refresh:
            return None, "bypass"
        start = time.perf_counter()
        cached, status = await self.cache.get(key)
        if cached is None:
            return None, status
        metrics = CallMetrics(latency_ms=_ms_since(start), cost_usd=0, cache_hit=True, attempts=0)
        llm_logger.info(
            "estimate_cache_hit",
            extra={
                "fields": {
                    "provider": cached.provider,
                    "model": cached.model,
                    "prompt_version": version,
                    "latency_ms": metrics.latency_ms,
                    "stream": stream,
                    "cache": status,
                }
            },
        )
        return cached.model_copy(update={"metrics": metrics}), status

    async def _store(
        self, key: str | None, response: EstimateResponse, lookup: CacheStatus
    ) -> None:
        # Redis just failed the lookup: a second timeout would double the latency it adds.
        if key is not None and lookup != "error":
            await self.cache.set(key, response)

    async def estimate(
        self, request: EstimateRequest, *, refresh: bool = False, prompt_version: str | None = None
    ) -> EstimateResponse:
        prompt = self._prepare(request, prompt_version)
        return await self.run(
            prompt,
            [ChatMessage("user", prompt.user)],
            request,
            request.transcription,
            use_cache=True,
            refresh=refresh,
        )

    async def estimate_stream(
        self, request: EstimateRequest, *, refresh: bool = False, prompt_version: str | None = None
    ) -> AsyncGenerator[StreamItem]:
        prompt = self._prepare(request, prompt_version)
        async with aclosing(
            self.stream_run(
                prompt,
                [ChatMessage("user", prompt.user)],
                request,
                request.transcription,
                use_cache=True,
                refresh=refresh,
            )
        ) as items:
            async for item in items:
                yield item

    async def run(
        self,
        prompt: RenderedPrompt,
        messages: Sequence[ChatMessage],
        request: EstimateRequest,
        grounding_source: str,
        *,
        use_cache: bool,
        refresh: bool = False,
    ) -> EstimateResponse:
        """One call with `messages` (ending with `prompt.user`); grounding checks quotes against
        `grounding_source`. Without `use_cache` the cache is never read or written."""
        key = self._start(prompt, use_cache)
        cached, lookup = await self._lookup(
            key, version=prompt.version, refresh=refresh, stream=False
        )
        if cached:
            return cached
        start = time.perf_counter()
        try:
            result = await self.provider.generate(
                system=prompt.system,
                messages=messages,
                schema=EstimationBreakdown,
                cache_key=routing_key(prompt),
            )
        except LLMError as exc:
            self._log_call(
                None,
                _ms_since(start),
                exc,
                version=prompt.version,
                cache=lookup,
                attempt=exc.attempt,
            )
            raise
        response = self._respond(
            result, request, grounding_source, version=prompt.version, cache=lookup
        )
        await self._store(key, response, lookup)
        return response

    async def stream_run(
        self,
        prompt: RenderedPrompt,
        messages: Sequence[ChatMessage],
        request: EstimateRequest,
        grounding_source: str,
        *,
        use_cache: bool,
        refresh: bool = False,
    ) -> AsyncGenerator[StreamItem]:
        """`run`, streamed: status and partial events, then exactly one response."""
        key = self._start(prompt, use_cache)
        cached, lookup = await self._lookup(
            key, version=prompt.version, refresh=refresh, stream=True
        )
        if cached:
            yield StatusEvent(phase="cache_hit", provider=cached.provider, model=cached.model)
            yield cached
            return
        start = time.perf_counter()
        snapshotter = PartialSnapshotter()
        snapshot, ttft_ms, result = "", None, None
        in_flight = self.primary_attempt
        yield StatusEvent(
            phase="calling_llm", provider=self.provider.name, model=self.provider.model
        )
        try:
            async with aclosing(
                self.provider.stream(
                    system=prompt.system,
                    messages=messages,
                    schema=EstimationBreakdown,
                    cache_key=routing_key(prompt),
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
                            in_flight = Attempt(
                                event.provider, event.model, event.attempt, fallback=True
                            )
                            yield StatusEvent(
                                phase="fallback", provider=event.provider, model=event.model
                            )
                        case LLMResult():
                            result = event
            if result is None:
                raise InvalidModelOutput(reason="no_final_result")
        except LLMError as exc:
            self._log_call(
                None,
                _ms_since(start),
                exc,
                version=prompt.version,
                cache=lookup,
                attempt=in_flight,
                stream=True,
                ttft_ms=ttft_ms,
            )
            raise
        # Disconnect mid-await (CancelledError) or aclose() while parked at a yield (GeneratorExit).
        # Sync logging only: any await here would be cancelled again.
        except (asyncio.CancelledError, GeneratorExit):
            self._log_cancelled(in_flight, _ms_since(start), ttft_ms, lookup, prompt.version)
            raise
        # Built (and logged) before the trailing events: the upstream call is complete, so a client
        # leaving now must still leave exactly one llm_call record.
        response = self._respond(
            result,
            request,
            grounding_source,
            version=prompt.version,
            cache=lookup,
            stream=True,
            ttft_ms=ttft_ms,
        )
        if partial := snapshotter.flush(snapshot):
            yield partial
        yield StatusEvent(phase="validating")
        yield response
        # Reached only once the consumer took the result and asked for more: a client that left
        # at any yield above caches nothing. Shielded so a disconnect cannot cut the write short,
        # and bounded so it cannot hold the stream open.
        with anyio.move_on_after(0.5, shield=True):
            await self._store(key, response, lookup)
