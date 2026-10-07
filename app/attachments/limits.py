from dataclasses import dataclass


@dataclass(frozen=True)
class AttachmentLimits:
    max_files: int = 5
    max_bytes: int = 10 * 1024 * 1024
    max_pages: int = 200
    max_chars: int = 50_000
    max_docx_uncompressed: int = 50 * 1024 * 1024
