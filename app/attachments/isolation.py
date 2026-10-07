"""Run `extract_all` in a short-lived child process with a hard timeout and a memory cap, so a
hostile upload can at worst take down its own process. Blocking: call it via `asyncio.to_thread`."""

import contextlib
import logging
import multiprocessing
import resource
import time
from collections.abc import Callable, Sequence
from multiprocessing.connection import Connection
from typing import Protocol

from app.attachments.extractor import Attachment, AttachmentError, ExtractedAttachment, extract_all
from app.attachments.limits import AttachmentLimits

logger = logging.getLogger(__name__)
parse_logger = logging.getLogger("app.attachments.extractor")

# forkserver: every child forks from one single-threaded server that has already imported the
# parsers (about 10 ms per extraction after a one-off start of about 100 ms; spawn pays 110 to
# 160 ms each time). Never fork the threaded web server itself. The preload list is process-wide.
CONTEXT = multiprocessing.get_context("forkserver")
CONTEXT.set_forkserver_preload([__name__])


class Extractor(Protocol):
    def __call__(
        self,
        files: Sequence[Attachment],
        limits: AttachmentLimits,
        *,
        on_file: Callable[[str], None],
    ) -> list[ExtractedAttachment]: ...


class Forward(logging.Handler):
    """Sends the extractor's records, which name exception types only, to the parent."""

    def __init__(self, conn: Connection) -> None:
        super().__init__(logging.WARNING)
        self.conn = conn

    def emit(self, record: logging.LogRecord) -> None:
        self.conn.send(("log", record.getMessage()))


def cap_memory(limit: int) -> None:
    """Best effort. Linux enforces RLIMIT_AS; macOS rejects any limit below the address space a
    process has already reserved (ValueError), so there the cap is skipped."""
    _, hard = resource.getrlimit(resource.RLIMIT_AS)
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_AS, (limit, hard))


def child(
    conn: Connection, extract: Extractor, files: Sequence[Attachment], limits: AttachmentLimits
) -> None:
    cap_memory(limits.max_memory_bytes)
    # Only the extractor's records leave the child: library messages can quote the document.
    logging.getLogger().addHandler(logging.NullHandler())
    parse_logger.addHandler(Forward(conn))
    current = "attachments"

    def started(name: str) -> None:
        nonlocal current
        current = name
        conn.send(("file", name))

    try:
        conn.send(("done", extract(files, limits, on_file=started)))
    except AttachmentError as exc:
        conn.send(("error", exc))
    except MemoryError:
        conn.send(("error", AttachmentError(f"{current}: too large to read")))
    except Exception as exc:  # noqa: BLE001  (send the type only: a traceback could quote the file)
        conn.send(("crash", type(exc).__name__))


def extract_all_isolated(
    files: Sequence[Attachment], limits: AttachmentLimits
) -> list[ExtractedAttachment]:
    """`extract_all` in a child process, killed after `limits.timeout_seconds`, with its address
    space capped at `limits.max_memory_bytes` where the OS enforces it."""
    return run_isolated(extract_all, files, limits)


def run_isolated(
    extract: Extractor, files: Sequence[Attachment], limits: AttachmentLimits
) -> list[ExtractedAttachment]:
    receive, send = CONTEXT.Pipe(duplex=False)
    worker = CONTEXT.Process(target=child, args=(send, extract, list(files), limits), daemon=True)
    worker.start()
    send.close()  # the child now holds the only write end: its death reads as EOF
    current = "attachments"
    deadline = time.monotonic() + limits.timeout_seconds
    try:
        while receive.poll(max(0.0, deadline - time.monotonic())):
            kind, payload = receive.recv()
            if kind == "file":
                current = payload
            elif kind == "log":
                parse_logger.warning("%s", payload)
            elif kind == "done":
                extracted: list[ExtractedAttachment] = payload
                return extracted
            elif isinstance(payload, AttachmentError):
                raise payload
            else:
                logger.warning("attachment worker failed: %s", payload)
                raise AttachmentError(f"{current}: could not be read")
        logger.warning("attachment worker killed after %s s", limits.timeout_seconds)
        raise AttachmentError(f"{current}: took too long to read")
    except EOFError:
        # Killed by a signal (the OOM killer included) or exited without a result.
        worker.join(1)
        logger.warning("attachment worker died with exit code %s", worker.exitcode)
        raise AttachmentError(f"{current}: could not be read") from None
    finally:
        if worker.is_alive():
            worker.kill()
        worker.join()
        worker.close()
        receive.close()
