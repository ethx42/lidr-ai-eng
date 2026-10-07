import io
import logging
import os
import pickle
import signal
import struct
import subprocess
import sys
import time
import tracemalloc
import warnings
import zipfile
import zlib
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pypdf
import pytest
from pydantic import ValidationError
from pypdf import PdfWriter

from app.attachments import extractor, isolation
from app.attachments.extractor import (
    Attachment,
    AttachmentError,
    AttachmentLimits,
    ExtractedAttachment,
    detect_kind,
    extract_all,
    format_attachments,
)
from app.attachments.isolation import extract_all_isolated, run_isolated
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


def settings(**limits: float) -> Settings:
    return Settings(_env_file=None, llm_provider="replay", llm_fallbacks="none", **limits)


def test_settings_carry_the_attachment_limits() -> None:
    loaded = settings(
        attachment_max_files=2,
        attachment_max_chars=1_000,
        attachment_timeout_seconds=2.5,
        attachment_max_memory_bytes=256 * 1024 * 1024,
        attachment_max_concurrent=4,
    )
    assert loaded.attachment_limits == AttachmentLimits(
        max_files=2,
        max_chars=1_000,
        timeout_seconds=2.5,
        max_memory_bytes=256 * 1024 * 1024,
        max_concurrent=4,
    )


@pytest.mark.parametrize(
    "limit",
    [
        {"attachment_timeout_seconds": 0},
        {"attachment_timeout_seconds": 121},
        {"attachment_max_memory_bytes": 64 * 1024 * 1024},
        {"attachment_max_memory_bytes": 9 * 1024**3},
        {"attachment_max_concurrent": 0},
        {"attachment_max_concurrent": 17},
    ],
    ids=[
        "timeout-zero",
        "timeout-too-long",
        "memory-too-small",
        "memory-too-large",
        "no-children",
        "too-many-children",
    ],
)
def test_child_process_limits_are_bounded(limit: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        settings(**limit)


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


# Fix round 2: extraction in a killable child process. The targets below run in the child, which
# imports this module to unpickle them.


def die_by_signal(
    files: Sequence[Attachment], limits: AttachmentLimits, *, on_file: Callable[[str], None]
) -> list[ExtractedAttachment]:
    on_file("victim.pdf")
    os.kill(os.getpid(), signal.SIGKILL)  # as the kernel's OOM killer would
    return []


def exit_without_a_result(
    files: Sequence[Attachment], limits: AttachmentLimits, *, on_file: Callable[[str], None]
) -> list[ExtractedAttachment]:
    os._exit(3)


def run_out_of_memory(
    files: Sequence[Attachment], limits: AttachmentLimits, *, on_file: Callable[[str], None]
) -> list[ExtractedAttachment]:
    on_file("huge.docx")
    raise MemoryError


def allocate_past_the_cap(
    files: Sequence[Attachment], limits: AttachmentLimits, *, on_file: Callable[[str], None]
) -> list[ExtractedAttachment]:
    on_file("huge.docx")
    bytearray(2 * limits.max_memory_bytes)
    return []


def fail_quoting_the_document(
    files: Sequence[Attachment], limits: AttachmentLimits, *, on_file: Callable[[str], None]
) -> list[ExtractedAttachment]:
    on_file("bad.docx")
    raise KeyError("SECRETMARKER")


def test_isolated_extraction_matches_in_process() -> None:
    files = [load("spec.pdf"), load("spec.docx"), load("notes.txt")]
    assert extract_all_isolated(files, AttachmentLimits()) == extract_all(files, AttachmentLimits())


def test_isolated_rejections_cross_the_process_boundary() -> None:
    with pytest.raises(AttachmentError, match=r"^encrypted\.pdf: password-protected PDFs"):
        extract_all_isolated([load("notes.txt"), load("encrypted.pdf")], AttachmentLimits())


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda: pdf_pages(NOOP * 20_000, pages=50), id="pages-sharing-a-stream"),
        # One page: no check between pages can fire; the fonts are built before any operator.
        pytest.param(lambda: pdf_pages(TEXT, fonts=200, cmap=cmap(5_000)), id="one-page-of-fonts"),
    ],
)
def test_isolated_extraction_is_killed_at_the_timeout(build: Callable[[], bytes]) -> None:
    upload = Attachment("slow.pdf", build())
    started = time.monotonic()
    with pytest.raises(AttachmentError, match=r"^slow\.pdf: took too long to read$"):
        extract_all_isolated([upload], AttachmentLimits(timeout_seconds=0.5))
    assert time.monotonic() - started < 0.5 + 1.0


def test_pdf_pages_stop_at_the_timeout_in_process() -> None:
    with pytest.raises(AttachmentError, match=r"^slow\.pdf: took too long to read$"):
        extract_all(
            [Attachment("slow.pdf", pdf_pages(NOOP * 20_000, pages=50))],
            AttachmentLimits(timeout_seconds=0.05),
        )


@pytest.mark.parametrize(
    ("target", "message"),
    [
        (die_by_signal, r"^victim\.pdf: could not be read$"),
        (exit_without_a_result, r"^attachments: could not be read$"),
    ],
    ids=["killed", "exited"],
)
def test_a_child_that_dies_is_an_attachment_error(
    target: Callable[..., list[ExtractedAttachment]], message: str
) -> None:
    with pytest.raises(AttachmentError, match=message):
        run_isolated(target, [load("notes.txt")], AttachmentLimits())


def test_memory_errors_in_the_child_are_too_large_to_read() -> None:
    with pytest.raises(AttachmentError, match=r"^huge\.docx: too large to read$"):
        run_isolated(run_out_of_memory, [load("notes.txt")], AttachmentLimits())


@pytest.mark.skipif(sys.platform != "linux", reason="only Linux enforces RLIMIT_AS")
def test_the_memory_cap_is_enforced_on_linux() -> None:
    with pytest.raises(AttachmentError, match=r"^huge\.docx: too large to read$"):
        run_isolated(
            allocate_past_the_cap,
            [load("notes.txt")],
            AttachmentLimits(max_memory_bytes=256 * 1024 * 1024),
        )


def test_unexpected_child_failures_log_the_type_only(caplog: pytest.LogCaptureFixture) -> None:
    with (
        caplog.at_level(logging.WARNING),
        pytest.raises(AttachmentError, match=r"^bad\.docx: could not be read$"),
    ):
        run_isolated(fail_quoting_the_document, [load("notes.txt")], AttachmentLimits())
    assert "attachment worker failed: KeyError" in caplog.text
    assert "SECRETMARKER" not in caplog.text


def test_child_parse_failures_reach_the_log_without_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    data = rewrite_docx({"word/document.xml": b"<a><SECRETMARKER></a>"})
    with (
        caplog.at_level(logging.WARNING),
        pytest.raises(AttachmentError, match=r"^bad\.docx: unreadable DOCX$"),
    ):
        extract_all_isolated([Attachment("bad.docx", data)], AttachmentLimits())
    assert "attachment parse failed: XMLSyntaxError" in caplog.text
    assert "SECRETMARKER" not in caplog.text


# Fix round 3: at most `max_concurrent` extraction children at once.


def extract_slowly(
    files: Sequence[Attachment], limits: AttachmentLimits, *, on_file: Callable[[str], None]
) -> list[ExtractedAttachment]:
    time.sleep(0.5)
    return extract_all(files, limits, on_file=on_file)


def hang(
    files: Sequence[Attachment], limits: AttachmentLimits, *, on_file: Callable[[str], None]
) -> list[ExtractedAttachment]:
    on_file("hung.pdf")
    time.sleep(30)
    return []


@pytest.fixture
def one_slot(monkeypatch: pytest.MonkeyPatch) -> AttachmentLimits:
    """The slot semaphore is sized on first use: start this test without one."""
    monkeypatch.setattr(isolation, "slot_pool", None)
    return AttachmentLimits(max_concurrent=1, timeout_seconds=5)


def timed(call: Callable[[], object]) -> tuple[object, float]:
    result = call()
    return result, time.monotonic()


def test_a_second_extraction_waits_for_the_slot(one_slot: AttachmentLimits) -> None:
    files = [load("notes.txt")]
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(timed, lambda: run_isolated(extract_slowly, files, one_slot))
        time.sleep(0.1)  # the first one holds the only slot
        second = pool.submit(timed, lambda: extract_all_isolated(files, one_slot))
        (first_result, first_done), (second_result, second_done) = first.result(), second.result()
    assert first_result == second_result == extract_all(files, one_slot)
    assert second_done > first_done


def test_no_slot_within_the_timeout_is_a_busy_error(one_slot: AttachmentLimits) -> None:
    with ThreadPoolExecutor(1) as pool:
        hung_limits = replace(one_slot, timeout_seconds=1.0)  # holds the slot past 0.3 s
        hung = pool.submit(run_isolated, hang, [load("notes.txt")], hung_limits)
        time.sleep(0.1)
        started = time.monotonic()
        with pytest.raises(
            AttachmentError, match="server is busy reading other attachments"
        ) as err:
            extract_all_isolated([load("notes.txt")], replace(one_slot, timeout_seconds=0.3))
        assert err.value.reason == "busy" and time.monotonic() - started < 1.0
    with pytest.raises(AttachmentError, match=r"^hung\.pdf: took too long to read$") as killed:
        hung.result()
    assert killed.value.reason == "invalid"


def test_errors_keep_their_reason_across_the_process_boundary() -> None:
    with pytest.raises(AttachmentError) as err:
        extract_all_isolated([load("encrypted.pdf")], AttachmentLimits())
    assert err.value.reason == "invalid"
    busy = pickle.loads(pickle.dumps(AttachmentError("x", reason="busy")))  # noqa: S301  (own bytes)
    assert (str(busy), busy.reason) == ("x", "busy")
