from app.services.grounding import check_grounding, normalize
from tests.factories import TRANSCRIPT, breakdown, task


def test_all_grounded() -> None:
    report = check_grounding(breakdown(), TRANSCRIPT)
    assert report.requirements_total == 2
    assert report.requirements_grounded == 2
    assert report.ungrounded_requirement_ids == []
    assert report.tasks_without_valid_basis == []
    assert report.score == 1.0


def test_fabricated_requirement() -> None:
    requirements = [
        {"id": "R1", "statement": "Booking", "evidence": "a booking app"},
        {"id": "R2", "statement": "Payments", "evidence": "pay online with Stripe"},
        {"id": "R3", "statement": "Loyalty", "evidence": "we want a loyalty program"},
    ]
    report = check_grounding(breakdown(requirements=requirements), TRANSCRIPT)
    assert report.ungrounded_requirement_ids == ["R3"]
    assert report.score == round(2 / 3, 3)


def test_formatting_only_differences_are_grounded() -> None:
    requirements = [
        {"id": "R1", "statement": "Studio", "evidence": '"A BOOKING  app for our "yoga studio"".'},
        {"id": "R2", "statement": "Launch", "evidence": "mobile   first,\nlaunch"},
    ]
    report = check_grounding(breakdown(requirements=requirements), TRANSCRIPT)
    assert report.ungrounded_requirement_ids == []


def test_dashes_and_curly_quotes_normalized() -> None:
    assert normalize("It’s — “ok”") == normalize('it\'s - "OK"')


def test_dangling_basis() -> None:
    tasks = [task("T1", basis=["R1"]), task("T2", basis=["R9"]), task("T3", basis=["A1", "R7"])]
    report = check_grounding(breakdown(tasks=tasks), TRANSCRIPT)
    assert report.tasks_without_valid_basis == ["T2", "T3"]


def test_empty_requirements_score_one() -> None:
    report = check_grounding(breakdown(requirements=[], tasks=[task(basis=["A1"])]), TRANSCRIPT)
    assert report.requirements_total == 0
    assert report.score == 1.0
