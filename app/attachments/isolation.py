"""Run `extract_all` in a short-lived child process with a hard timeout and a memory cap, so a
hostile upload can at worst take down its own process. Blocking: call it via `asyncio.to_thread`."""

import contextlib
import logging
import math
import multiprocessing
import os
import resource
import sys
import threading
import time
from collections.abc import Callable, Sequence
from multiprocessing import spawn
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
CONTEXT.set_forkserver_preload(["__main__", __name__])

# Each child re-runs the parent's main script unless the server has already loaded it (uvicorn's
# console script: about 25 ms per child). The "__main__" preload above should do that, but
# CPython 3.12's forkserver reads "main_path" where spawn sends "init_main_from_path", so it never
# fires. The parent therefore names its script in the environment the server inherits, and the
# server, importing this module as a preload, loads it once; children then skip it.
PARENT_MAIN_ENV = "ATTACHMENTS_PARENT_MAIN"
if sys.orig_argv[-1].startswith("from multiprocessing.forkserver import main"):
    if parent_main := os.environ.get(PARENT_MAIN_ENV):
        spawn.import_main_path(parent_main)
elif main_script := getattr(sys.modules["__main__"], "__file__", None):
    os.environ[PARENT_MAIN_ENV] = os.path.abspath(main_script)

# At most `max_concurrent` children at once, process-wide. Callers wait in worker threads
# (asyncio.to_thread), so a thread semaphore fits. Sized from the limits on first use: the
# settings do not change while the service runs.
slot_pool: threading.BoundedSemaphore | None = None
slot_pool_lock = threading.Lock()


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


def cap(kind: int, limit: int) -> None:
    """Best effort: lower the soft limit and keep the hard one. Where the OS refuses, skip it
    (macOS rejects any RLIMIT_AS below the address space a process has already reserved)."""
    _, hard = resource.getrlimit(kind)
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(kind, (limit, hard))


def child(
    conn: Connection, extract: Extractor, files: Sequence[Attachment], limits: AttachmentLimits
) -> None:
    cap(resource.RLIMIT_AS, limits.max_memory_bytes)
    # CPU seconds, one more than the wall-clock timeout: the parent's kill comes first, and this
    # stops a child that no parent is left to kill.
    cap(resource.RLIMIT_CPU, math.ceil(limits.timeout_seconds) + 1)
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
    space capped at `limits.max_memory_bytes` where the OS enforces it. Waits up to the same
    timeout for one of `limits.max_concurrent` slots, else raises a "busy" AttachmentError."""
    return run_isolated(extract_all, files, limits)


def slots(size: int) -> threading.BoundedSemaphore:
    global slot_pool
    with slot_pool_lock:
        if slot_pool is None:
            slot_pool = threading.BoundedSemaphore(size)
        return slot_pool


def run_isolated(
    extract: Extractor, files: Sequence[Attachment], limits: AttachmentLimits
) -> list[ExtractedAttachment]:
    slot = slots(limits.max_concurrent)
    if not slot.acquire(timeout=limits.timeout_seconds):
        raise AttachmentError(
            "the server is busy reading other attachments, try again", reason="busy"
        )
    try:
        return run_child(extract, files, limits)
    finally:
        slot.release()


def run_child(
    extract: Extractor, files: Sequence[Attachment], limits: AttachmentLimits
) -> list[ExtractedAttachment]:
    receive, send = CONTEXT.Pipe(duplex=False)
    with receive, send:
        worker = CONTEXT.Process(
            target=child, args=(send, extract, list(files), limits), daemon=True
        )
        worker.start()
        send.close()  # the child now holds the only write end: its death reads as EOF
        try:
            return await_result(receive, worker, limits)
        finally:
            if worker.is_alive():
                worker.kill()
            worker.join()
            worker.close()


def await_result(
    receive: Connection, worker: multiprocessing.process.BaseProcess, limits: AttachmentLimits
) -> list[ExtractedAttachment]:
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
    # EOFError: killed by a signal (the OOM killer included) or exited without a result.
    # OSError: it died in the middle of a message.
    except (EOFError, OSError):
        worker.join(1)
        logger.warning("attachment worker died with exit code %s", worker.exitcode)
        raise AttachmentError(f"{current}: could not be read") from None
