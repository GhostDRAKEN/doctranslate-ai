"""Document-related API routes."""

import json
import logging

from fastapi import APIRouter, BackgroundTasks, File, UploadFile, status
from fastapi.responses import FileResponse

from app.core.errors import AppError
from app.schemas.document import (
    DocumentDocxGenerationResponse,
    DocumentPdfGenerationResponse,
    DocumentUploadResponse,
    QualityReportResponse,
)
from app.schemas.job import (
    DocumentStatusResponse,
    ProcessDocumentRequest,
    ProcessDocumentResponse,
)
from app.services.docx.docx_generator import generate_docx
from app.services.extraction_service import read_intermediate
from app.services.job_service import (
    ensure_document_exists,
    get_document_status,
    initialize_uploaded_status,
    queue_processing_job,
    run_document_processing,
)
from app.services.pdf_overlay_service import generate_pdf_overlay
from app.services.quality_report_service import generate_and_save_quality_report
from app.services.storage_service import (
    get_docx_result_path,
    get_pdf_result_path,
    get_quality_report_path,
    save_source_pdf,
)
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


@router.get(
    "/documents/{document_id}/quality-report",
    response_model=QualityReportResponse,
)
async def document_quality_report(document_id: str) -> QualityReportResponse:
    """Return or lazily generate the automatic document quality report."""

    ensure_document_exists(document_id)
    report_path = get_quality_report_path(document_id)
    if report_path.is_file():
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    else:
        payload = generate_and_save_quality_report(document_id)
    return QualityReportResponse.model_validate(payload)


@router.post(
    "/documents/{document_id}/generate-docx",
    response_model=DocumentDocxGenerationResponse,
)
async def generate_document_docx(document_id: str) -> DocumentDocxGenerationResponse:
    """Generate a MVP DOCX from the translated intermediate document."""

    generate_docx(document_id)
    return DocumentDocxGenerationResponse(
        document_id=document_id,
        status="docx_generated",
        download_url=f"/api/documents/{document_id}/download/docx",
    )


@router.post(
    "/documents/{document_id}/generate-pdf",
    response_model=DocumentPdfGenerationResponse,
)
async def generate_document_pdf(document_id: str) -> DocumentPdfGenerationResponse:
    """Generate a MVP translated PDF overlay from the intermediate document."""

    generate_pdf_overlay(document_id)
    return DocumentPdfGenerationResponse(
        document_id=document_id,
        status="pdf_generated",
        download_url=f"/api/documents/{document_id}/download/pdf",
    )


@router.get("/documents/{document_id}/download/docx")
async def download_document_docx(document_id: str) -> FileResponse:
    """Download the generated DOCX file."""

    ensure_document_exists(document_id)
    docx_path = get_docx_result_path(document_id)
    if not docx_path.is_file():
        raise AppError(
            code="DOCX_NOT_FOUND",
            message="Le document DOCX n'est pas encore disponible.",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"document_id": document_id},
        )

    return FileResponse(
        path=docx_path,
        filename="result.docx",
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
    )


@router.get("/documents/{document_id}/download/pdf")
async def download_document_pdf(document_id: str) -> FileResponse:
    """Download the generated PDF overlay file."""

    ensure_document_exists(document_id)
    pdf_path = get_pdf_result_path(document_id)
    if not pdf_path.is_file():
        raise AppError(
            code="PDF_NOT_FOUND",
            message="Le PDF genere est introuvable.",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"document_id": document_id},
        )

    return FileResponse(
        path=pdf_path,
        filename="translated_document.pdf",
        media_type="application/pdf",
    )
