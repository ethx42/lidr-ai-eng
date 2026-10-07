from pathlib import Path

import pytest

from evals.run_eval import FRONT_MATTER

PAIRS = [
    ("data/transcripts/course-meeting.md", "web/src/content/samples/course-meeting.md"),
    ("evals/golden/02-medium-clinic-portal.md", "web/src/content/samples/clinic-portal.md"),
    ("evals/golden/03-vague-marketplace.md", "web/src/content/samples/vague-marketplace.md"),
]


@pytest.mark.parametrize(("source", "copy"), PAIRS)
def test_web_samples_match_their_sources(source: str, copy: str) -> None:
    expected = FRONT_MATTER.sub("", Path(source).read_text(encoding="utf-8"))
    assert Path(copy).read_text(encoding="utf-8") == expected
