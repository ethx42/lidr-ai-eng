import re
import unicodedata

from app.schemas.estimation import EstimationBreakdown, GroundingReport

_TYPOGRAPHY = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u00ab": '"',
        "\u00bb": '"',
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
    }
)
_QUOTE_EDGES = " \"'.,;:!?-()[]"


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_TYPOGRAPHY).casefold()
    return re.sub(r"\s+", " ", text).strip()


def is_grounded(evidence: str, normalized_transcript: str) -> bool:
    quote = normalize(evidence).strip(_QUOTE_EDGES)
    return bool(quote) and quote in normalized_transcript


def check_grounding(breakdown: EstimationBreakdown, transcript: str) -> GroundingReport:
    normalized = normalize(transcript)
    ungrounded = [r.id for r in breakdown.requirements if not is_grounded(r.evidence, normalized)]
    known_ids = {r.id for r in breakdown.requirements} | {a.id for a in breakdown.assumptions}
    invalid_basis = [t.id for t in breakdown.tasks if not t.basis or not set(t.basis) <= known_ids]
    total = len(breakdown.requirements)
    grounded = total - len(ungrounded)
    return GroundingReport(
        requirements_total=total,
        requirements_grounded=grounded,
        ungrounded_requirement_ids=ungrounded,
        tasks_without_valid_basis=invalid_basis,
        score=round(grounded / total, 3) if total else 1.0,
    )
