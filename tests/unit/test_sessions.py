import uuid

import pytest

from app.sessions import ConversationHistory, InMemorySessionStore, ProjectMetadata


def test_window_keeps_last_n_pairs() -> None:
    h = ConversationHistory(max_turns=6)
    for i in range(8):
        h.append(f"u{i}", f"a{i}")
    assert h.turns == 6
    msgs = h.to_messages_list("SYS")
    assert msgs[0] == {"role": "system", "content": "SYS"}
    assert [m["content"] for m in msgs[1:3]] == ["u2", "a2"]
    assert len(msgs) == 1 + 2 * 6


def test_system_prompt_is_always_first_and_current() -> None:
    h = ConversationHistory(max_turns=1)
    h.append("u", "a")
    assert h.to_messages_list("NEW")[0]["content"] == "NEW"


def test_size_cap_drops_oldest_but_keeps_latest_pair() -> None:
    h = ConversationHistory(max_turns=6, max_chars=100)
    h.append("x" * 60, "y" * 10)
    h.append("z" * 500, "w")
    assert h.turns == 1 and h.to_messages_list("S")[1]["content"] == "z" * 500


def test_size_cap_drops_only_as_many_old_pairs_as_needed() -> None:
    h = ConversationHistory(max_turns=6, max_chars=100)
    for i in range(3):
        h.append(f"u{i}" + "x" * 18, f"a{i}" + "y" * 18)
    assert h.turns == 2
    assert [m["content"][:2] for m in h.to_messages_list("S")[1:]] == ["u1", "a1", "u2", "a2"]


def test_sources_slide_out_with_their_pairs() -> None:
    h = ConversationHistory(max_turns=2, max_chars=100)
    for i in range(3):
        h.append(f"u{i}", f"a{i}", source=f"s{i}")
    assert h.sources == ["s1", "s2"]
    h.append("x" * 200, "y", source="big")
    assert h.sources == ["big"]


def test_as_chat_appends_the_new_user_message() -> None:
    h = ConversationHistory(max_turns=2)
    h.append("u1", "a1")
    chat = h.as_chat("u2")
    assert [(m.role, m.content) for m in chat] == [
        ("user", "u1"),
        ("assistant", "a1"),
        ("user", "u2"),
    ]


def test_rejects_non_positive_max_turns() -> None:
    with pytest.raises(ValueError):
        ConversationHistory(max_turns=0)


def test_rejects_non_positive_max_chars() -> None:
    with pytest.raises(ValueError):
        ConversationHistory(max_chars=0)


def test_store_expires_idle_sessions() -> None:
    now = [0.0]
    store = InMemorySessionStore(
        max_turns=6, max_history_chars=60_000, ttl_seconds=10, max_sessions=10, clock=lambda: now[0]
    )
    s = store.create()
    now[0] = 11
    assert store.get(s.id) is None


def test_store_ttl_counts_from_the_last_use() -> None:
    now = [0.0]
    store = InMemorySessionStore(
        max_turns=6, max_history_chars=60_000, ttl_seconds=10, max_sessions=10, clock=lambda: now[0]
    )
    s = store.create()
    now[0] = 5
    assert store.get(s.id) is s
    now[0] = 14
    assert store.get(s.id) is s


def test_store_expired_sessions_do_not_count_toward_the_cap() -> None:
    now = [0.0]
    store = InMemorySessionStore(
        max_turns=6, max_history_chars=60_000, ttl_seconds=10, max_sessions=2, clock=lambda: now[0]
    )
    stale = store.create()
    now[0] = 5
    live = store.create()
    now[0] = 12  # stale expired at 10; live is idle for 7
    fresh = store.create()
    assert store.get(live.id) is live and store.get(fresh.id) is fresh
    assert store.get(stale.id) is None


STORE_SETTINGS = {"max_turns": 6, "max_history_chars": 60_000, "ttl_seconds": 10, "max_sessions": 2}


@pytest.mark.parametrize("field", STORE_SETTINGS)
def test_store_rejects_non_positive_settings(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        InMemorySessionStore(**(STORE_SETTINGS | {field: 0}))


def test_store_evicts_least_recently_used_at_capacity() -> None:
    store = InMemorySessionStore(
        max_turns=6, max_history_chars=60_000, ttl_seconds=100, max_sessions=2
    )
    a, b = store.create(), store.create()
    store.get(a.id)  # a becomes most recent
    store.create()  # evicts b
    assert store.get(b.id) is None and store.get(a.id) is not None


def test_metadata_empty() -> None:
    assert ProjectMetadata().is_empty()
    assert not ProjectMetadata(project_name="X").is_empty()


def test_session_ids_are_dashed_uuid4() -> None:
    store = InMemorySessionStore(
        max_turns=6, max_history_chars=60_000, ttl_seconds=100, max_sessions=2
    )
    session_id = store.create().id
    assert str(uuid.UUID(session_id, version=4)) == session_id
