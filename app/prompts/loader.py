"""Versioned Jinja2 prompts: app/prompts/<use case>/<version>/<role>.j2."""

import hashlib
import logging
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.context.examples import REFERENCE_ESTIMATIONS
from app.schemas.estimation import DetailLevel, EstimateRequest, OutputFormat, ProjectType

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent
USE_CASE = "estimation"
DEFAULT_VERSION = "v1"
VERSION_PATTERN = re.compile(r"v[1-9]\d*")
# Sent only with an explicit output language, the case where models translate quotes.
EVIDENCE_REMINDER = (
    "Write the narrative in that language, but keep every evidence quote verbatim in the "
    "transcript's original language; do not translate quotes."
)
DEFAULT_LANGUAGE = (
    "The language the transcript is written in, not languages or places mentioned in it"
)
# Our delimiter tags, in any case or spacing, so request data cannot close or open them.
DELIMITER_TAG = re.compile(r"<\s*(/?)\s*(transcript|output_language)\b[^>]*>", re.IGNORECASE)

_env = Environment(
    loader=FileSystemLoader(PROMPTS_DIR),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    auto_reload=False,
    autoescape=False,  # noqa: S701  # plain-text prompts, not HTML: escaping corrupts transcripts
)


@dataclass(frozen=True)
class PromptParams:
    project_type: ProjectType
    detail_level: DetailLevel
    output_format: OutputFormat


# The form's defaults; what the context endpoint shows when no params are given.
DEFAULT_PARAMS = PromptParams(ProjectType.WEB_SAAS, DetailLevel.MEDIUM, OutputFormat.PHASES_TABLE)


@dataclass(frozen=True)
class RenderedPrompt:
    version: str
    system: str
    user: str
    sha256: str


def available_versions() -> list[str]:
    root = PROMPTS_DIR / USE_CASE
    found = [p.name for p in root.iterdir() if p.is_dir() and VERSION_PATTERN.fullmatch(p.name)]
    return sorted(found, key=lambda v: int(v[1:]))


def _check(version: str) -> str:
    if version not in available_versions():
        raise ValueError(f"Unknown prompt version: {version!r}")
    return version


def neutralize(text: str) -> str:
    return DELIMITER_TAG.sub(r"[\1\2]", text)


@cache
def _references() -> list[dict[str, str]]:
    return [
        {
            "size": ref.size,
            "meeting_summary": ref.meeting_summary.strip(),
            "estimation_json": ref.estimation.model_dump_json(),
        }
        for ref in REFERENCE_ESTIMATIONS
    ]


def render_system(params: PromptParams, version: str = DEFAULT_VERSION) -> str:
    template = _env.get_template(f"{USE_CASE}/{_check(version)}/system.j2")
    return template.render(
        references=_references(),
        project_type=params.project_type.value,
        detail_level=params.detail_level.value,
        output_format=params.output_format.value,
    )


def render_estimation_prompt(
    request: EstimateRequest, version: str = DEFAULT_VERSION
) -> tuple[str, str]:
    params = PromptParams(request.project_type, request.detail_level, request.output_format)
    language = re.sub(r"[<>]", "", request.output_language or "") or DEFAULT_LANGUAGE
    user = _env.get_template(f"{USE_CASE}/{_check(version)}/user.j2").render(
        transcript=neutralize(request.transcription),
        project_type=request.project_type.value,
        output_language=language,
        evidence_reminder=EVIDENCE_REMINDER if request.output_language else "",
    )
    return render_system(params, version), user


def render(request: EstimateRequest, version: str = DEFAULT_VERSION) -> RenderedPrompt:
    system, user = render_estimation_prompt(request, version)
    digest = hashlib.sha256(f"{system}\x00{user}".encode()).hexdigest()
    logger.info(
        "prompt_rendered",
        extra={"fields": {"prompt_version": version, "prompt_sha256": digest}},
    )
    return RenderedPrompt(version=version, system=system, user=user, sha256=digest)
