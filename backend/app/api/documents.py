"""Document-related API routes."""

import logging

from fastapi import APIRouter, BackgroundTasks, File, UploadFile, status

from app.schemas.document import DocumentUploadResponse
from app.schemas.job import (
    DocumentStatusResponse,
    ProcessDocumentRequest,
    ProcessDocumentResponse,
)
from app.services.extraction_service import read_intermediate
from app.services.job_service import (
    ensure_document_exists,
    get_document_status,
    initialize_uploaded_status,
    queue_processing_job,
    run_document_processing,
)
from app.services.storage_service import save_source_pdf
from app.services.upload_validation import (
    read_and_validate_pdf_content,
    validate_pdf_mvp_limits,
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
    validate_pdf_mvp_limits(content)

    document_id = generate_document_id()
    save_source_pdf(document_id, content)
    initialize_uploaded_status(document_id)

    logger.info("PDF uploaded successfully document_id=%s", document_id)

    return DocumentUploadResponse(
        document_id=document_id,
        filename=file.filename or "source.pdf",
        status="uploaded",
    )


@router.post(
    "/documents/{document_id}/process",
    response_model=ProcessDocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def process_document(
    document_id: str,
    _: ProcessDocumentRequest,
    background_tasks: BackgroundTasks,
) -> ProcessDocumentResponse:
    """Queue simplified document processing in the background."""

    queued_job = queue_processing_job(document_id)
    background_tasks.add_task(
        run_document_processing,
        document_id,
        queued_job["job_id"],
    )

    logger.info(
        "Processing queued document_id=%s job_id=%s",
        document_id,
        queued_job["job_id"],
    )

    return ProcessDocumentResponse(
        job_id=queued_job["job_id"],
        document_id=document_id,
        status="queued",
        translation_provider="mock",
    )


@router.get(
    "/documents/{document_id}/status",
    response_model=DocumentStatusResponse,
)
async def document_status(document_id: str) -> DocumentStatusResponse:
    """Return current document processing status."""

    return get_document_status(document_id)


@router.get("/documents/{document_id}/intermediate")
async def document_intermediate(document_id: str) -> dict:
    """Return the intermediate representation for MVP debug."""

    ensure_document_exists(document_id)
    return read_intermediate(document_id)
