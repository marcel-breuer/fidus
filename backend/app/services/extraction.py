"""Bounded text extraction and deterministic overlap-aware chunking."""

from io import BytesIO
from zipfile import ZipFile

MAX_EXTRACTION_BYTES = 25 * 1024 * 1024
MAX_PDF_PAGES = 500


class ExtractionError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def extract_text(mime_or_extension: str, content: bytes) -> str:
    if len(content) > MAX_EXTRACTION_BYTES:
        raise ExtractionError("CORRUPT_FILE")
    kind = mime_or_extension.lower().split(";")[0]
    if kind.endswith((".txt", ".md", ".markdown")) or kind in {"text/plain", "text/markdown"}:
        try:
            result = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ExtractionError("CORRUPT_FILE") from exc
    elif kind.endswith(".pdf") or kind == "application/pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(content), strict=True)
            if reader.is_encrypted:
                raise ExtractionError("ENCRYPTED_PDF")
            if len(reader.pages) > MAX_PDF_PAGES:
                raise ExtractionError("TOO_MANY_PAGES")
            result = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError("CORRUPT_FILE") from exc
    elif kind.endswith(".docx") or kind == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        try:
            with ZipFile(BytesIO(content)) as archive:
                entries = archive.infolist()
                if len(entries) > 1000 or sum(entry.file_size for entry in entries) > 50 * 1024 * 1024:
                    raise ExtractionError("CORRUPT_FILE")
                if "word/document.xml" not in archive.namelist():
                    raise ExtractionError("CORRUPT_FILE")
            from docx import Document

            document = Document(BytesIO(content))
            parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text]
            parts.extend(
                cell.text
                for table in document.tables
                for row in table.rows
                for cell in row.cells
                if cell.text
            )
            result = "\n\n".join(parts)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError("CORRUPT_FILE") from exc
    else:
        raise ExtractionError("CORRUPT_FILE")
    result = result.strip()
    if not result:
        raise ExtractionError("EMPTY_TEXT")
    return result


def chunk_text(text: str, size: int = 1200, overlap: int = 200) -> list[str]:
    if size < 1 or overlap < 0 or overlap >= size:
        raise ValueError("size must be positive and overlap must be smaller than size")
    if not text.strip():
        return []
    # Retain all source characters: prefer a paragraph/sentence edge near the limit,
    # falling back to a hard split for long tokens or unpunctuated text.
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            floor = start + max(1, size // 2)
            candidates = [text.rfind("\n\n", floor, end), text.rfind("\n", floor, end)]
            sentence = max(text.rfind(mark, floor, end) for mark in (". ", "! ", "? "))
            if sentence >= 0:
                candidates.append(sentence + 1)
            boundary = max(candidates)
            if boundary > start:
                end = boundary
        piece = text[start:end]
        if piece.strip():
            chunks.append(piece)
        if end >= len(text):
            break
        next_start = max(start + 1, end - overlap)
        # Make overlap start at a word boundary when possible; the adjacent chunks
        # still retain an unbroken source span even when a token is longer than size.
        whitespace = text.find(" ", next_start, end)
        newline = text.find("\n", next_start, end)
        boundaries = [position + 1 for position in (whitespace, newline) if position >= 0]
        start = min(boundaries) if boundaries else next_start
    return chunks
