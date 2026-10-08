import asyncio
import uuid
from collections.abc import Sequence

import httpx2
import pytest
from fastapi import FastAPI

from app.attachments.extractor import Attachment, AttachmentError, ExtractedAttachment
from app.attachments.limits import AttachmentLimits
from app.services import conversation as conversation_module
from app.services.conversation import SessionBusy, SessionNotFound
from tests.api.conftest import ClientFactory
from tests.api.test_estimate_stream import parse_sse
from tests.fakes import FakeProvider, GatedFakeProvider, SpyCache

FORM = {
    "transcript": "Client: We need a booking app for our yoga studio.",
    "project_type": "mobile_app",
    "detail_level": "medium",
    "output_format": "phases_table",
}
TURN_ENDPOINTS = ["estimate", "estimate/stream"]
NOTES = ("attachments", ("notes.txt", b"Meeting notes: launch before the summer.", "text/plain"))
EXE = ("attachments", ("virus.exe", b"MZ\x90\x00\x03\x00\x00\x00", "application/octet-stream"))


@pytest.fixture
def extractions(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """The file names of every extraction the service runs (the real extractor still runs)."""
    seen: list[list[str]] = []
    extract = conversation_module.extract_all_isolated

    def spy(files: Sequence[Attachment], limits: AttachmentLimits) -> list[ExtractedAttachment]:
        seen.append([f.filename for f in files])
        return extract(files, limits)

    monkeypatch.setattr(conversation_module, "extract_all_isolated", spy)
    return seen


async def new_session(client: httpx2.AsyncClient) -> str:
    session_id: str = (await client.post("/sessions")).json()["session_id"]
    return session_id


def error_of(r: httpx2.Response) -> tuple[int, str, str]:
    error = r.json()["error"]
    return r.status_code, error["code"], error["message"]


async def test_create_returns_a_uuid4_session_id(async_client: httpx2.AsyncClient) -> None:
    r = await async_client.post("/sessions")
    assert r.status_code == 201
    assert uuid.UUID(r.json()["session_id"]).version == 4


async def test_get_reports_the_session_and_the_prompt_version_it_sends(
    async_client: httpx2.AsyncClient,
) -> None:
    sid = await new_session(async_client)
    await async_client.post(f"/sessions/{sid}/estimate", data=FORM)
    r = await async_client.get(f"/sessions/{sid}")
    assert r.status_code == 200
    assert r.json() | {"project_metadata": None} == {
        "session_id": sid,
        "project_metadata": None,
        "history_turns": 1,
        "max_turns": 6,
        "prompt_version": "v3",
    }
    assert r.json()["project_metadata"]["project_name"] == "Yoga booking"


@pytest.mark.parametrize("endpoint", ["", *TURN_ENDPOINTS])
async def test_an_unknown_session_is_404(
    async_client: httpx2.AsyncClient, fake_provider: FakeProvider, endpoint: str
) -> None:
    url = f"/sessions/{uuid.uuid4()}/{endpoint}".rstrip("/")
    r = await (async_client.post(url, data=FORM) if endpoint else async_client.get(url))
    assert r.status_code == 404 and r.json()["error"]["code"] == "session_not_found"
    assert fake_provider.calls == []


def test_a_session_evicted_by_the_cap_is_404(make_client: ClientFactory) -> None:
    with make_client(max_sessions=1) as client:
        first = client.post("/sessions").json()["session_id"]
        client.post("/sessions")
        r = client.post(f"/sessions/{first}/estimate", data=FORM)
    assert r.status_code == 404 and r.json()["error"]["code"] == "session_not_found"


@pytest.mark.parametrize("settings", [{"max_sessions": 1}], indirect=True)
async def test_at_the_cap_with_every_turn_in_flight_create_is_503(
    app: FastAPI, async_client: httpx2.AsyncClient
) -> None:
    sid = await new_session(async_client)
    async with app.state.conversation.get(sid).lock:
        r = await async_client.post("/sessions")
    assert error_of(r)[:2] == (503, "sessions_full")
    assert (await async_client.get(f"/sessions/{sid}")).status_code == 200


@pytest.mark.parametrize("endpoint", TURN_ENDPOINTS)
async def test_a_busy_session_is_409_json_before_any_stream(
    app: FastAPI, async_client: httpx2.AsyncClient, fake_provider: FakeProvider, endpoint: str
) -> None:
    sid = await new_session(async_client)
    async with app.state.conversation.get(sid).lock:
        r = await async_client.post(f"/sessions/{sid}/{endpoint}", data=FORM)
    assert r.status_code == 409 and r.headers["content-type"] == "application/json"
    assert r.json()["error"]["code"] == "session_busy"
    assert fake_provider.calls == []


@pytest.mark.parametrize("fake_provider", [pytest.param(GatedFakeProvider(), id="gated")])
async def test_a_turn_while_another_is_in_flight_is_409(
    app: FastAPI, async_client: httpx2.AsyncClient, fake_provider: GatedFakeProvider
) -> None:
    sid = await new_session(async_client)
    first = asyncio.create_task(async_client.post(f"/sessions/{sid}/estimate", data=FORM))
    await asyncio.wait_for(fake_provider.entered.wait(), timeout=1)
    assert app.state.conversation.get(sid).lock.locked()
    second = await async_client.post(f"/sessions/{sid}/estimate", data=FORM)
    fake_provider.release.set()
    assert second.status_code == 409 and second.json()["error"]["code"] == "session_busy"
    assert (await first).json()["history_turns"] == 1


@pytest.mark.parametrize("endpoint", TURN_ENDPOINTS)
async def test_a_session_taken_during_extraction_is_409_json(
    app: FastAPI,
    async_client: httpx2.AsyncClient,
    fake_provider: FakeProvider,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
) -> None:
    sid = await new_session(async_client)
    lock = app.state.conversation.get(sid).lock

    async def extract_while_another_turn_starts(
        files: Sequence[Attachment],
    ) -> list[ExtractedAttachment]:
        await lock.acquire()
        return []

    monkeypatch.setattr(app.state.conversation, "extract", extract_while_another_turn_starts)
    r = await async_client.post(f"/sessions/{sid}/{endpoint}", data=FORM, files=[NOTES])
    lock.release()
    assert r.status_code == 409 and r.json()["error"]["code"] == "session_busy"
    assert fake_provider.calls == []


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [(SessionBusy, "session_busy", True), (SessionNotFound, "session_not_found", False)],
)
async def test_a_session_lost_after_the_checks_becomes_an_error_event(
    app: FastAPI,
    async_client: httpx2.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    error: type[Exception],
    code: str,
    retryable: bool,
) -> None:
    # Another turn takes the session (or the cap evicts it) once the stream has started.
    async def lost(*_: object, **__: object) -> object:
        raise error("lost")
        yield

    sid = await new_session(async_client)
    monkeypatch.setattr(app.state.conversation, "turn_stream", lost)
    r = await async_client.post(f"/sessions/{sid}/estimate/stream", data=FORM)
    assert r.status_code == 200
    [(name, data)] = parse_sse(r.text)
    assert name == "error" and (data["code"], data["retryable"]) == (code, retryable)
    assert data["request_id"] == r.headers["x-request-id"]


@pytest.mark.parametrize("endpoint", TURN_ENDPOINTS)
async def test_an_unsupported_attachment_is_422_json_naming_the_file(
    async_client: httpx2.AsyncClient,
    fake_provider: FakeProvider,
    caplog: pytest.LogCaptureFixture,
    endpoint: str,
) -> None:
    sid = await new_session(async_client)
    r = await async_client.post(f"/sessions/{sid}/{endpoint}", data=FORM, files=[EXE])
    status, code, message = error_of(r)
    assert (status, code) == (422, "invalid_attachment") and "virus.exe" in message
    assert r.headers["content-type"] == "application/json"
    assert fake_provider.calls == []
    [record] = [rec for rec in caplog.records if rec.getMessage() == "attachment_rejected"]
    assert record.exc_info is None


async def test_more_attachments_than_the_limit_are_422_before_extraction(
    async_client: httpx2.AsyncClient, fake_provider: FakeProvider, extractions: list[list[str]]
) -> None:
    sid = await new_session(async_client)
    r = await async_client.post(f"/sessions/{sid}/estimate", data=FORM, files=[NOTES] * 6)
    status, code, message = error_of(r)
    assert (status, code) == (422, "invalid_attachment") and "at most 5" in message
    assert extractions == [] and fake_provider.calls == []


@pytest.mark.parametrize(("size", "status"), [(100, 200), (101, 422)])
def test_an_attachment_over_the_size_limit_is_422_before_extraction(
    make_client: ClientFactory, extractions: list[list[str]], size: int, status: int
) -> None:
    with make_client(attachment_max_bytes=100) as client:
        sid = client.post("/sessions").json()["session_id"]
        big = ("attachments", ("big.txt", b"x" * size, "text/plain"))
        r = client.post(f"/sessions/{sid}/estimate", data=FORM, files=[big])
    assert r.status_code == status
    if status == 422:
        assert r.json()["error"]["code"] == "invalid_attachment"
        assert "big.txt" in r.json()["error"]["message"]
    assert extractions == ([["big.txt"]] if status == 200 else [])


async def test_empty_browser_file_inputs_are_ignored(
    async_client: httpx2.AsyncClient, extractions: list[list[str]]
) -> None:
    # What a browser sends for a file input left empty, then an empty file that has a name.
    body = "".join(
        [
            *(
                f'--b\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
                for name, value in FORM.items()
            ),
            (
                '--b\r\nContent-Disposition: form-data; name="attachments"; filename=""\r\n'
                "Content-Type: application/octet-stream\r\n\r\n\r\n"
            ),
            (
                '--b\r\nContent-Disposition: form-data; name="attachments"; filename="empty.txt"'
                "\r\nContent-Type: text/plain\r\n\r\n\r\n"
            ),
            "--b--\r\n",
        ]
    )
    sid = await new_session(async_client)
    r = await async_client.post(
        f"/sessions/{sid}/estimate",
        content=body.encode(),
        headers={"content-type": "multipart/form-data; boundary=b"},
    )
    assert r.status_code == 200 and extractions == []


async def test_no_free_extraction_slot_is_503(
    async_client: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def busy(files: Sequence[Attachment], limits: AttachmentLimits) -> list[ExtractedAttachment]:
        raise AttachmentError("the server is busy reading other attachments", reason="busy")

    monkeypatch.setattr(conversation_module, "extract_all_isolated", busy)
    sid = await new_session(async_client)
    r = await async_client.post(f"/sessions/{sid}/estimate", data=FORM, files=[NOTES])
    assert error_of(r)[:2] == (503, "attachments_busy")


@pytest.mark.parametrize("endpoint", TURN_ENDPOINTS)
@pytest.mark.parametrize(("chars", "status"), [(10, 200), (11, 422)])
def test_the_transcript_limit_applies_before_extraction(
    make_client: ClientFactory,
    extractions: list[list[str]],
    endpoint: str,
    chars: int,
    status: int,
) -> None:
    with make_client(max_transcription_chars=10) as client:
        sid = client.post("/sessions").json()["session_id"]
        form = FORM | {"transcript": "x" * chars}
        r = client.post(f"/sessions/{sid}/{endpoint}", data=form, files=[NOTES])
    assert r.status_code == status
    if status == 422:
        assert r.json()["error"]["code"] == "invalid_request"
        assert r.json()["error"]["details"] == [
            {
                "loc": ["body", "transcript"],
                "msg": "Transcription exceeds 10 characters.",
                "type": "string_too_long",
            }
        ]
        assert extractions == [] and client.fake.calls == []


@pytest.mark.parametrize("endpoint", TURN_ENDPOINTS)
@pytest.mark.parametrize(
    ("transcript", "status"), [("ab\r\ncd\refgh", 200), ("ab\r\ncd\refghi", 422)]
)
def test_a_line_break_counts_once_against_the_transcript_limit(
    make_client: ClientFactory, endpoint: str, transcript: str, status: int
) -> None:
    # Multipart sends a form's line breaks as CRLF; the composer counts each "\n" as one character.
    with make_client(max_transcription_chars=10) as client:
        sid = client.post("/sessions").json()["session_id"]
        r = client.post(f"/sessions/{sid}/{endpoint}", data=FORM | {"transcript": transcript})
    assert r.status_code == status
    if status == 200:
        sent = client.fake.calls[0]["messages"][-1].content
        assert "ab\ncd\nefgh" in sent and "\r" not in sent


async def test_a_line_break_counts_once_against_the_output_language_limit(
    async_client: httpx2.AsyncClient, fake_provider: FakeProvider
) -> None:
    sid = await new_session(async_client)
    language = "x" * 20 + "\r\n" + "x" * 19  # 41 characters as sent, 40 as typed
    r = await async_client.post(
        f"/sessions/{sid}/estimate", data=FORM | {"output_language": language}
    )
    assert r.status_code == 200
    assert "x" * 20 + "\n" + "x" * 19 in fake_provider.calls[0]["messages"][-1].content


@pytest.mark.parametrize(
    ("form", "loc"),
    [
        ({k: v for k, v in FORM.items() if k != "transcript"}, ["body", "transcript"]),
        (FORM | {"transcript": "   "}, ["body", "transcript"]),
        (FORM | {"project_type": "spaceship"}, ["body", "project_type"]),
        (FORM | {"detail_level": "extreme"}, ["body", "detail_level"]),
        (FORM | {"output_format": "poem"}, ["body", "output_format"]),
        (FORM | {"output_language": "x" * 41}, ["body", "output_language"]),
        (FORM | {"unknown": "x"}, ["body", "unknown"]),
    ],
)
@pytest.mark.parametrize("endpoint", TURN_ENDPOINTS)
async def test_invalid_fields_are_422_json(
    async_client: httpx2.AsyncClient,
    fake_provider: FakeProvider,
    form: dict[str, str],
    loc: list[str],
    endpoint: str,
) -> None:
    sid = await new_session(async_client)
    r = await async_client.post(f"/sessions/{sid}/{endpoint}", data=form)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"
    assert [d["loc"] for d in r.json()["error"]["details"]] == [loc]
    assert fake_provider.calls == []


@pytest.mark.parametrize("language", ["", "   "])
async def test_an_empty_output_language_means_none(
    async_client: httpx2.AsyncClient, fake_provider: FakeProvider, language: str
) -> None:
    sid = await new_session(async_client)
    r = await async_client.post(
        f"/sessions/{sid}/estimate", data=FORM | {"output_language": language}
    )
    assert r.status_code == 200
    assert "do not translate quotes" not in fake_provider.calls[0]["messages"][-1].content


async def test_the_output_language_limit_counts_after_stripping(
    async_client: httpx2.AsyncClient, fake_provider: FakeProvider
) -> None:
    sid = await new_session(async_client)
    language = "  " + "x" * 40 + "  "  # 44 characters, 40 once stripped: accepted, as single-shot
    r = await async_client.post(
        f"/sessions/{sid}/estimate", data=FORM | {"output_language": language}
    )
    assert r.status_code == 200
    assert "x" * 40 in fake_provider.calls[0]["messages"][-1].content


def test_a_body_over_the_upload_limit_is_413(make_client: ClientFactory) -> None:
    with make_client(attachment_max_files=1, attachment_max_bytes=1024) as client:
        sid = client.post("/sessions").json()["session_id"]
        big = ("attachments", ("big.txt", b"x" * (1024 + 1024 * 1024), "text/plain"))
        r = client.post(f"/sessions/{sid}/estimate", data=FORM, files=[big])
    assert r.status_code == 413 and r.headers["x-request-id"]
    assert client.fake.calls == []


async def test_the_stream_sends_partials_then_a_result_with_the_project_metadata(
    async_client: httpx2.AsyncClient,
) -> None:
    sid = await new_session(async_client)
    r = await async_client.post(f"/sessions/{sid}/estimate/stream", data=FORM, files=[NOTES])
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    names = [name for name, _ in events]
    assert names.index("partial") < names.index("result") == len(names) - 1
    result = events[-1][1]
    assert (result["session_id"], result["history_turns"]) == (sid, 1)
    assert result["project_metadata"]["project_name"] == "Yoga booking"
    assert (await async_client.get(f"/sessions/{sid}")).json()["history_turns"] == 1


async def test_a_stream_turn_sees_the_blocking_turn_before_it(
    async_client: httpx2.AsyncClient, fake_provider: FakeProvider
) -> None:
    sid = await new_session(async_client)
    await async_client.post(f"/sessions/{sid}/estimate", data=FORM)
    r = await async_client.post(f"/sessions/{sid}/estimate/stream", data=FORM)
    assert parse_sse(r.text)[-1][1]["history_turns"] == 2
    assert [m.role for m in fake_provider.calls[1]["messages"]] == ["user", "assistant", "user"]


def test_session_turns_bypass_the_cache(make_client: ClientFactory) -> None:
    cache = SpyCache()
    with make_client(cache=cache) as client:
        sid = client.post("/sessions").json()["session_id"]
        for endpoint in TURN_ENDPOINTS:
            assert client.post(f"/sessions/{sid}/{endpoint}", data=FORM).status_code == 200
    assert (cache.gets, cache.sets) == (0, 0)
