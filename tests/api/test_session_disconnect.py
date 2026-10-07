"""A client that leaves a session stream mid-answer must release the session: the next turn is not
a 409 and the history is unchanged. In-process HTTP clients buffer the whole body, so these tests
use a real socket, or drive the ASGI app directly with a client that stops reading."""

import asyncio
from urllib.parse import urlencode

import httpx2
import uvicorn
from starlette.types import Message

from app.config import Settings
from app.main import create_app
from tests.fakes import SlowFakeProvider, TickingFakeProvider

FORM = {
    "transcript": "Client: We need a booking app for our yoga studio.",
    "project_type": "mobile_app",
    "detail_level": "medium",
    "output_format": "phases_table",
}


async def test_leaving_a_session_stream_releases_the_session(
    unused_tcp_port: int, slow_fake: SlowFakeProvider, settings: Settings
) -> None:
    app = create_app(settings=settings, provider_factory=lambda _: slow_fake)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=unused_tcp_port, log_level="error")
    )
    task = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(5):  # a bind failure must fail the test, not hang it
            while not server.started:
                assert not task.done(), "uvicorn exited during startup"
                await asyncio.sleep(0.01)
        async with httpx2.AsyncClient(base_url=f"http://127.0.0.1:{unused_tcp_port}") as http:
            sid = (await http.post("/sessions")).json()["session_id"]
            async with http.stream("POST", f"/sessions/{sid}/estimate/stream", data=FORM) as r:
                async for line in r.aiter_lines():
                    if line == "event: partial":
                        break
            await asyncio.wait_for(slow_fake.stream_closed.wait(), timeout=1)
            # SlowFakeProvider.generate answers at once: only a held session could stop this turn.
            after = await http.post(f"/sessions/{sid}/estimate", data=FORM)
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=5)  # a server that never stops must not hang the run
    assert after.status_code == 200 and after.json()["history_turns"] == 1


async def test_a_slow_reader_leaving_releases_the_session(settings: Settings) -> None:
    # A client that stops reading: FastAPI's producer ends up parked on a full buffer with the
    # endpoint generator paused at a `yield`, which no cancellation reaches.
    provider = TickingFakeProvider()
    app = create_app(settings=settings, provider_factory=lambda _: provider)
    body = urlencode(FORM).encode()
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

    async with app.router.lifespan_context(app):
        session = app.state.conversation.start()
        path = f"/sessions/{session.id}/estimate/stream"
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},  # what uvicorn 0.53 advertises
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"127.0.0.1:8000"),
                (b"content-type", b"application/x-www-form-urlencoded"),
                (b"content-length", str(len(body)).encode()),
            ],
            "client": ("127.0.0.1", 50000),
            "server": ("127.0.0.1", 8000),
        }
        request = asyncio.create_task(app(scope, receive, send))
        await asyncio.sleep(1)  # several partials: the buffers fill and the producer parks
        assert session.lock.locked()
        disconnected.set()
        await asyncio.wait_for(provider.stream_closed.wait(), timeout=1)
        await asyncio.wait_for(request, timeout=1)
        assert not session.lock.locked()
        assert session.history.turns == 0
