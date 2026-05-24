"""Upload validation helpers for PDF files."""

from pathlib import Path

import fitz
from fastapi import UploadFile, status

from app.core.config import get_settings
from app.core.errors import AppError

PDF_MIME_TYPE = "application/pdf"
PDF_SIGNATURE = b"%PDF"


def validate_pdf_metadata(file: UploadFile) -> None:
    """Validate filename extension and MIME type."""

    filename = file.filename or ""
    if Path(filename).suffix.lower() != ".pdf":
        raise AppError(
            code="INVALID_FILE_TYPE",
            message="Le fichier doit etre un PDF.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if file.content_type != PDF_MIME_TYPE:
        raise AppError(
            code="INVALID_FILE_TYPE",
            message="Le fichier doit etre un PDF.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )


async def read_and_validate_pdf_content(file: UploadFile) -> bytes:
    """Read uploaded content while enforcing size and PDF signature limits."""

    settings = get_settings()
    max_size_bytes = settings.max_file_size_mb * 1024 * 1024
    content = bytearray()

    while chunk := await file.read(1024 * 1024):
        content.extend(chunk)
        if len(content) > max_size_bytes:
            raise AppError(
                code="FILE_TOO_LARGE",
                message=(
                    "Le fichier depasse la taille maximale de "
                    f"{settings.max_file_size_mb} Mo."
                ),
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            )

    if not content.startswith(PDF_SIGNATURE):
        raise AppError(
            code="INVALID_FILE_TYPE",
            message="Le fichier doit etre un PDF.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return bytes(content)


def validate_pdf_mvp_limits(content: bytes) -> None:
    """Validate page count and selectable text before storing the PDF."""

    settings = get_settings()
    try:
        with fitz.open(stream=content, filetype="pdf") as pdf_document:
            max_page_count = (
                settings.max_batch_experimental_pages
                if settings.enable_batch_mode
                else settings.max_page_count
            )
            if pdf_document.page_count > max_page_count:
                raise AppError(
                    code="PDF_TOO_MANY_PAGES",
                    message=(
                        "Le PDF depasse la limite MVP de "
                        f"{max_page_count} pages."
                    ),
                    status_code=status.HTTP_400_BAD_REQUEST,
                    details={
                        "page_count": pdf_document.page_count,
                        "max_page_count": max_page_count,
                    },
                )

            has_selectable_text = any(
                page.get_text("text").strip() for page in pdf_document
            )
            if not has_selectable_text:
                raise AppError(
                    code="PDF_NO_SELECTABLE_TEXT",
                    message="Le PDF doit contenir du texte selectionnable.",
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    details=None,
                )
    except AppError:
        raise
    except Exception as exc:
        raise AppError(
            code="INVALID_FILE_TYPE",
            message="Le fichier PDF est invalide ou illisible.",
            status_code=status.HTTP_400_BAD_REQUEST,
        ) from exc
