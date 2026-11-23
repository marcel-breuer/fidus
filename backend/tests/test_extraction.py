from io import BytesIO

import pytest

from app.services.extraction import MAX_EXTRACTION_BYTES, ExtractionError, chunk_text, extract_text


def test_extract_text_and_markdown_as_is() -> None:
	assert extract_text("text/plain", b"hello\nworld") == "hello\nworld"
	assert extract_text("notes.md", b"# Title\n\n**text**") == "# Title\n\n**text**"


def test_empty_and_invalid_utf8_have_stable_errors() -> None:
	with pytest.raises(ExtractionError, match="EMPTY_TEXT"):
		extract_text(".txt", b" \n")
	with pytest.raises(ExtractionError, match="CORRUPT_FILE"):
		extract_text(".txt", b"\xff")
	with pytest.raises(ExtractionError, match="CORRUPT_FILE"):
		extract_text(".txt", b"x" * (MAX_EXTRACTION_BYTES + 1))


def test_chunking_is_bounded_ordered_and_overlapping() -> None:
	text = "First sentence. " + ("alpha beta gamma. " * 100) + "last token"
	chunks = chunk_text(text, size=80, overlap=15)
	assert chunks and all(chunk.strip() and len(chunk) <= 80 for chunk in chunks)
	covered_until = 0
	for chunk in chunks:
		found = text.find(chunk, max(0, covered_until - 15))
		assert found >= 0
		assert found <= covered_until
		covered_until = max(covered_until, found + len(chunk))
	assert covered_until == len(text)
	assert any(
		any(left.endswith(right[:length]) for length in range(1, min(15, len(right)) + 1))
		for left, right in zip(chunks, chunks[1:], strict=False)
	)


def test_chunking_handles_long_tokens_and_empty_text() -> None:
	assert chunk_text("", 20, 2) == []
	chunks = chunk_text("x" * 101, size=20, overlap=3)
	assert all(0 < len(chunk) <= 20 for chunk in chunks)
	assert sum(map(len, chunks)) >= 101
	with pytest.raises(ValueError):
		chunk_text("text", size=10, overlap=10)


def test_pdf_and_docx_extractors_when_libraries_are_installed() -> None:
	pypdf = pytest.importorskip("pypdf")
	stream = b"BT /F1 12 Tf 72 720 Td (Hello PDF) Tj ET"
	objects = [
		b"<< /Type /Catalog /Pages 2 0 R >>",
		b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
		b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
		b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
		b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
		b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
	]
	pdf = bytearray(b"%PDF-1.4\n")
	offsets = [0]
	for number, body in enumerate(objects, start=1):
		offsets.append(len(pdf))
		pdf.extend(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
	xref_offset = len(pdf)
	pdf.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
	for offset in offsets[1:]:
		pdf.extend(f"{offset:010d} 00000 n \n".encode())
	pdf.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode())
	assert "Hello PDF" in extract_text(".pdf", bytes(pdf))
	encrypted_writer = pypdf.PdfWriter()
	encrypted_writer.add_blank_page(width=10, height=10)
	encrypted_writer.encrypt("secret")
	encrypted_buffer = BytesIO()
	encrypted_writer.write(encrypted_buffer)
	with pytest.raises(ExtractionError, match="ENCRYPTED_PDF"):
		extract_text(".pdf", encrypted_buffer.getvalue())
	large_writer = pypdf.PdfWriter()
	for _ in range(501):
		large_writer.add_blank_page(width=10, height=10)
	large_buffer = BytesIO()
	large_writer.write(large_buffer)
	with pytest.raises(ExtractionError, match="TOO_MANY_PAGES"):
		extract_text(".pdf", large_buffer.getvalue())

	with pytest.raises(ExtractionError, match="CORRUPT_FILE"):
		extract_text(".pdf", b"bad pdf")
	docx = pytest.importorskip("docx")
	document = docx.Document()
	document.add_paragraph("Hello DOCX")
	table = document.add_table(rows=1, cols=1)
	table.cell(0, 0).text = "Table cell"
	buffer = BytesIO()
	document.save(buffer)
	text = extract_text(".docx", buffer.getvalue())
	assert "Hello DOCX" in text and "Table cell" in text
	with pytest.raises(ExtractionError, match="CORRUPT_FILE"):
		extract_text(".docx", b"bad docx")
