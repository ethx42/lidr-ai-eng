import json
import logging

import pytest

from app.observability import (
    CLIENT_LOGGERS,
    JsonFormatter,
    configure_logging,
    log_llm_call,
    request_id_var,
)
from app.schemas.estimation import Usage


def test_llm_call_record_fields_and_no_content(caplog: pytest.LogCaptureFixture) -> None:
    token = request_id_var.set("req-1")
    try:
        with caplog.at_level(logging.INFO, logger="app.llm"):
            log_llm_call(
                provider="openai",
                model="gpt-4o-mini",
                prompt_version="v1",
                usage=Usage(
                    input_tokens=10, output_tokens=5, cached_input_tokens=2, cache_write_tokens=3
                ),
                latency_ms=123,
                outcome="ok",
            )
    finally:
        request_id_var.reset(token)
    [record] = [r for r in caplog.records if r.getMessage() == "llm_call"]
    payload = json.loads(JsonFormatter().format(record))
    assert payload["event"] == "llm_call"
    assert payload["request_id"] == "req-1"
    assert payload["input_tokens"] == 10
    assert payload["cached_input_tokens"] == 2
    assert payload["cache_write_tokens"] == 3
    assert payload["latency_ms"] == 123
    assert payload["outcome"] == "ok"
    assert set(payload) >= {"provider", "model", "prompt_version", "output_tokens", "level", "ts"}


def test_debug_level_keeps_app_debug_and_caps_client_loggers() -> None:
    root = logging.getLogger()
    saved = root.level, list(root.handlers)
    try:
        configure_logging("DEBUG")
        assert logging.getLogger("app.llm").isEnabledFor(logging.DEBUG)
        assert all(
            not logging.getLogger(name).isEnabledFor(logging.DEBUG) for name in CLIENT_LOGGERS
        )
        configure_logging("WARNING")
        assert logging.getLogger("anthropic").getEffectiveLevel() == logging.WARNING
    finally:
        root.setLevel(saved[0])
        root.handlers = saved[1]
        for name in CLIENT_LOGGERS:
            logging.getLogger(name).setLevel(logging.NOTSET)


def test_llm_call_record_carries_stream_cost_attempt_and_cache(
    caplog: pytest.LogCaptureFixture,
) -> None:
    common = {"provider": "openai", "model": "gpt-4o-mini", "prompt_version": "v1", "usage": None}
    with caplog.at_level(logging.INFO, logger="app.llm"):
        log_llm_call(**common, latency_ms=10, outcome="ok")
        log_llm_call(
            **common,
            latency_ms=900,
            outcome="cancelled",
            stream=True,
            ttft_ms=150,
            cost_usd=0.0012,
            attempt=2,
            fallback=True,
            cache="miss",
        )
    blocking, streamed = (
        json.loads(JsonFormatter().format(r))
        for r in caplog.records
        if r.getMessage() == "llm_call"
    )
    keys = ("stream", "ttft_ms", "cost_usd", "attempt", "fallback", "cache")
    assert [blocking[k] for k in keys] == [False, None, None, 1, False, "bypass"]
    assert [streamed[k] for k in keys] == [True, 150, 0.0012, 2, True, "miss"]
    assert streamed["outcome"] == "cancelled"
