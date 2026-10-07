"""Client disconnects mid-answer (offline). In-process HTTP clients buffer the whole body, so these
tests use a real socket, or drive the ASGI app directly with a client that stops reading."""

import asyncio
import contextlib
import json
import logging

import fakeredis
import httpx2
import pytest
import uvicorn
from starlette.types import Message

from app.config import Settings
from app.main import create_app
from app.services.cache import RedisCache
from tests.factories import TRANSCRIPT
from tests.fakes import SlowFakeProvider, TickingFakeProvider


async def test_client_disconnect_closes_upstream(
    unused_tcp_port: int,
    slow_fake: SlowFakeProvider,
    settings: Settings,
    redis_client: fakeredis.FakeAsyncRedis,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(
        settings=settings,
        provider_factory=lambda _: slow_fake,
        cache_factory=lambda _: RedisCache(redis_client, ttl_seconds=60),
    )
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=unused_tcp_port, log_level="error")
    )
    task = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(5):  # a bind failure must fail the test, not hang it
            while not server.started:
                assert not task.done(), "uvicorn exited during startup"
                await asyncio.sleep(0.01)
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
    assert await redis_client.keys("estimate:*") == []


async def test_slow_client_disconnect_closes_upstream_in_the_request_context(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    # A client that stops reading: FastAPI's producer ends up parked on a full buffer with the
    # endpoint generator paused at a `yield`, which no cancellation reaches.
    provider = TickingFakeProvider()
    app = create_app(settings=settings, provider_factory=lambda _: provider)
    body = json.dumps({"transcription": TRANSCRIPT}).encode()
    disconnected = asyncio.Event()
    received = sent_chunks = 0

    async def receive() -> Message:
        nonlocal received
        received += 1
        if received == 1:
            return {"type": "http.request", "body": body, "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        nonlocal sent_chunks
        if message["type"] == "http.response.body":
            sent_chunks += 1
            if sent_chunks > 1:  # the socket buffer is full from here on
                await asyncio.Event().wait()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},  # what uvicorn 0.53 advertises
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/estimate/stream",
        "raw_path": b"/api/v1/estimate/stream",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"application/json"), (b"x-request-id", b"slow-reader")],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    }
    with caplog.at_level(logging.INFO, logger="app.llm"):
        async with app.router.lifespan_context(app):
            request = asyncio.create_task(app(scope, receive, send))
            await asyncio.sleep(1)  # several partials: the buffers fill and the producer parks
            disconnected.set()
            await asyncio.wait_for(provider.stream_closed.wait(), timeout=1)
            # FastAPI 0.141.1 itself ends such a request with BrokenResourceError (its keep-alive
            # task was blocked on the stream it just closed); a hang would still fail here.
            with contextlib.suppress(ExceptionGroup):
                await asyncio.wait_for(request, timeout=1)
    [record] = [rec for rec in caplog.records if rec.getMessage() == "llm_call"]
    assert record.fields["outcome"] == "cancelled"
    assert record.request_id == "slow-reader"
