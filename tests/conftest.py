import asyncio
import contextlib
import shutil
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import fakeredis
import pytest
from jinja2 import FileSystemLoader

from app.attachments.limits import AttachmentLimits
from app.prompts import loader
from app.services.cache import RedisCache
from app.services.conversation import ConversationService
from app.services.errors import UpstreamUnavailable
from app.services.llm_service import EstimationService
from app.services.providers.base import LLMProvider
from app.sessions import InMemorySessionStore
from tests.factories import make_service
from tests.fakes import FakeProvider, GatedFakeProvider, SlowFakeProvider, SpyCache


@pytest.fixture
def prompts_v99(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A second version without shipping one: v1's templates, also as v99, from a scratch dir."""
    for version in ("v1", "v99"):
        shutil.copytree(loader.PROMPTS_DIR / "estimation" / "v1", tmp_path / "estimation" / version)
    monkeypatch.setattr(loader, "PROMPTS_DIR", tmp_path)
    monkeypatch.setattr(loader, "_env", loader._env.overlay(loader=FileSystemLoader(tmp_path)))


@pytest.fixture
def fake() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def fake_provider(fake: FakeProvider) -> FakeProvider:
    return fake


@pytest.fixture
def slow_fake_provider() -> GatedFakeProvider:
    return GatedFakeProvider()


@pytest.fixture
def spy_cache() -> SpyCache:
    return SpyCache()


@pytest.fixture
def make_conversation(spy_cache: SpyCache) -> Callable[[LLMProvider], ConversationService]:
    def build(provider: LLMProvider) -> ConversationService:
        return ConversationService(
            estimation=make_service(provider, spy_cache),
            store=InMemorySessionStore(
                max_turns=6, max_history_chars=60_000, ttl_seconds=7200, max_sessions=1000
            ),
            limits=AttachmentLimits(),
        )

    return build


@pytest.fixture
def conversation(
    make_conversation: Callable[[LLMProvider], ConversationService], fake_provider: FakeProvider
) -> ConversationService:
    return make_conversation(fake_provider)


@pytest.fixture
def service_with_fake(fake: FakeProvider) -> EstimationService:
    return make_service(fake)


@pytest.fixture
def slow_fake() -> SlowFakeProvider:
    return SlowFakeProvider()


@pytest.fixture
def service_with_slow_fake(slow_fake: SlowFakeProvider) -> EstimationService:
    return make_service(slow_fake)


@pytest.fixture
def service_with_failing_fake() -> EstimationService:
    return make_service(FakeProvider(error=UpstreamUnavailable()))


@pytest.fixture
def redis_client() -> fakeredis.FakeAsyncRedis:
    """A fresh in-memory server per test (named so it never shadows the API `client`)."""
    return fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer(), decode_responses=True)


@pytest.fixture
def service_with_fakeredis(
    fake: FakeProvider, redis_client: fakeredis.FakeAsyncRedis
) -> EstimationService:
    return make_service(fake, RedisCache(redis_client, ttl_seconds=60))


@pytest.fixture
def service_with_fakeredis_failing(redis_client: fakeredis.FakeAsyncRedis) -> EstimationService:
    return make_service(
        FakeProvider(error=UpstreamUnavailable()), RedisCache(redis_client, ttl_seconds=60)
    )


@pytest.fixture
def service_with_fakeredis_slow(
    slow_fake: SlowFakeProvider, redis_client: fakeredis.FakeAsyncRedis
) -> EstimationService:
    return make_service(slow_fake, RedisCache(redis_client, ttl_seconds=60))


@pytest.fixture
async def slow_redis_url() -> AsyncIterator[str]:
    """A live but slow Redis: answers each command, one at a time, 0.1 s after reading it. Every
    reply is well inside the 0.2 s socket timeout, so only the cache's wall-clock bound can stop a
    new connection, which waits for four replies (HELLO, CLIENT MAINT_NOTIFICATIONS, two CLIENT
    SETINFO) before the command's own. It stores nothing (GET is always nil)."""

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        with contextlib.suppress(ConnectionError, asyncio.IncompleteReadError):
            while header := await reader.readline():  # RESP array: *<n>, then $<len> + data each
                args = []
                for _ in range(int(header[1:])):
                    size = int((await reader.readline())[1:])
                    args.append((await reader.readexactly(size + 2))[:-2].upper())
                await asyncio.sleep(0.1)
                match args[0]:
                    case b"HELLO":
                        writer.write(b"%1\r\n+proto\r\n:3\r\n")
                    case b"GET":
                        writer.write(b"_\r\n")
                    case _:
                        writer.write(b"+OK\r\n")
                await writer.drain()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    yield f"redis://{host}:{port}/0"
    server.close()
