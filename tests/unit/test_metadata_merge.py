from app.sessions import MAX_TECHNOLOGIES, ProjectMetadata, merge_metadata
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


KNOWN = ProjectMetadata(
    project_name="Yoga Booking",
    assumed_team_size=3,
    mentioned_technologies=["Stripe"],
    agreed_scope="Booking app.",
)
SAME_AS_KNOWN = {
    "project_name": "Yoga Booking",
    "team": [("Full-stack developer", 3)],
    "technologies": ["Stripe"],
    "summary": "Booking app.",
}


def test_later_name_and_summary_replace_the_known_ones() -> None:
    merged, changed = merge_metadata(
        KNOWN,
        breakdown(**SAME_AS_KNOWN | {"project_name": "Studio Pass", "summary": "Passes app."}),
    )
    assert (merged.project_name, merged.agreed_scope) == ("Studio Pass", "Passes app.")
    assert changed == ["project_name", "agreed_scope"]


def test_smaller_latest_team_replaces_the_known_size() -> None:
    merged, changed = merge_metadata(
        KNOWN, breakdown(**SAME_AS_KNOWN | {"team": [("Full-stack developer", 2)]})
    )
    assert merged.assumed_team_size == 2
    assert changed == ["assumed_team_size"]


def test_one_field_change_reports_exactly_that_field() -> None:
    merged, changed = merge_metadata(
        KNOWN, breakdown(**SAME_AS_KNOWN | {"summary": "Booking app with a waitlist."})
    )
    assert merged == KNOWN.model_copy(update={"agreed_scope": "Booking app with a waitlist."})
    assert changed == ["agreed_scope"]


def test_overlong_technology_names_are_dropped() -> None:
    merged, _ = merge_metadata(
        ProjectMetadata(), breakdown(technologies=["Stripe", "x" * 81, "y" * 80])
    )
    assert merged.mentioned_technologies == ["Stripe", "y" * 80]


def test_full_list_keeps_known_entries_and_drops_new_names_silently() -> None:
    full = KNOWN.model_copy(
        update={"mentioned_technologies": [f"T{i}" for i in range(MAX_TECHNOLOGIES)]}
    )
    merged, changed = merge_metadata(
        full, breakdown(**SAME_AS_KNOWN | {"technologies": ["Twilio", "t0", "Stripe"]})
    )
    assert merged == full
    assert changed == []
