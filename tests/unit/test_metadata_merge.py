from app.sessions import ProjectMetadata, merge_metadata
from tests.factories import breakdown


def test_first_turn_fills_everything() -> None:
    b = breakdown(
        project_name="Yoga Booking",
        technologies=["Stripe", "React Native"],
        team=[("Backend developer", 1), ("Mobile developer", 2)],
        summary="Booking app.",
    )
    merged, changed = merge_metadata(ProjectMetadata(), b)
    assert merged == ProjectMetadata(
        project_name="Yoga Booking",
        assumed_team_size=3,
        mentioned_technologies=["Stripe", "React Native"],
        agreed_scope="Booking app.",
    )
    assert set(changed) == {
        "project_name",
        "assumed_team_size",
        "mentioned_technologies",
        "agreed_scope",
    }


def test_technologies_union_is_case_insensitive_and_keeps_first_spelling() -> None:
    first, _ = merge_metadata(ProjectMetadata(), breakdown(technologies=["Stripe"]))
    merged, changed = merge_metadata(first, breakdown(technologies=["stripe", "Twilio"]))
    assert merged.mentioned_technologies == ["Stripe", "Twilio"]
    assert "mentioned_technologies" in changed


def test_blank_values_never_erase_known_facts() -> None:
    known = ProjectMetadata(
        project_name="Yoga Booking",
        assumed_team_size=3,
        mentioned_technologies=["Stripe"],
        agreed_scope="Booking app.",
    )
    merged, changed = merge_metadata(
        known, breakdown(project_name="  ", technologies=[], team=[], summary=" ")
    )
    assert merged == known and changed == []


def test_technologies_are_capped() -> None:
    merged, _ = merge_metadata(
        ProjectMetadata(), breakdown(technologies=[f"T{i}" for i in range(50)])
    )
    assert len(merged.mentioned_technologies) == 30
