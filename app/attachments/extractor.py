"""Local text extraction for turn attachments (PDF, DOCX, plain text). Sync and CPU-bound: the
service runs it through `app.attachments.isolation.extract_all_isolated`, in a child process."""

import io
import logging
import time
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

import pypdf
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.attachments.limits import AttachmentLimits

__all__ = [
    "Attachment",
    "AttachmentError",
    "AttachmentLimits",
    "ExtractedAttachment",
    "detect_kind",
    "extract_all",
    "format_attachments",
]

Kind = Literal["pdf", "docx", "text"]

ZIP_MAGIC = b"PK\x03\x04"
MAX_NAME_CHARS = 120
TRUNCATED = "\n[truncated]"
UNSUPPORTED = "unsupported file type (PDF, DOCX or plain text only)"
NO_TEXT = "no extractable text"
# Decoded size cap for any one PDF stream; pypdf parses page content at about 1 s per MB.
PDF_STREAM_BYTES = 4 * 1024 * 1024
# What Word writes. zipfile's bzip2 and LZMA readers inflate a whole chunk in one call.
DOCX_COMPRESSION = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
# "<" bytes across every member: lxml holds about 130 bytes per element, and Word writes about
# 25 per paragraph, so this allows some 40,000 paragraphs in about 130 MB. Every member, not only
# *.xml: python-docx parses a part by its content type, whatever its name; binary media add about
# one per 256 bytes (some 200,000 at the 50 MB uncompressed cap).
DOCX_MAX_TAGS = 1_000_000

logger = logging.getLogger(__name__)
# Malformed PDFs make pypdf log a warning per repaired object.
logging.getLogger("pypdf").setLevel(logging.ERROR)


@dataclass(frozen=True)
class Attachment:
    filename: str
    data: bytes


@dataclass(frozen=True)
class ExtractedAttachment:
    filename: str
    kind: Kind
    text: str
    pages: int | None


class AttachmentError(ValueError):
    """The message is safe to show to the user. `reason` is "busy" when the server had no free
    extraction slot (worth retrying), else "invalid" (the file itself)."""

    def __init__(self, message: str, reason: Literal["invalid", "busy"] = "invalid") -> None:
        super().__init__(message)
        self.reason = reason


def unreadable(label: str, exc: Exception) -> AttachmentError:
    # The type name only: parser messages can quote the document.
    logger.warning("attachment parse failed: %s", type(exc).__name__)
    return AttachmentError(f"unreadable {label}")


def sanitise_name(name: str) -> str:
    clean = "".join(c for c in name if c.isprintable() and c not in "<>").strip()
    return clean[:MAX_NAME_CHARS] or "attachment"


def megabytes(size: int) -> str:
    return f"{size / 1_048_576:.3g} MB"


def is_docx(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return "word/document.xml" in archive.namelist()
    # ValueError: a name flagged UTF-8 that is not; NotImplementedError: an unknown zip version.
    except (zipfile.BadZipFile, ValueError, NotImplementedError):
        return False


def is_text(data: bytes) -> bool:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return b"\x00" not in data


def detect_kind(data: bytes) -> Kind:
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(ZIP_MAGIC):
        if is_docx(data):
            return "docx"
    elif is_text(data):
        return "text"
    raise AttachmentError(UNSUPPORTED)


def pdf_text(
    data: bytes, pages_left: int, max_pages: int, chars_left: int, deadline: float
) -> tuple[str, int]:
    texts: list[str] = []
    try:
        with pypdf.apply_configuration(
            zlib_maximum_output_length=PDF_STREAM_BYTES,
            array_based_stream_maximum_output_length=PDF_STREAM_BYTES,
            lzw_maximum_output_length=PDF_STREAM_BYTES,
            run_length_maximum_output_length=PDF_STREAM_BYTES,
            page_tree_maximum_entries=10_000,
        ):
            reader = pypdf.PdfReader(io.BytesIO(data))
            # Before any page access: a user-password PDF raises FileNotDecryptedError there.
            if reader.is_encrypted and reader.decrypt("") == pypdf.PasswordType.NOT_DECRYPTED:
                raise AttachmentError("password-protected PDFs are not supported")
            pages = len(reader.pages)
            if pages > pages_left:
                raise AttachmentError(f"too many pages (at most {max_pages} per turn)")
            extracted = 0
            for page in reader.pages:
                if extracted >= chars_left:
                    break
                # Defence in depth: the child process is killed at the same timeout anyway.
                if time.monotonic() > deadline:
                    raise AttachmentError("took too long to read")
                if text := page.extract_text().strip():
                    texts.append(text)
                    extracted += len(text) + 2
    except (AttachmentError, MemoryError):
        raise
    # Besides PyPdfError and DependencyError, malformed files raise bare KeyError, AttributeError,
    # TypeError, ValueError or NotImplementedError (fuzzed on pypdf 6.19). RecursionError (deeply
    # nested objects) is the document's fault too.
    except Exception as exc:
        raise unreadable("PDF", exc) from exc
    if not texts:
        raise AttachmentError(f"{NO_TEXT} (scanned PDF?)")
    return "\n\n".join(texts), pages


def block_lines(block: Paragraph | Table) -> list[str]:
    if isinstance(block, Paragraph):
        return [block.text]
    # A horizontally merged cell repeats the same _Cell object in its row.
    return [" | ".join(cell.text for cell in dict.fromkeys(row.cells)) for row in block.rows]


def repacked(data: bytes, max_uncompressed: int) -> io.BytesIO:
    """python-docx has no zip-bomb guard, and zipfile's read() inflates a whole member before
    cutting it at its declared size. Check the members, then copy them out in bounded reads (which
    stop at the declared size) into an uncompressed archive."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(out, "w") as copy:
        members = [info for info in source.infolist() if not info.is_dir()]
        if any(info.compress_type not in DOCX_COMPRESSION for info in members):
            raise AttachmentError("unsupported DOCX compression (only stored or deflated)")
        if len({info.filename for info in members}) < len(members):
            raise AttachmentError("unreadable DOCX (duplicate entries)")
        if sum(info.file_size for info in members) > max_uncompressed:
            raise AttachmentError(
                f"DOCX too large uncompressed (limit {megabytes(max_uncompressed)})"
            )
        tags = 0
        for info in members:
            with source.open(info) as member, copy.open(info.filename, "w") as target:
                while chunk := member.read(64 * 1024):
                    tags += chunk.count(b"<")
                    target.write(chunk)
        if tags > DOCX_MAX_TAGS:
            raise AttachmentError("DOCX too complex (too many XML elements)")
    out.seek(0)
    return out


def docx_text(data: bytes, max_uncompressed: int) -> str:
    try:
        document = Document(repacked(data, max_uncompressed))
        lines = [line for block in document.iter_inner_content() for line in block_lines(block)]
    except (AttachmentError, MemoryError):
        raise
    # Not only BadZipFile, KeyError and ValueError: lxml's XMLSyntaxError (a SyntaxError), a part
    # with an unexpected root (AttributeError), corrupt members (zlib.error, a CRC BadZipFile).
    except Exception as exc:
        raise unreadable("DOCX", exc) from exc
    return "\n".join(line for line in lines if line.strip())


def extract_one(
    data: bytes, limits: AttachmentLimits, pages_left: int, chars_left: int, deadline: float
) -> tuple[Kind, str | None, int | None]:
    """Kind, text (None when the character budget is already spent) and PDF page count."""
    if len(data) > limits.max_bytes:
        raise AttachmentError(f"larger than {megabytes(limits.max_bytes)}")
    kind = detect_kind(data)
    if not chars_left:
        return kind, None, None
    if kind == "pdf":
        text, pages = pdf_text(data, pages_left, limits.max_pages, chars_left, deadline)
        return kind, text, pages
    if kind == "docx":
        text = docx_text(data, limits.max_docx_uncompressed)
    else:
        text = data.decode("utf-8-sig")
    if not text.strip():
        raise AttachmentError(NO_TEXT)
    return kind, text, None


def extract_all(
    files: Sequence[Attachment],
    limits: AttachmentLimits,
    *,
    on_file: Callable[[str], None] | None = None,
) -> list[ExtractedAttachment]:
    """`on_file` gets each sanitised name before that file is read (the child reports progress)."""
    if len(files) > limits.max_files:
        raise AttachmentError(f"too many attachments (at most {limits.max_files} per turn)")
    chars_left, pages_left = limits.max_chars, limits.max_pages
    deadline = time.monotonic() + limits.timeout_seconds
    extracted: list[ExtractedAttachment] = []
    for file in files:
        name = sanitise_name(file.filename)
        if on_file:
            on_file(name)
        try:
            kind, text, pages = extract_one(file.data, limits, pages_left, chars_left, deadline)
        # No chained cause: parser messages can quote the document.
        except AttachmentError as exc:
            raise AttachmentError(f"{name}: {exc}") from None
        pages_left -= pages or 0
        kept = (text or "")[:chars_left]
        chars_left -= len(kept)
        clipped = text is None or len(text) > len(kept)
        extracted.append(
            ExtractedAttachment(name, kind, kept + TRUNCATED if clipped else kept, pages)
        )
    return extracted


def format_attachments(items: Sequence[ExtractedAttachment]) -> str:
    return "\n\n".join(f"--- attachment: {item.filename} ---\n{item.text}" for item in items)
