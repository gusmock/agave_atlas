from __future__ import annotations

import mimetypes
from pathlib import Path


def guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "application/octet-stream"


def extract_text(path: Path, max_chars: int = 60_000) -> str:
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
            return text[:max_chars]
        if suffix in {".docx", ".doc"}:
            from docx import Document

            document = Document(str(path))
            text = "\n".join(paragraph.text for paragraph in document.paragraphs)
            return text[:max_chars]
        if suffix in {".txt", ".md", ".csv"}:
            return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except Exception:
        return ""
    return ""
