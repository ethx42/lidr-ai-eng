"""Local text extraction for turn attachments (PDF, DOCX, plain text). Sync and CPU-bound:
callers run `extract_all` in a worker thread."""

import io
import logging
import shutil
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import pypdf
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

Kind = Literal["pdf", "docx", "text"]

ZIP_MAGIC = b"PK\x03\x04"
MAX_NAME_CHARS = 120
TRUNCATED = "\n[truncated]"
UNSUPPORTED = "unsupported file type (PDF, DOCX or plain text only)"

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


@dataclass(frozen=True)
class AttachmentLimits:
    max_files: int = 5
    max_bytes: int = 10 * 1024 * 1024
    max_pages: int = 200
    max_chars: int = 50_000
    max_docx_uncompressed: int = 50 * 1024 * 1024


class AttachmentError(ValueError):
    """The message is safe to show to the user."""


def sanitise_name(name: str) -> str:
    clean = "".join(c for c in name if c.isprintable() and c not in "<>").strip()
    return clean[:MAX_NAME_CHARS] or "attachment"


def megabytes(size: int) -> str:
    return f"{size / 1_048_576:.3g} MB"


def is_docx(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return "word/document.xml" in archive.namelist()
    except zipfile.BadZipFile:
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


def pdf_text(data: bytes, pages_left: int, max_pages: int) -> tuple[str, int]:
    try:
        # Text extraction decodes content streams only; pypdf's defaults (75 MB, 100k entries) are
        # sized for whole documents, images included.
        with pypdf.apply_configuration(
            zlib_maximum_output_length=20_000_000, page_tree_maximum_entries=10_000
        ):
            reader = pypdf.PdfReader(io.BytesIO(data))
            # Before any page access: a user-password PDF raises FileNotDecryptedError there.
            if reader.is_encrypted and reader.decrypt("") == pypdf.PasswordType.NOT_DECRYPTED:
                raise AttachmentError("password-protected PDFs are not supported")
            pages = len(reader.pages)
            if pages > pages_left:
                raise AttachmentError(f"too many pages (at most {max_pages} per turn)")
            texts = [page.extract_text().strip() for page in reader.pages]
    except AttachmentError:
        raise
    # Besides PyPdfError and DependencyError, malformed files raise bare KeyError, AttributeError,
    # TypeError, ValueError or NotImplementedError (fuzzed on pypdf 6.19).
    except Exception as exc:
        raise AttachmentError("unreadable PDF") from exc
    text = "\n\n".join(t for t in texts if t)
    if not text:
        raise AttachmentError("no extractable text (scanned PDF?)")
    return text, pages


def block_lines(block: Paragraph | Table) -> list[str]:
    if isinstance(block, Paragraph):
        return [block.text]
    # A horizontally merged cell repeats the same _Cell object in its row.
    return [" | ".join(cell.text for cell in dict.fromkeys(row.cells)) for row in block.rows]


def repacked(data: bytes, max_uncompressed: int) -> io.BytesIO:
    """python-docx has no zip-bomb guard, and zipfile's read() inflates a whole member before
    cutting it at its declared size. Check the declared total, then copy the members out in
    bounded reads (which stop at the declared size) into an uncompressed archive."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(out, "w") as copy:
        members = [info for info in source.infolist() if not info.is_dir()]
        if sum(info.file_size for info in members) > max_uncompressed:
            raise AttachmentError(
                f"DOCX too large uncompressed (limit {megabytes(max_uncompressed)})"
            )
        for info in members:
            with source.open(info) as member, copy.open(info.filename, "w") as target:
                shutil.copyfileobj(member, target)
    out.seek(0)
    return out


def docx_text(data: bytes, max_uncompressed: int) -> str:
    try:
        document = Document(repacked(data, max_uncompressed))
        lines = [line for block in document.iter_inner_content() for line in block_lines(block)]
    except AttachmentError:
        raise
    # Not only BadZipFile, KeyError and ValueError: lxml's XMLSyntaxError (a SyntaxError), a part
    # with an unexpected root (AttributeError), corrupt members (zlib.error, a CRC BadZipFile).
    except Exception as exc:
        raise AttachmentError("unreadable DOCX") from exc
    return "\n".join(line for line in lines if line.strip())


def extract_one(
    kind: Kind, data: bytes, limits: AttachmentLimits, pages_left: int
) -> tuple[str, int | None]:
    if kind == "pdf":
        return pdf_text(data, pages_left, limits.max_pages)
    if kind == "docx":
        return docx_text(data, limits.max_docx_uncompressed), None
    return data.decode("utf-8-sig"), None


def extract_all(files: Sequence[Attachment], limits: AttachmentLimits) -> list[ExtractedAttachment]:
    if len(files) > limits.max_files:
        raise AttachmentError(f"too many attachments (at most {limits.max_files} per turn)")
    chars_left, pages_left = limits.max_chars, limits.max_pages
    extracted: list[ExtractedAttachment] = []
    for file in files:
        name = sanitise_name(file.filename)
        try:
            if len(file.data) > limits.max_bytes:
                raise AttachmentError(f"larger than {megabytes(limits.max_bytes)}")
            kind = detect_kind(file.data)
            text, pages = extract_one(kind, file.data, limits, pages_left)
        except AttachmentError as exc:
            raise AttachmentError(f"{name}: {exc}") from exc.__cause__
        pages_left -= pages or 0
        kept = text[:chars_left]
        chars_left -= len(kept)
        extracted.append(
            ExtractedAttachment(
                name, kind, kept + TRUNCATED if len(text) > len(kept) else text, pages
            )
        )
    return extracted


def format_attachments(items: Sequence[ExtractedAttachment]) -> str:
    return "\n\n".join(f"--- attachment: {item.filename} ---\n{item.text}" for item in items)
