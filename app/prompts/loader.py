"""Versioned Jinja2 prompts: app/prompts/<use case>/<version>/<role>.j2."""

import hashlib
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, meta

from app.attachments.extractor import ExtractedAttachment
from app.context.examples import REFERENCE_ESTIMATIONS
from app.schemas.estimation import DetailLevel, EstimateRequest, OutputFormat, ProjectType
from app.sessions import ProjectMetadata

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
DELIMITER_TAG = re.compile(
    r"<\s*(/?)\s*(transcript|output_language|project_metadata)\b[^>]*>", re.IGNORECASE
)

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


def _fact(value: str) -> str:
    # Model output re-rendered into the system prompt, where every tag is ours: no angle brackets
    # (as for output_language), and one line, so a value cannot forge a list item or a role line.
    return " ".join(re.sub(r"[<>]", "", value).split())


def _neutral_metadata(metadata: ProjectMetadata) -> ProjectMetadata:
    return metadata.model_copy(
        update={
            # Blank once cleaned is absent: "" would still make the metadata non-empty.
            "project_name": _fact(metadata.project_name or "") or None,
            "mentioned_technologies": [
                fact for t in metadata.mentioned_technologies if (fact := _fact(t))
            ],
            "agreed_scope": _fact(metadata.agreed_scope or "") or None,
        }
    )


def renders_attachments(version: str) -> bool:
    """Whether this version's user message shows the attachments (v1 and v2 ignore them)."""
    source = (PROMPTS_DIR / USE_CASE / _check(version) / "user.j2").read_text(encoding="utf-8")
    return "attachments" in meta.find_undeclared_variables(_env.parse(source))


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


# The templates always get `metadata` (system) and `attachments` (user): StrictUndefined raises
# on a missing one. v1 and v2 ignore them.
def render_system(
    params: PromptParams,
    version: str = DEFAULT_VERSION,
    *,
    metadata: ProjectMetadata | None = None,
) -> str:
    template = _env.get_template(f"{USE_CASE}/{_check(version)}/system.j2")
    return template.render(
        references=_references(),
        project_type=params.project_type.value,
        detail_level=params.detail_level.value,
        output_format=params.output_format.value,
        metadata=None if metadata is None else _neutral_metadata(metadata),
    )


def render_estimation_prompt(
    request: EstimateRequest,
    version: str = DEFAULT_VERSION,
    *,
    metadata: ProjectMetadata | None = None,
    attachments: Sequence[ExtractedAttachment] = (),
) -> tuple[str, str]:
    params = PromptParams(request.project_type, request.detail_level, request.output_format)
    language = re.sub(r"[<>]", "", request.output_language or "") or DEFAULT_LANGUAGE
    user = _env.get_template(f"{USE_CASE}/{_check(version)}/user.j2").render(
        transcript=neutralize(request.transcription),
        attachments=[
            {"filename": neutralize(a.filename), "text": neutralize(a.text)} for a in attachments
        ],
        project_type=request.project_type.value,
        output_language=language,
        evidence_reminder=EVIDENCE_REMINDER if request.output_language else "",
    )
    return render_system(params, version, metadata=metadata), user


def render(
    request: EstimateRequest,
    version: str = DEFAULT_VERSION,
    *,
    metadata: ProjectMetadata | None = None,
    attachments: Sequence[ExtractedAttachment] = (),
) -> RenderedPrompt:
    system, user = render_estimation_prompt(
        request, version, metadata=metadata, attachments=attachments
    )
    digest = hashlib.sha256(f"{system}\x00{user}".encode()).hexdigest()
    logger.info(
        "prompt_rendered",
        extra={"fields": {"prompt_version": version, "prompt_sha256": digest}},
    )
    return RenderedPrompt(version=version, system=system, user=user, sha256=digest)
