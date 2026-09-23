import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.context.examples import REFERENCE_ESTIMATIONS, ReferenceEstimation

PROMPT_VERSION = "v1"
PROMPTS_DIR = Path(__file__).parent
# Our delimiter tags, in any case or spacing, so request data cannot close or open them.
DELIMITER_TAG = re.compile(r"<\s*(/?)\s*(transcript|output_language)\b[^>]*>", re.IGNORECASE)


@dataclass(frozen=True)
class PromptBundle:
    version: str
    system_text: str


def render_reference(index: int, ref: ReferenceEstimation) -> str:
    return (
        f'<reference index="{index}" size="{ref.size}">\n'
        f"<meeting_summary>\n{ref.meeting_summary.strip()}\n</meeting_summary>\n"
        f"<estimation>\n{ref.estimation.model_dump_json()}\n</estimation>\n"
        "</reference>"
    )


@lru_cache
def load_prompt() -> PromptBundle:
    template = (PROMPTS_DIR / PROMPT_VERSION / "system.md").read_text(encoding="utf-8")
    references = "\n".join(
        render_reference(i, ref) for i, ref in enumerate(REFERENCE_ESTIMATIONS, start=1)
    )
    return PromptBundle(
        version=PROMPT_VERSION,
        system_text=template.replace("{reference_estimations}", references),
    )


def build_user_message(transcription: str, output_language: str | None) -> str:
    transcript = DELIMITER_TAG.sub(r"[\1\2]", transcription)
    language = re.sub(r"[<>]", "", output_language or "") or "Same language as the transcript"
    return (
        "Estimate the project discussed in this meeting transcript.\n"
        f"<transcript>\n{transcript}\n</transcript>\n"
        f"<output_language>{language}</output_language>"
    )
