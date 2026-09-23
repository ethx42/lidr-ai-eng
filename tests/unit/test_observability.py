import json
import logging

import pytest

from app.observability import JsonFormatter, log_llm_call, request_id_var
from app.schemas.estimation import Usage


def test_llm_call_record_fields_and_no_content(caplog: pytest.LogCaptureFixture) -> None:
    token = request_id_var.set("req-1")
    try:
        with caplog.at_level(logging.INFO, logger="app.llm"):
            log_llm_call(
                provider="openai",
                model="gpt-4o-mini",
                prompt_version="v1",
                usage=Usage(input_tokens=10, output_tokens=5, cached_input_tokens=2),
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
    assert payload["latency_ms"] == 123
    assert payload["outcome"] == "ok"
    assert set(payload) >= {"provider", "model", "prompt_version", "output_tokens", "level", "ts"}
