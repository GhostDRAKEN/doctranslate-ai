"""Upload validation helpers for PDF files."""

from pathlib import Path

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
