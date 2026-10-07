import logging

import pytest

from app.observability import prompt_version_var
from app.schemas.estimation import EstimationBreakdown
from app.services.errors import (
    Attempt,
    InvalidModelOutput,
    LLMError,
    UpstreamError,
    UpstreamRateLimited,
    UpstreamUnavailable,
)
from app.services.providers.base import ChatMessage, LLMResult, ProviderSwitch, TextDelta
from app.services.providers.fallback import Cooldown, FallbackProvider, falls_back
from tests.fakes import FakeProvider, SlowFakeProvider, SlowToFailProvider

ARGS = {
    "system": "S",
    "messages": [
        ChatMessage("user", "U1"),
        ChatMessage("assistant", "A1"),
        ChatMessage("user", "U2"),
    ],
    "schema": EstimationBreakdown,
    "cache_key": "k",
}


async def test_falls_back_on_unavailable_and_reports_it() -> None:
    primary = FakeProvider(error=UpstreamUnavailable(), name="openai")
    secondary = FakeProvider(name="anthropic", model="claude-haiku-4-5")
    result = await FallbackProvider([primary, secondary], Cooldown()).generate(**ARGS)
    assert result.provider == "anthropic" and result.fallback_used and result.attempts == 2


@pytest.mark.parametrize("stream", [False, True], ids=["generate", "stream"])
async def test_the_fallback_attempt_receives_the_full_history(stream: bool) -> None:
    primary = FakeProvider(error=UpstreamUnavailable())
    secondary = FakeProvider(name="anthropic")
    router = FallbackProvider([primary, secondary], Cooldown())
    if stream:
        [e async for e in router.stream(**ARGS)]
    else:
        await router.generate(**ARGS)
    assert primary.calls[0]["messages"] == secondary.calls[0]["messages"] == ARGS["messages"]


@pytest.mark.parametrize("error", [UpstreamError(), InvalidModelOutput()])
async def test_does_not_fall_back_on_caller_or_output_errors(error) -> None:
    secondary = FakeProvider(name="anthropic")
    with pytest.raises(type(error)):
        await FallbackProvider([FakeProvider(error=error), secondary], Cooldown()).generate(**ARGS)
    assert secondary.calls == []


async def test_quota_exhaustion_falls_back() -> None:
    primary = FakeProvider(error=UpstreamError(reason="insufficient_quota"))
    result = await FallbackProvider([primary, FakeProvider(name="anthropic")], Cooldown()).generate(
        **ARGS
    )
    assert result.provider == "anthropic"


async def test_stream_falls_back_only_before_first_delta() -> None:
    early = FakeProvider(error=UpstreamUnavailable())  # fails before yielding
    events = [
        e
        async for e in FallbackProvider([early, FakeProvider(name="anthropic")], Cooldown()).stream(
            **ARGS
        )
    ]
    assert isinstance(events[0], ProviderSwitch) and events[0].provider == "anthropic"
    late = FakeProvider(stream_error_after_chunks=1, stream_error=UpstreamUnavailable())
    secondary = FakeProvider(name="anthropic")
    with pytest.raises(UpstreamUnavailable):
        [e async for e in FallbackProvider([late, secondary], Cooldown()).stream(**ARGS)]
    assert secondary.calls == []


async def test_cooldown_skips_a_failing_primary_then_recovers() -> None:
    clock = [0.0]
    cooldown = Cooldown(failures=2, seconds=30, clock=lambda: clock[0])
    primary = FakeProvider(error=UpstreamUnavailable())
    router = FallbackProvider([primary, FakeProvider(name="anthropic")], cooldown)
    await router.generate(**ARGS)
    await router.generate(**ARGS)
    third = await router.generate(**ARGS)
    assert len(primary.calls) == 2  # third call skipped the primary
    assert third.provider == "anthropic" and third.fallback_used
    clock[0] = 31
    primary.error = None
    result = await router.generate(**ARGS)
    assert result.provider == "openai"


async def test_all_in_cooldown_still_tries_the_primary() -> None:
    cooldown = Cooldown(failures=1, seconds=30)
    a, b = (
        FakeProvider(error=UpstreamUnavailable()),
        FakeProvider(error=UpstreamUnavailable(), name="anthropic"),
    )
    router = FallbackProvider([a, b], cooldown)
    with pytest.raises(UpstreamUnavailable):
        await router.generate(**ARGS)
    with pytest.raises(UpstreamUnavailable):
        await router.generate(**ARGS)
    assert len(a.calls) == 2


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (UpstreamUnavailable(reason="stream_transport"), True),
        (UpstreamRateLimited(), True),
        (UpstreamError(reason="insufficient_quota"), True),
        (UpstreamError(), False),
        (UpstreamError(reason="stream_error:invalid_prompt"), False),
        (InvalidModelOutput(reason="refusal"), False),
    ],
)
def test_only_availability_failures_fall_back(error: LLMError, expected: bool) -> None:
    assert falls_back(error) is expected


def test_reports_the_primary_and_exposes_the_chain() -> None:
    primary, secondary = FakeProvider(model="gpt-4o-mini"), FakeProvider(name="anthropic")
    router = FallbackProvider([primary, secondary], Cooldown())
    assert (router.name, router.model, router.chain) == (
        "openai",
        "gpt-4o-mini",
        [primary, secondary],
    )


def test_an_empty_chain_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one provider"):
        FallbackProvider([], Cooldown())


async def test_each_failed_attempt_that_falls_back_logs_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    primary = FakeProvider(
        error=UpstreamRateLimited(reason="rate_limit_error"), model="gpt-4o-mini"
    )
    router = FallbackProvider([primary, FakeProvider(name="anthropic")], Cooldown())
    prompt_version_var.set("v9")  # set by the service for each request
    with caplog.at_level(logging.DEBUG, logger="app.llm"):
        await router.generate(**ARGS)
    [record] = [r for r in caplog.records if r.name == "app.llm"]
    assert (record.getMessage(), record.levelno) == ("llm_fallback", logging.WARNING)
    fields = record.fields
    keys = ("provider", "model", "attempt", "fallback", "stream", "prompt_version", "outcome")
    assert {k: fields[k] for k in keys} == {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "attempt": 1,
        "fallback": False,
        "stream": False,
        "prompt_version": "v9",
        "outcome": "upstream_rate_limited",
    }
    assert (fields["cause"], fields["upstream_status"]) == ("rate_limit_error", None)
    assert fields["latency_ms"] >= 0


async def test_the_last_failure_is_raised_with_its_attempt_not_logged_as_a_fallback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    primary = FakeProvider(error=UpstreamUnavailable())
    secondary = FakeProvider(
        error=UpstreamRateLimited(), name="anthropic", model="claude-haiku-4-5"
    )
    with (
        caplog.at_level(logging.DEBUG, logger="app.llm"),
        pytest.raises(UpstreamRateLimited) as info,
    ):
        await FallbackProvider([primary, secondary], Cooldown()).generate(**ARGS)
    fallbacks = [r for r in caplog.records if r.getMessage() == "llm_fallback"]
    assert [r.fields["attempt"] for r in fallbacks] == [1]
    assert info.value.attempt == Attempt("anthropic", "claude-haiku-4-5", 2, fallback=True)


async def test_an_error_that_does_not_fall_back_carries_its_attempt() -> None:
    primary = FakeProvider(error=InvalidModelOutput(reason="refusal"), model="gpt-4o-mini")
    with pytest.raises(InvalidModelOutput) as info:
        await FallbackProvider([primary, FakeProvider(name="anthropic")], Cooldown()).generate(
            **ARGS
        )
    assert info.value.attempt == Attempt("openai", "gpt-4o-mini", 1, fallback=False)


async def test_stream_switch_names_the_fallback_its_attempt_and_the_cause() -> None:
    primary = FakeProvider(error=UpstreamUnavailable(reason="stream_transport"))
    secondary = FakeProvider(name="anthropic", model="claude-haiku-4-5")
    events = [e async for e in FallbackProvider([primary, secondary], Cooldown()).stream(**ARGS)]
    assert events[0] == ProviderSwitch(
        provider="anthropic", model="claude-haiku-4-5", cause="stream_transport", attempt=2
    )
    assert all(isinstance(e, TextDelta) for e in events[1:-1]) and len(events) > 2
    result = events[-1]
    assert isinstance(result, LLMResult)
    assert (result.provider, result.attempts, result.fallback_used) == ("anthropic", 2, True)


async def test_stream_served_by_the_primary_has_no_switch() -> None:
    router = FallbackProvider([FakeProvider(), FakeProvider(name="anthropic")], Cooldown())
    events = [e async for e in router.stream(**ARGS)]
    assert not any(isinstance(e, ProviderSwitch) for e in events)
    result = events[-1]
    assert isinstance(result, LLMResult) and (result.attempts, result.fallback_used) == (1, False)


async def test_stream_skipping_a_cooled_down_primary_still_announces_the_switch() -> None:
    primary = FakeProvider(error=UpstreamUnavailable())
    router = FallbackProvider([primary, FakeProvider(name="anthropic")], Cooldown(failures=1))
    await router.generate(**ARGS)  # one failure puts the primary in cooldown
    events = [e async for e in router.stream(**ARGS)]
    assert len(primary.calls) == 1
    assert events[0] == ProviderSwitch(
        provider="anthropic", model="fake-model", cause="cooldown", attempt=1
    )
    result = events[-1]
    assert isinstance(result, LLMResult) and (result.attempts, result.fallback_used) == (1, True)


async def test_a_mid_stream_availability_failure_counts_toward_the_cooldown() -> None:
    late = FakeProvider(stream_error_after_chunks=1, stream_error=UpstreamUnavailable())
    router = FallbackProvider([late, FakeProvider(name="anthropic")], Cooldown(failures=1))
    with pytest.raises(UpstreamUnavailable):
        [e async for e in router.stream(**ARGS)]
    assert (await router.generate(**ARGS)).provider == "anthropic"
    assert len(late.calls) == 1


async def test_closing_the_router_stream_closes_the_provider_stream() -> None:
    slow = SlowFakeProvider()
    slow.name = "anthropic"
    stream = FallbackProvider([FakeProvider(error=UpstreamUnavailable()), slow], Cooldown()).stream(
        **ARGS
    )
    assert isinstance(await anext(stream), ProviderSwitch)
    assert isinstance(await anext(stream), TextDelta)
    await stream.aclose()
    assert slow.closed_streams == 1


async def test_aclose_closes_every_provider_in_the_chain() -> None:
    primary, secondary = FakeProvider(), FakeProvider(name="anthropic")
    await FallbackProvider([primary, secondary], Cooldown()).aclose()
    assert primary.closed and secondary.closed


def test_cooldown_counts_consecutive_failures_per_key_and_a_success_resets() -> None:
    clock = [0.0]
    cooldown = Cooldown(failures=2, seconds=30, clock=lambda: clock[0])
    cooldown.record_failure("a")
    cooldown.record_success("a")
    cooldown.record_failure("a")
    assert cooldown.available("a")  # the success broke the streak
    cooldown.record_failure("a")
    assert not cooldown.available("a") and cooldown.available("b")
    clock[0] = 30
    assert cooldown.available("a")  # the window is over: worth one more try
    cooldown.record_failure("a")
    assert not cooldown.available("a")  # still failing: straight back into cooldown
    cooldown.record_success("a")
    assert cooldown.available("a")


async def test_a_served_result_reports_the_time_since_the_first_attempt(
    caplog: pytest.LogCaptureFixture,
) -> None:
    router = FallbackProvider([SlowToFailProvider(), FakeProvider(name="anthropic")], Cooldown())
    with caplog.at_level(logging.WARNING, logger="app.llm"):
        result = await router.generate(**ARGS)
    assert result.latency_ms >= 50  # the failed primary's 60 ms included, not the fake's 42
    [failed] = [r.fields for r in caplog.records if r.getMessage() == "llm_fallback"]
    assert 50 <= failed["latency_ms"] <= result.latency_ms  # the failed attempt's own duration


async def test_stream_fallback_records_are_marked_as_stream(
    caplog: pytest.LogCaptureFixture,
) -> None:
    second = FakeProvider(error=UpstreamUnavailable(), name="anthropic")
    router = FallbackProvider(
        [FakeProvider(error=UpstreamUnavailable()), second, FakeProvider(name="replay")], Cooldown()
    )
    with caplog.at_level(logging.WARNING, logger="app.llm"):
        [e async for e in router.stream(**ARGS)]
    records = [r.fields for r in caplog.records if r.getMessage() == "llm_fallback"]
    assert [(f["attempt"], f["fallback"], f["stream"]) for f in records] == [
        (1, False, True),
        (2, True, True),
    ]


async def test_aclose_closes_every_provider_even_if_one_fails() -> None:
    class BrokenClose(FakeProvider):
        async def aclose(self) -> None:
            raise RuntimeError("close failed")

    first, last = FakeProvider(), FakeProvider(name="replay")
    router = FallbackProvider([first, BrokenClose(name="anthropic"), last], Cooldown())
    with pytest.raises(RuntimeError, match="close failed"):
        await router.aclose()
    assert first.closed and last.closed
