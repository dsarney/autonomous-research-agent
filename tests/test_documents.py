from io import BytesIO

import pytest
from docx import Document
from pypdf import PdfWriter
from reportlab.pdfgen import canvas

from app.agent.documents import (
    DocumentError,
    IncomingFile,
    TRUNCATION_MARKER,
    documents_to_sources,
    extract_documents,
    format_document_context,
    sanitize_filename,
)


def _extract(
    files: list[IncomingFile],
    *,
    max_files: int = 5,
    max_upload_mb: int = 10,
    max_chars_per_file: int = 20_000,
    max_total_chars: int = 60_000,
):
    return extract_documents(
        files,
        max_files=max_files,
        max_upload_mb=max_upload_mb,
        max_chars_per_file=max_chars_per_file,
        max_total_chars=max_total_chars,
    )


def _pdf_with_text(text: str) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(72, 720, text)
    pdf.save()
    return buffer.getvalue()


def _empty_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _docx_with_text(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_extracts_txt_md_pdf_and_docx() -> None:
    documents = _extract(
        [
            IncomingFile("notes.txt", "text/plain", b"Plain article claims."),
            IncomingFile("notes.md", "text/markdown", b"# Markdown heading\nBody."),
            IncomingFile("paper.pdf", "application/pdf", _pdf_with_text("PDF claim")),
            IncomingFile(
                "article.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                _docx_with_text("Word article body"),
            ),
        ]
    )
    assert [item.id for item in documents] == ["D1", "D2", "D3", "D4"]
    assert "Plain article claims." in documents[0].excerpt
    assert "Markdown heading" in documents[1].excerpt
    assert "PDF claim" in documents[2].excerpt
    assert "Word article body" in documents[3].excerpt


def test_rejects_unsupported_type_and_empty_pdf() -> None:
    with pytest.raises(DocumentError, match="Unsupported file type"):
        _extract([IncomingFile("photo.png", "image/png", b"not-a-document")])
    with pytest.raises(DocumentError, match="no extractable text"):
        _extract([IncomingFile("scan.pdf", "application/pdf", _empty_pdf())])
    with pytest.raises(DocumentError, match="could not be read"):
        _extract([IncomingFile("broken.pdf", "application/pdf", b"not-a-pdf")])


def test_rejects_too_many_and_oversize_files() -> None:
    with pytest.raises(DocumentError, match="at most 1"):
        _extract(
            [
                IncomingFile("a.txt", "text/plain", b"one"),
                IncomingFile("b.txt", "text/plain", b"two"),
            ],
            max_files=1,
        )
    with pytest.raises(DocumentError, match="larger than 1 MB"):
        _extract(
            [IncomingFile("big.txt", "text/plain", b"x" * (1024 * 1024 + 1))],
            max_upload_mb=1,
        )


def test_truncates_excerpts_and_seeds_upload_sources() -> None:
    documents = _extract(
        [IncomingFile("long.txt", "text/plain", b"abcdefghij" * 20)],
        max_chars_per_file=25,
        max_total_chars=25,
    )
    assert TRUNCATION_MARKER in documents[0].excerpt
    sources = documents_to_sources(documents)
    assert sources[0].id == "D1"
    assert sources[0].kind == "upload"
    assert sources[0].url == "upload://long.txt"
    context = format_document_context(documents)
    assert "### D1 long.txt" in context


def test_sanitize_filename_strips_paths() -> None:
    assert sanitize_filename("../../secret.pdf") == "secret.pdf"
    assert sanitize_filename("") == "document"
