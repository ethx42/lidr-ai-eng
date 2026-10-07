import asyncio
import logging
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from app.attachments.extractor import Attachment, AttachmentError, ExtractedAttachment
from app.attachments.limits import AttachmentLimits
from app.schemas.session import TurnResponse
from app.schemas.stream import PartialEvent, StatusEvent
from app.services import conversation as conversation_module
from app.services import llm_service
from app.services.conversation import ConversationService, SessionBusy, SessionNotFound
from app.services.errors import UpstreamUnavailable
from app.services.providers.fallback import Cooldown, FallbackProvider
from app.services.rendering import render_compact
from app.sessions import ProjectMetadata
from tests.factories import breakdown, typed_request
from tests.fakes import FakeProvider, GatedFakeProvider, SlowFakeProvider, SpyCache

MakeConversation = Callable[..., ConversationService]
SPEC_PDF = Path("tests/fixtures/attachments/spec.pdf").read_bytes()


def records(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, object]]:
    return [r.fields for r in caplog.records if r.getMessage() == event]


async def test_two_turns_update_metadata_and_history(conversation, fake_provider) -> None:
    s = conversation.start()
    fake_provider.queue(breakdown(project_name="Yoga Booking", technologies=["Stripe"]))
    r1 = await conversation.turn(s.id, typed_request(transcription="first transcript"), [])
    fake_provider.queue(breakdown(project_name="Yoga Booking", technologies=["Twilio"]))
    r2 = await conversation.turn(s.id, typed_request(transcription="second transcript"), [])
    assert r1.history_turns == 1 and r2.history_turns == 2
    assert r2.project_metadata.mentioned_technologies == ["Stripe", "Twilio"]
    assert r2.metadata_changes == ["mentioned_technologies"]
    second_call = fake_provider.calls[1]
    assert [m.role for m in second_call["messages"]] == ["user", "assistant", "user"]
    assert "Yoga Booking" in second_call["system"]  # metadata injected


async def test_attachment_text_reaches_prompt_and_grounding(conversation, fake_provider) -> None:
    s = conversation.start()
    pdf = Attachment("spec.pdf", SPEC_PDF)
    fake_provider.queue(
        breakdown(requirements=[("R1", "Offline payments", "offline payments via Redsys")])
    )
    r = await conversation.turn(
        s.id, typed_request(transcription="we need payments"), await conversation.extract([pdf])
    )
    assert "ATTACHMENT-MARKER" in fake_provider.calls[0]["messages"][-1].content
    assert r.grounding.ungrounded_requirement_ids == []  # quote found in the attachment


@pytest.mark.parametrize(("max_turns", "grounded"), [(6, True), (1, False)])
async def test_quotes_from_earlier_turns_are_grounded_while_the_model_still_sees_them(
    make_conversation: MakeConversation, max_turns: int, grounded: bool
) -> None:
    provider = FakeProvider()
    conversation = make_conversation(provider, max_turns=max_turns)
    s = conversation.start()
    await conversation.turn(s.id, typed_request("Client: Payments must work offline."), [])
    await conversation.turn(s.id, typed_request("Client: Add a loyalty card."), [])
    provider.queue(breakdown(requirements=[("R1", "Offline payments", "must work offline")]))
    r = await conversation.turn(s.id, typed_request("Client: And a gift shop."), [])
    # With one turn kept, the first has slid out of the window: the model no longer saw it.
    seen = " ".join(m.content for m in provider.calls[-1]["messages"])
    assert ("must work offline" in seen) is grounded
    assert r.grounding.ungrounded_requirement_ids == ([] if grounded else ["R1"])


async def test_grounding_source_is_the_turn_then_the_windowed_client_texts(
    conversation: ConversationService,
    fake_provider: FakeProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources: list[str] = []
    check = llm_service.check_grounding
    monkeypatch.setattr(
        llm_service, "check_grounding", lambda b, source: sources.append(source) or check(b, source)
    )
    s = conversation.start()
    fake_provider.queue(breakdown(project_name="Yoga Booking"))
    r1 = await conversation.turn(s.id, typed_request("first transcript"), [])
    notes = ExtractedAttachment("notes.txt", "text", "second notes", None)
    await conversation.turn(s.id, typed_request("second transcript"), [notes])
    assert sources[1].startswith("second transcript\n\n--- attachment: notes.txt ---\nsecond notes")
    assert "first transcript" in sources[1]
    # Raw client text only: none of the prompt's own scaffolding.
    assert "<transcript>" not in sources[1] and "Project type" not in sources[1]
    # Never the system prompt, the metadata block or the model's own (assistant) turns.
    assert "<project_metadata>" not in sources[1] and "Yoga Booking" not in sources[1]
    assert render_compact(r1.breakdown) not in sources[1]


async def test_raw_client_text_kept_for_grounding_stays_within_the_history_cap(
    make_conversation: MakeConversation,
) -> None:
    provider = FakeProvider()
    conversation = make_conversation(provider, max_history_chars=20_000)
    s = conversation.start()
    # Neutralised, the tag and its 10,000 characters of attributes become "[transcript]".
    transcript = "<transcript " + "x" * 10_000 + ">Client: a booking app."
    for _ in range(6):
        await conversation.turn(s.id, typed_request(transcript), [])
    assert len(provider.calls[-1]["messages"][-1].content) < 2_000  # the model saw little
    assert sum(len(source) for source in conversation.get(s.id).history.sources) <= 20_000


@pytest.mark.parametrize(
    "scaffolding", ["Spanish", "Project type: web_saas", "do not translate quotes"]
)
async def test_prompt_scaffolding_from_earlier_turns_is_never_evidence(
    conversation: ConversationService, fake_provider: FakeProvider, scaffolding: str
) -> None:
    s = conversation.start()
    first = typed_request("Client: Payments must work offline.", output_language="Spanish")
    await conversation.turn(s.id, first, [])
    assert scaffolding in fake_provider.calls[0]["messages"][-1].content  # the model saw it
    fake_provider.queue(breakdown(requirements=[("R1", "Scaffold", scaffolding)]))
    r = await conversation.turn(s.id, typed_request("Client: Add a loyalty card."), [])
    assert r.grounding.ungrounded_requirement_ids == ["R1"]


async def test_attachments_a_version_does_not_render_are_never_evidence(
    conversation: ConversationService, fake_provider: FakeProvider
) -> None:
    s = conversation.start()
    notes = ExtractedAttachment("notes.txt", "text", "offline payments via Redsys", None)
    fake_provider.queue(breakdown(requirements=[("R1", "Offline", "offline payments via Redsys")]))
    r1 = await conversation.turn(s.id, typed_request("a"), [notes], prompt_version="v2")
    assert "Redsys" not in fake_provider.calls[0]["messages"][-1].content  # v2 ignores them
    fake_provider.queue(breakdown(requirements=[("R1", "Offline", "offline payments via Redsys")]))
    r2 = await conversation.turn(s.id, typed_request("b"), [])
    assert r1.grounding.ungrounded_requirement_ids == r2.grounding.ungrounded_requirement_ids
    assert r2.grounding.ungrounded_requirement_ids == ["R1"]


async def test_a_commit_that_fails_leaves_the_session_unchanged(
    conversation: ConversationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object) -> None:
        raise RuntimeError("merge failed")

    monkeypatch.setattr(conversation_module, "merge_metadata", broken)
    s = conversation.start()
    with pytest.raises(RuntimeError):
        await conversation.turn(s.id, typed_request(), [])
    session = conversation.get(s.id)
    assert session.history.turns == 0 and session.metadata == ProjectMetadata()
    assert not session.lock.locked()


async def test_cancelling_a_turn_mid_call_releases_the_session_unchanged(
    make_conversation: MakeConversation, slow_fake_provider: GatedFakeProvider
) -> None:
    conversation = make_conversation(slow_fake_provider)
    s = conversation.start()
    task = asyncio.create_task(conversation.turn(s.id, typed_request(), []))
    await asyncio.sleep(0)  # parked in the provider call, holding the lock
    assert conversation.get(s.id).lock.locked()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    session = conversation.get(s.id)
    assert not session.lock.locked()
    assert session.history.turns == 0 and session.metadata == ProjectMetadata()
    slow_fake_provider.release.set()
    assert (await conversation.turn(s.id, typed_request(), [])).history_turns == 1


async def test_leaving_the_stream_at_validating_leaves_the_session_unchanged(
    conversation: ConversationService,
) -> None:
    # The response is built, but the turn has not reached the client yet.
    s = conversation.start()
    items = conversation.turn_stream(s.id, typed_request(), [])
    async for item in items:
        if isinstance(item, StatusEvent) and item.phase == "validating":
            break
    await items.aclose()
    session = conversation.get(s.id)
    assert not session.lock.locked()
    assert session.history.turns == 0 and session.metadata == ProjectMetadata()


async def test_concurrent_turn_on_same_session_is_rejected(
    make_conversation, slow_fake_provider
) -> None:
    conversation = make_conversation(slow_fake_provider)
    s = conversation.start()
    first = asyncio.create_task(conversation.turn(s.id, typed_request(transcription="a"), []))
    await asyncio.sleep(0)
    with pytest.raises(SessionBusy):
        async with asyncio.timeout(1):  # waiting on the lock would hang until the release
            await conversation.turn(s.id, typed_request(transcription="b"), [])
    slow_fake_provider.release.set()
    await first


async def test_failed_turn_leaves_history_unchanged(conversation, fake_provider) -> None:
    s = conversation.start()
    fake_provider.error = UpstreamUnavailable()
    with pytest.raises(UpstreamUnavailable):
        await conversation.turn(s.id, typed_request(transcription="a"), [])
    assert conversation.get(s.id).history.turns == 0


async def test_conversation_never_uses_the_cache(conversation, spy_cache) -> None:
    s = conversation.start()
    await conversation.turn(s.id, typed_request(transcription="a"), [])
    assert spy_cache.gets == 0 and spy_cache.sets == 0


async def test_history_holds_the_user_prompt_and_the_compact_answer(
    conversation: ConversationService, fake_provider: FakeProvider
) -> None:
    s = conversation.start()
    r1 = await conversation.turn(s.id, typed_request(transcription="first transcript"), [])
    await conversation.turn(s.id, typed_request(transcription="second transcript"), [])
    first, second = fake_provider.calls
    assert second["messages"][0] == first["messages"][-1]
    assert second["messages"][1].content == render_compact(r1.breakdown)
    assert "first transcript" in second["messages"][0].content
    assert "second transcript" in second["messages"][-1].content


async def test_turns_render_the_conversation_prompt_version(
    conversation: ConversationService, fake_provider: FakeProvider
) -> None:
    # The estimation service's own default (single-shot) is v1 here.
    s = conversation.start()
    assert conversation.prompt_version == "v3"
    r = await conversation.turn(s.id, typed_request(), [])
    assert r.prompt_version == "v3" and "<project_metadata>" in fake_provider.calls[0]["system"]
    pinned = await conversation.turn(s.id, typed_request(), [], prompt_version="v2")
    assert pinned.prompt_version == "v2"


async def test_the_fallback_record_names_the_turns_prompt_version(
    make_conversation: MakeConversation, caplog: pytest.LogCaptureFixture
) -> None:
    primary = FakeProvider(error=UpstreamUnavailable(), model="gpt-4o-mini")
    secondary = FakeProvider(name="anthropic", model="claude-haiku-4-5")
    conversation = make_conversation(FallbackProvider([primary, secondary], Cooldown()))
    s = conversation.start()
    with caplog.at_level(logging.INFO, logger="app.llm"):
        await conversation.turn(s.id, typed_request(), [])
    [fallback] = records(caplog, "llm_fallback")
    assert fallback["prompt_version"] == "v3"


@pytest.mark.parametrize("stream", [False, True])
async def test_turns_log_a_cache_bypass(
    conversation: ConversationService, spy_cache: SpyCache, stream: bool, caplog
) -> None:
    s = conversation.start()
    with caplog.at_level(logging.INFO, logger="app.llm"):
        if stream:
            [_ async for _ in conversation.turn_stream(s.id, typed_request(), [])]
        else:
            await conversation.turn(s.id, typed_request(), [])
    [call] = records(caplog, "llm_call")
    assert (call["cache"], call["stream"], call["outcome"]) == ("bypass", stream, "ok")
    assert spy_cache.gets == 0 and spy_cache.sets == 0


async def test_an_unknown_session_is_not_found(conversation: ConversationService) -> None:
    with pytest.raises(SessionNotFound):
        conversation.get("no-such-session")
    with pytest.raises(SessionNotFound):
        await conversation.turn("no-such-session", typed_request(), [])
    with pytest.raises(SessionNotFound):
        await anext(conversation.turn_stream("no-such-session", typed_request(), []))


async def test_stream_turn_updates_the_session_after_the_final_response(
    conversation: ConversationService, fake_provider: FakeProvider
) -> None:
    s = conversation.start()
    fake_provider.queue(breakdown(project_name="Yoga Booking", technologies=["Stripe"]))
    items = conversation.turn_stream(s.id, typed_request(), [])
    seen: list[StatusEvent | PartialEvent | TurnResponse] = []
    async for item in items:
        if not isinstance(item, TurnResponse):
            assert conversation.get(s.id).history.turns == 0  # nothing committed mid-stream
        seen.append(item)
    *events, result = seen
    assert isinstance(events[0], StatusEvent) and events[0].phase == "calling_llm"
    assert any(isinstance(e, PartialEvent) for e in events)
    assert isinstance(result, TurnResponse) and result.session_id == s.id
    assert result.history_turns == 1 and result.metadata_changes == [
        "project_name",
        "assumed_team_size",
        "mentioned_technologies",
        "agreed_scope",
    ]
    session = conversation.get(s.id)
    assert session.history.turns == 1 and session.metadata == result.project_metadata
    assert not session.lock.locked()


@pytest.mark.parametrize("how", ["aclose", "cancel"])
async def test_leaving_mid_stream_releases_the_session_with_history_unchanged(
    make_conversation: MakeConversation, how: str
) -> None:
    provider = SlowFakeProvider()  # one delta, then stalls
    conversation = make_conversation(provider)
    s = conversation.start()
    items = conversation.turn_stream(s.id, typed_request(), [])
    if how == "aclose":
        await anext(items)  # calling_llm
        await anext(items)  # first partial
        await items.aclose()
    else:
        streaming = asyncio.Event()

        async def consume() -> None:
            async for item in items:
                if isinstance(item, PartialEvent):
                    streaming.set()

        task = asyncio.create_task(consume())
        await streaming.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert provider.closed_streams == 1
    session = conversation.get(s.id)
    assert not session.lock.locked()
    assert session.history.turns == 0 and session.metadata == ProjectMetadata()
    assert (await conversation.turn(s.id, typed_request(), [])).history_turns == 1


async def test_a_turn_while_a_stream_is_in_flight_is_rejected(
    make_conversation: MakeConversation,
) -> None:
    conversation = make_conversation(SlowFakeProvider())
    s = conversation.start()
    items = conversation.turn_stream(s.id, typed_request(transcription="a"), [])
    await anext(items)
    with pytest.raises(SessionBusy):
        await conversation.turn(s.id, typed_request(transcription="b"), [])
    with pytest.raises(SessionBusy):
        await anext(conversation.turn_stream(s.id, typed_request(transcription="b"), []))
    await items.aclose()
    assert conversation.get(s.id).history.turns == 0


async def test_a_failed_stream_turn_leaves_history_unchanged(
    make_conversation: MakeConversation,
) -> None:
    provider = FakeProvider(stream_error_after_chunks=1, stream_error=UpstreamUnavailable())
    conversation = make_conversation(provider)
    s = conversation.start()
    with pytest.raises(UpstreamUnavailable):
        [_ async for _ in conversation.turn_stream(s.id, typed_request(), [])]
    session = conversation.get(s.id)
    assert session.history.turns == 0 and not session.lock.locked()


async def test_sessions_do_not_share_a_lock(
    make_conversation: MakeConversation, slow_fake_provider: GatedFakeProvider
) -> None:
    conversation = make_conversation(slow_fake_provider)
    a, b = conversation.start(), conversation.start()
    first = asyncio.create_task(conversation.turn(a.id, typed_request(), []))
    await asyncio.sleep(0)
    second = asyncio.create_task(conversation.turn(b.id, typed_request(), []))
    await asyncio.sleep(0)
    slow_fake_provider.release.set()
    assert [r.session_id for r in await asyncio.gather(first, second)] == [a.id, b.id]


async def test_extract_runs_the_isolated_extractor_off_the_event_loop(
    conversation: ConversationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[threading.Thread, AttachmentLimits]] = []

    def isolated(
        files: Sequence[Attachment], limits: AttachmentLimits
    ) -> list[ExtractedAttachment]:
        seen.append((threading.current_thread(), limits))
        return [ExtractedAttachment(f.filename, "text", "x", None) for f in files]

    monkeypatch.setattr(conversation_module, "extract_all_isolated", isolated)
    extracted = await conversation.extract([Attachment("notes.txt", b"x")])
    assert [a.filename for a in extracted] == ["notes.txt"]
    [(thread, limits)] = seen
    assert thread is not threading.main_thread() and limits is conversation.limits


async def test_an_unreadable_attachment_fails_extraction(
    conversation: ConversationService,
) -> None:
    with pytest.raises(AttachmentError) as caught:
        await conversation.extract([Attachment("spec.pdf", b"MZ\x90\x00\x03\x00\x00\x00")])
    assert caught.value.reason == "invalid"
