"""The LLM call: CAG prompt -> provider -> computed totals -> grounding -> markdown."""

import logging
import time

from app.observability import log_llm_call
from app.prompts.loader import PromptBundle, build_user_message
from app.schemas.estimation import (
    EstimateRequest,
    EstimateResponse,
    EstimationBreakdown,
    Usage,
)
from app.services.errors import LLMError
from app.services.estimation_math import enrich
from app.services.grounding import check_grounding
from app.services.providers.base import LLMProvider
from app.services.rendering import render_markdown

logger = logging.getLogger(__name__)


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

    def _log_call(self, usage: Usage | None, latency_ms: int, outcome: str) -> None:
        log_llm_call(
            provider=self.provider.name,
            model=self.provider.model,
            prompt_version=self.prompt.version,
            usage=usage,
            latency_ms=latency_ms,
            outcome=outcome,
        )

    async def estimate(self, request: EstimateRequest) -> EstimateResponse:
        start = time.perf_counter()
        try:
            result = await self.provider.generate(
                system=self.prompt.system_text,
                user=build_user_message(request.transcription, request.output_language),
                schema=EstimationBreakdown,
                cache_key=f"estimator-{self.prompt.version}",
            )
        except LLMError as exc:
            latency_ms = round((time.perf_counter() - start) * 1000)
            self._log_call(None, latency_ms, exc.code)
            raise
        self._log_call(result.usage, result.latency_ms, "ok")

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
            model=self.provider.model,
            provider=self.provider.name,
            prompt_version=self.prompt.version,
            usage=result.usage,
        )
