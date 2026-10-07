import io
import struct
import tracemalloc
import zipfile

import pytest
from pypdf import PdfWriter

from app.attachments.extractor import (
    Attachment,
    AttachmentError,
    AttachmentLimits,
    detect_kind,
    extract_all,
    format_attachments,
)
from app.config import Settings

FIX = "tests/fixtures/attachments/"


def load(name: str) -> Attachment:
    return Attachment(filename=name, data=open(FIX + name, "rb").read())


def test_pdf_text_extracted_with_pages() -> None:
    [a] = extract_all([load("spec.pdf")], AttachmentLimits())
    assert a.kind == "pdf" and a.pages == 2 and "ATTACHMENT-MARKER" in a.text


def test_docx_paragraphs_and_tables_extracted() -> None:
    [a] = extract_all([load("spec.docx")], AttachmentLimits())
    assert a.kind == "docx" and "ATTACHMENT-MARKER" in a.text


def test_kind_comes_from_bytes_not_extension() -> None:
    fake = Attachment(filename="spec.pdf", data=b"MZ\x90\x00binary")
    with pytest.raises(AttachmentError, match="unsupported"):
        extract_all([fake], AttachmentLimits())


def test_zip_that_is_not_docx_rejected() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", "hi")
    with pytest.raises(AttachmentError, match="unsupported"):
        detect_kind(buf.getvalue())


def test_docx_bomb_rejected() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "word/document.xml", "<w/>" * 3_000_000
        )  # 12 MB uncompressed, enough over the cap
    with pytest.raises(AttachmentError, match="too large"):
        extract_all(
            [Attachment("big.docx", buf.getvalue())],
            AttachmentLimits(max_docx_uncompressed=10_000_000),
        )


def test_encrypted_pdf_rejected_with_clear_message() -> None:
    with pytest.raises(AttachmentError, match="password"):
        extract_all([load("encrypted.pdf")], AttachmentLimits())


def test_limits_on_count_bytes_and_chars() -> None:
    with pytest.raises(AttachmentError, match="at most 1"):
        extract_all([load("notes.txt"), load("notes.txt")], AttachmentLimits(max_files=1))
    with pytest.raises(AttachmentError, match="larger than"):
        extract_all([load("spec.pdf")], AttachmentLimits(max_bytes=10))
    [a] = extract_all([Attachment("n.txt", b"a" * 100)], AttachmentLimits(max_chars=10))
    assert (
        a.text == "a" * 10 + "\n[truncated]"
    )  # truncated (marker outside the budget), never rejected for length


def test_format_uses_brief_separator_and_sanitised_names() -> None:
    [a] = extract_all([Attachment("we<ird>\nname.txt", b"hello")], AttachmentLimits())
    assert format_attachments([a]) == "--- attachment: weirdname.txt ---\nhello"


def test_errors_name_the_sanitised_file() -> None:
    with pytest.raises(AttachmentError, match=r"^setup\.exe: unsupported file type"):
        extract_all([Attachment("setup<\n>.exe", b"MZ\x90\x00")], AttachmentLimits())


@pytest.mark.parametrize(
    "data",
    [b"plain\x00text", b"PK\x03\x04not really a zip", b"\xff\xfe\x00binary"],
    ids=["nul-bytes", "corrupt-zip", "not-utf8"],
)
def test_unknown_bytes_are_unsupported(data: bytes) -> None:
    with pytest.raises(AttachmentError, match="unsupported"):
        detect_kind(data)


def test_kinds_detected_from_bytes() -> None:
    assert [detect_kind(load(n).data) for n in ("spec.pdf", "spec.docx", "notes.txt")] == [
        "pdf",
        "docx",
        "text",
    ]


def test_docx_keeps_document_order_and_table_rows() -> None:
    [a] = extract_all([load("spec.docx")], AttachmentLimits())
    assert a.pages is None
    assert a.text.index("Checkout service") < a.text.index("ATTACHMENT-MARKER")
    assert a.text.endswith("Module | Hours\nPayments | 40")


def test_corrupt_pdf_is_unreadable() -> None:
    with pytest.raises(AttachmentError, match="unreadable PDF"):
        extract_all([Attachment("x.pdf", b"%PDF-1.7\n" + bytes(range(256)))], AttachmentLimits())


def test_pdf_without_text_is_rejected() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    out = io.BytesIO()
    writer.write(out)
    with pytest.raises(AttachmentError, match="no extractable text"):
        extract_all([Attachment("scan.pdf", out.getvalue())], AttachmentLimits())


def test_page_budget_is_shared_across_files() -> None:
    extract_all([load("spec.pdf")], AttachmentLimits(max_pages=2))
    with pytest.raises(AttachmentError, match="too many pages"):
        extract_all([load("spec.pdf"), load("spec.pdf")], AttachmentLimits(max_pages=3))


def test_char_budget_is_shared_across_files() -> None:
    first, second = extract_all(
        [Attachment("a.txt", b"a" * 6), Attachment("b.txt", b"b" * 6)],
        AttachmentLimits(max_chars=10),
    )
    assert (first.text, second.text) == ("a" * 6, "b" * 4 + "\n[truncated]")


def rewrite_docx(replace: dict[str, bytes | None]) -> bytes:
    out = io.BytesIO()
    with (
        zipfile.ZipFile(FIX + "spec.docx") as src,
        zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as dst,
    ):
        for item in src.infolist():
            data = replace.get(item.filename, src.read(item.filename))
            if data is not None:
                dst.writestr(item.filename, data)
    return out.getvalue()


@pytest.mark.parametrize(
    "replace",
    [
        {"word/document.xml": b"<w:document"},
        {"word/document.xml": b'<?xml version="1.0"?><other/>'},
        {"[Content_Types].xml": None},
    ],
    ids=["malformed-xml", "wrong-root", "no-content-types"],
)
def test_malformed_docx_is_unreadable(replace: dict[str, bytes | None]) -> None:
    with pytest.raises(AttachmentError, match="unreadable DOCX"):
        extract_all([Attachment("bad.docx", rewrite_docx(replace))], AttachmentLimits())


def lying_docx(inflated_mb: int) -> bytes:
    """spec.docx whose word/document.xml inflates to `inflated_mb` MB but declares 1 KB."""
    buf = io.BytesIO(rewrite_docx({"word/document.xml": None}))
    with (
        zipfile.ZipFile(buf, "a", compression=zipfile.ZIP_DEFLATED) as archive,
        archive.open("word/document.xml", "w") as member,
    ):
        for _ in range(inflated_mb):
            member.write(bytes(1 << 20))
    with zipfile.ZipFile(buf) as archive:
        header_offset = archive.getinfo("word/document.xml").header_offset
    data = bytearray(buf.getvalue())
    # Uncompressed size: local header +22, central directory entry (the last one) +24.
    for at in (header_offset + 22, data.rfind(b"PK\x01\x02") + 24):
        struct.pack_into("<I", data, at, 1024)
    return bytes(data)


def test_docx_with_lying_sizes_is_inflated_in_bounded_chunks() -> None:
    upload = lying_docx(inflated_mb=100)
    assert len(upload) < AttachmentLimits().max_bytes
    tracemalloc.start()
    try:
        with pytest.raises(AttachmentError, match="unreadable DOCX"):
            extract_all([Attachment("lying.docx", upload)], AttachmentLimits())
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 20 * 1024 * 1024  # zipfile's read() would inflate all 100 MB before cutting


def test_settings_carry_the_attachment_limits() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="replay",
        llm_fallbacks="none",
        attachment_max_files=2,
        attachment_max_chars=1_000,
    )
    assert settings.attachment_limits == AttachmentLimits(max_files=2, max_chars=1_000)
