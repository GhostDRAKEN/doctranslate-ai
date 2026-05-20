"""Document-related API routes."""

import logging

from fastapi import APIRouter, File, UploadFile, status

from app.schemas.document import DocumentUploadResponse
from app.services.storage_service import save_source_pdf
from app.services.upload_validation import (
    read_and_validate_pdf_content,
    validate_pdf_metadata,
)
from app.utils.ids import generate_document_id

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Return backend health status."""

    return {
        "status": "ok",
        "service": "doctranslate-api",
    }


@router.post(
    "/documents/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(file: UploadFile = File(...)) -> DocumentUploadResponse:
    """Validate and store one uploaded PDF."""

    validate_pdf_metadata(file)
    content = await read_and_validate_pdf_content(file)

    document_id = generate_document_id()
    save_source_pdf(document_id, content)

    logger.info("PDF uploaded successfully document_id=%s", document_id)

    return DocumentUploadResponse(
        document_id=document_id,
        filename=file.filename or "source.pdf",
        status="uploaded",
    )
