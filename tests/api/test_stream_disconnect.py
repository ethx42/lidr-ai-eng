"""Client disconnect over a real socket (still offline): in-process transports buffer the whole
body, so only a running server shows the upstream stream being closed mid-answer."""

import asyncio
import logging

import httpx2
import pytest
import uvicorn

from app.config import Settings
from app.main import create_app
from tests.factories import TRANSCRIPT
from tests.fakes import SlowFakeProvider


async def test_client_disconnect_closes_upstream(
    unused_tcp_port: int,
    slow_fake: SlowFakeProvider,
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(settings=settings, provider_factory=lambda _: slow_fake)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=unused_tcp_port, log_level="error")
    )
    task = asyncio.create_task(server.serve())
    while not server.started:  # noqa: ASYNC110 - uvicorn exposes startup only as a flag
        await asyncio.sleep(0.01)
    try:
        with caplog.at_level(logging.INFO, logger="app.llm"):
            async with (
                httpx2.AsyncClient() as http,
                http.stream(
                    "POST",
                    f"http://127.0.0.1:{unused_tcp_port}/api/v1/estimate/stream",
                    json={"transcription": TRANSCRIPT},
                ) as r,
            ):
                async for line in r.aiter_lines():
                    if line == "event: partial":
                        break
            await asyncio.wait_for(slow_fake.stream_closed.wait(), timeout=1)
    finally:
        server.should_exit = True
        await task
    [record] = [rec for rec in caplog.records if rec.getMessage() == "llm_call"]
    assert record.fields["outcome"] == "cancelled"
