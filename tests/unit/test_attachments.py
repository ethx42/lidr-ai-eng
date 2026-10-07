import io
import logging
import struct
import subprocess
import sys
import time
import tracemalloc
import warnings
import weakref
import zipfile
import zlib
from collections.abc import Callable
from pathlib import Path

import pypdf
import pytest
from pypdf import PdfWriter

from app.attachments import extractor
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
ROOT = Path(__file__).resolve().parents[2]


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


def rewrite_docx(
    replace: dict[str, bytes | None], compression: int = zipfile.ZIP_DEFLATED
) -> bytes:
    out = io.BytesIO()
    with (
        zipfile.ZipFile(FIX + "spec.docx") as src,
        zipfile.ZipFile(out, "w", compression=compression) as dst,
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


# Fix round 1: every decompressor and every PDF page bounded, parser failures surfaced.

W_NS = b'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
TEXT = b"BT /F0 12 Tf 72 700 Td (Hello world) Tj ET\n"
NOOP = b"0 0 m\n"  # a path operator: parsing work, no text


def raw_pdf(*objects: bytes) -> bytes:
    """A PDF from object bodies numbered from 1 (1 is the catalog), with a valid xref table."""
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def flate(data: bytes) -> bytes:
    packed = zlib.compress(data)
    return b"<< /Filter /FlateDecode /Length %d >>\nstream\n%s\nendstream" % (len(packed), packed)


def pdf_pages(content: bytes, pages: int = 1, fonts: int = 1, cmap: bytes = b"") -> bytes:
    """`pages` pages sharing one content stream, each listing `fonts` font names that all point
    at one Helvetica, with an optional ToUnicode CMap."""
    to_unicode = b"/ToUnicode 5 0 R " if cmap else b""
    names = b" ".join(b"/F%d 4 0 R" % i for i in range(fonts))
    page = (
        b"<< /Type /Page /Parent 2 0 R /Contents 3 0 R /Resources << /Font << %s >> >> >>" % names
    )
    kids = b" ".join(b"%d 0 R" % (6 + i) for i in range(pages))
    return raw_pdf(
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [%s] /Count %d /MediaBox [0 0 612 792] >>" % (kids, pages),
        flate(content),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica %s>>" % to_unicode,
        flate(cmap),
        *[page] * pages,
    )


def cmap(entries: int) -> bytes:
    pairs = b"".join(b"<%04X> <%04X>\n" % (i, i) for i in range(100))
    block = b"100 beginbfchar\n%sendbfchar\n" % pairs
    return b"begincmap\n" + block * (entries // 100) + b"endcmap\n"


def count_page_extractions(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    original = pypdf.PageObject.extract_text

    def spy(self: pypdf.PageObject, *args: object, **kwargs: object) -> str:
        calls.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(pypdf.PageObject, "extract_text", spy)
    return calls


@pytest.mark.parametrize("method", [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA], ids=["bzip2", "lzma"])
def test_docx_members_must_be_stored_or_deflated(method: int) -> None:
    with pytest.raises(AttachmentError, match="unsupported DOCX compression"):
        extract_all([Attachment("x.docx", rewrite_docx({}, method))], AttachmentLimits())


def broken_central_directory(case: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("word/document.xml", "<w/>")
        archive.writestr("caf\u00e9.xml", "x")  # non-ASCII, so stored with the UTF-8 flag
    data = bytearray(buf.getvalue())
    if case == "invalid-utf8-name":
        data[data.rfind("\u00e9".encode())] = 0xFF
    else:  # "version needed to extract" 9.5 in the last central directory entry
        struct.pack_into("<H", data, data.rfind(b"PK\x01\x02") + 6, 95)
    return bytes(data)


@pytest.mark.parametrize("case", ["invalid-utf8-name", "unknown-zip-version"])
def test_zip_that_zipfile_cannot_open_is_unsupported(case: str) -> None:
    data = broken_central_directory(case)
    with pytest.raises(AttachmentError, match="unsupported"):
        detect_kind(data)
    with pytest.raises(AttachmentError, match=r"^bad\.docx: unsupported file type"):
        extract_all([Attachment("bad.docx", data)], AttachmentLimits())


def test_pdf_stops_at_the_char_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = count_page_extractions(monkeypatch)
    [a] = extract_all(
        [Attachment("long.pdf", pdf_pages(TEXT * 50, pages=20))], AttachmentLimits(max_chars=100)
    )
    assert (a.pages, len(a.text), len(calls)) == (20, 100 + len("\n[truncated]"), 1)


def test_files_after_the_char_budget_are_listed_not_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = count_page_extractions(monkeypatch)
    _, skipped = extract_all(
        [Attachment("a.txt", b"a" * 20), load("spec.pdf")], AttachmentLimits(max_chars=10)
    )
    assert (skipped.kind, skipped.text, skipped.pages, calls) == ("pdf", "\n[truncated]", None, [])


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda: pdf_pages(NOOP * 20_000, pages=10), id="pages-sharing-a-stream"),
        # One page: a per-page check never fires; the fonts are built before the first operator.
        pytest.param(lambda: pdf_pages(TEXT, fonts=40, cmap=cmap(5_000)), id="one-page-of-fonts"),
    ],
)
def test_pdf_parsing_has_a_deadline(
    monkeypatch: pytest.MonkeyPatch, build: Callable[[], bytes]
) -> None:
    monkeypatch.setattr(extractor, "PARSE_SECONDS", 0.05)
    with pytest.raises(AttachmentError, match=r"^slow\.pdf: took too long to read$"):
        extract_all([Attachment("slow.pdf", build())], AttachmentLimits())


def test_docx_parsing_has_a_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extractor, "PARSE_SECONDS", 0.05)
    body = b"<w:document %s><w:body>%s</w:body></w:document>" % (W_NS, b"<w:p/>" * 200_000)
    with pytest.raises(AttachmentError, match="took too long to read"):
        extract_all(
            [Attachment("long.docx", rewrite_docx({"word/document.xml": body}))],
            AttachmentLimits(),
        )


def test_pdf_stream_inflating_past_the_cap_is_unreadable() -> None:
    content = NOOP * (5 * 1024 * 1024 // len(NOOP))  # 5 MB decoded, about 5 KB on the wire
    with pytest.raises(AttachmentError, match="unreadable PDF"):
        extract_all([Attachment("bomb.pdf", pdf_pages(content))], AttachmentLimits())


def test_parse_failures_log_the_exception_type_only(caplog: pytest.LogCaptureFixture) -> None:
    data = rewrite_docx({"word/document.xml": b"<a><SECRETMARKER></a>"})
    with (
        caplog.at_level(logging.WARNING, logger=extractor.__name__),
        pytest.raises(AttachmentError) as err,
    ):
        extract_all([Attachment("bad.docx", data)], AttachmentLimits())
    records = [r for r in caplog.records if r.name == extractor.__name__]
    assert [r.getMessage() for r in records] == ["attachment parse failed: XMLSyntaxError"]
    assert records[0].exc_info is None and "SECRETMARKER" not in caplog.text
    # No chained parser exception either: its message quotes the document.
    assert err.value.__cause__ is None and err.value.__suppress_context__


@pytest.mark.parametrize(
    ("name", "target"), [("spec.pdf", (pypdf, "PdfReader")), ("spec.docx", (extractor, "Document"))]
)
def test_memory_errors_are_not_turned_into_422s(
    monkeypatch: pytest.MonkeyPatch, name: str, target: tuple[object, str]
) -> None:
    def exhausted(*args: object) -> None:
        raise MemoryError

    monkeypatch.setattr(*target, exhausted)
    with pytest.raises(MemoryError):
        extract_all([load(name)], AttachmentLimits())


def test_config_does_not_import_the_parsers() -> None:
    probe = "import sys, app.config; print(sorted({'pypdf', 'docx', 'lxml'} & set(sys.modules)))"
    result = subprocess.run(  # noqa: S603  (fixed argv: this interpreter and a literal probe)
        [sys.executable, "-c", probe], cwd=ROOT, capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"


def test_docx_with_duplicate_entries_is_rejected_without_warnings() -> None:
    buf = io.BytesIO(rewrite_docx({}))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # zipfile warns about the duplicate this test builds
        with zipfile.ZipFile(buf, "a") as archive:
            archive.writestr("word/document.xml", "<w/>")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(AttachmentError, match="duplicate"):
            extract_all([Attachment("dup.docx", buf.getvalue())], AttachmentLimits())
    assert caught == []


EMPTY_DOCX = rewrite_docx({"word/document.xml": b"<w:document %s><w:body/></w:document>" % W_NS})


@pytest.mark.parametrize(
    "attachment",
    [
        Attachment("empty.txt", b""),
        Attachment("blank.txt", b" \n\t\r\n "),
        Attachment("blank.docx", EMPTY_DOCX),
    ],
    ids=["empty-txt", "whitespace-txt", "empty-docx"],
)
def test_files_without_text_are_rejected(attachment: Attachment) -> None:
    with pytest.raises(AttachmentError, match=r": no extractable text$"):
        extract_all([attachment], AttachmentLimits())


def test_docx_with_too_many_xml_elements_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # lxml holds about 130 bytes per element: a 78 KB upload of 5M empty paragraphs took +771 MB.
    monkeypatch.setattr(extractor, "DOCX_MAX_TAGS", 1_000)
    body = b"<w:document %s><w:body>%s</w:body></w:document>" % (W_NS, b"<w:p/>" * 2_000)
    with pytest.raises(AttachmentError, match="too many XML elements"):
        extract_all(
            [Attachment("many.docx", rewrite_docx({"word/document.xml": body}))],
            AttachmentLimits(),
        )


class Item:
    pass


def finalizer_bait(case: str) -> tuple[list[object], weakref.WeakSet[Item]]:
    """An object whose release runs code where a raised exception is only printed and the tracer
    is switched off: a weakref callback in the stdlib, or an abandoned parser generator's close."""
    alive: weakref.WeakSet[Item] = weakref.WeakSet()
    if case == "weakref-callback":
        item = Item()
        alive.add(item)
        return [item], alive
    namespace: dict[str, object] = {"__name__": "pypdf.fake"}
    exec("def pages():\n    yield 1\n    yield 2\n", namespace)  # noqa: S102  (a fixed literal)
    pages = namespace["pages"]()
    next(pages)
    return [pages], alive


@pytest.mark.parametrize("case", ["weakref-callback", "abandoned-parser-generator"])
def test_deadline_survives_finalizers(case: str) -> None:
    held, _ = finalizer_bait(case)
    spec = load("spec.pdf").data

    def parse() -> int:
        time.sleep(0.02)
        held.clear()  # C call: the finalizer is the first Python code after the deadline
        return len(pypdf.PdfReader(io.BytesIO(spec)).pages)  # must still be stopped

    with pytest.raises(AttachmentError, match="took too long to read"):
        extractor.within(0.01, parse)
