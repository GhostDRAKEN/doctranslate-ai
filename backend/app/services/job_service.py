"""Simplified document processing job service."""

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import status

from app.core.errors import AppError
from app.schemas.job import DocumentStatusResponse
from app.services.storage_service import (
    document_exists,
    get_intermediate_path,
    get_status_path,
)
from app.utils.ids import generate_job_id

logger = logging.getLogger(__name__)

RUNNING_STATUSES = {"queued", "processing"}


def now_utc() -> str:
    """Return an ISO timestamp suitable for API responses."""

    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_status(
    document_id: str,
    *,
    status_value: str,
    current_step: str,
    progress: int,
    job_id: str | None = None,
    error: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the persisted status document."""

    return {
        "document_id": document_id,
        "job_id": job_id,
        "status": status_value,
        "current_step": current_step,
        "progress": progress,
        "updated_at": now_utc(),
        "error": error,
    }


def write_status(document_id: str, payload: dict[str, Any]) -> None:
    """Persist status.json for a document."""

    status_path = get_status_path(document_id)
    status_path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def read_status(document_id: str) -> dict[str, Any]:
    """Read status.json or fail with a controlled document error."""

    ensure_document_exists(document_id)
    status_path = get_status_path(document_id)
    if not status_path.is_file():
        payload = build_status(
            document_id,
            status_value="uploaded",
            current_step="upload",
            progress=0,
        )
        write_status(document_id, payload)
        return payload

    return json.loads(status_path.read_text(encoding="utf-8"))


def initialize_uploaded_status(document_id: str) -> None:
    """Set the initial uploaded status after a successful upload."""

    write_status(
        document_id,
        build_status(
            document_id,
            status_value="uploaded",
            current_step="upload",
            progress=0,
        ),
    )


def ensure_document_exists(document_id: str) -> None:
    """Raise a standard error when the document does not exist."""

    if not document_exists(document_id):
        raise AppError(
            code="DOCUMENT_NOT_FOUND",
            message="Le document demande est introuvable.",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"document_id": document_id},
        )


def get_document_status(document_id: str) -> DocumentStatusResponse:
    """Return current status for API polling."""

    return DocumentStatusResponse.model_validate(read_status(document_id))


def write_quality_report_if_available(document_id: str) -> None:
    """Generate the final quality report without blocking the processing job."""

    if not get_intermediate_path(document_id).is_file():
        logger.warning(
            "Quality report skipped document_id=%s reason=intermediate_missing",
            document_id,
        )
        return

    try:
        from app.services.quality_report_service import generate_and_save_quality_report

        report = generate_and_save_quality_report(document_id)
        logger.info(
            "Quality report generated document_id=%s recommendation=%s score=%.3f",
            document_id,
            report["recommendation"],
            report["overall_score"],
        )
    except Exception:
        logger.exception("Quality report generation failed document_id=%s", document_id)


def queue_processing_job(document_id: str) -> dict[str, str]:
    """Create a queued job and return its public identifiers."""

    current_status = read_status(document_id)
    if current_status["status"] in RUNNING_STATUSES:
        raise AppError(
            code="PROCESS_ALREADY_RUNNING",
            message="Un traitement est deja en cours pour ce document.",
            status_code=status.HTTP_409_CONFLICT,
            details={"document_id": document_id},
        )

    job_id = generate_job_id()
    write_status(
        document_id,
        build_status(
            document_id,
            status_value="queued",
            current_step="analysis",
            progress=0,
            job_id=job_id,
        ),
    )

    return {"job_id": job_id, "document_id": document_id}


def run_document_processing(document_id: str, job_id: str) -> None:
    """Run the current MVP processing pipeline and update status.json."""

    try:
        from app.core.config import get_settings

        settings = get_settings()
        logger.info("Processing started document_id=%s job_id=%s", document_id, job_id)
        if settings.enable_batch_mode:
            write_status(
                document_id,
                build_status(
                    document_id,
                    status_value="processing",
                    current_step="analysis",
                    progress=10,
                    job_id=job_id,
                ),
            )

            def update_batch_status(current_step: str, progress: int) -> None:
                write_status(
                    document_id,
                    build_status(
                        document_id,
                        status_value="processing",
                        current_step=current_step,
                        progress=progress,
                        job_id=job_id,
                    ),
                )

            from app.services.batch_service import process_document_in_batches

            process_document_in_batches(
                document_id,
                status_callback=update_batch_status,
            )
            time.sleep(0.05)
            write_quality_report_if_available(document_id)

            write_status(
                document_id,
                build_status(
                    document_id,
                    status_value="completed",
                    current_step="done",
                    progress=100,
                    job_id=job_id,
                ),
            )
            logger.info(
                "Batch processing completed document_id=%s job_id=%s",
                document_id,
                job_id,
            )
            return

        write_status(
            document_id,
            build_status(
                document_id,
                status_value="processing",
                current_step="analysis",
                progress=20,
                job_id=job_id,
            ),
        )
        time.sleep(0.05)

        write_status(
            document_id,
            build_status(
                document_id,
                status_value="processing",
                current_step="extraction",
                progress=60,
                job_id=job_id,
            ),
        )

        from app.services.extraction_service import extract_document_intermediate

        extract_document_intermediate(document_id)
        time.sleep(0.05)

        write_status(
            document_id,
            build_status(
                document_id,
                status_value="processing",
                current_step="translation",
                progress=80,
                job_id=job_id,
            ),
        )

        from app.services.translation_service import translate_document_intermediate

        translate_document_intermediate(document_id)
        time.sleep(0.05)

        write_status(
            document_id,
            build_status(
                document_id,
                status_value="processing",
                current_step="validation_report",
                progress=90,
                job_id=job_id,
            ),
        )
        write_quality_report_if_available(document_id)
        time.sleep(0.05)

        write_status(
            document_id,
            build_status(
                document_id,
                status_value="completed",
                current_step="done",
                progress=100,
                job_id=job_id,
            ),
        )
        logger.info("Processing completed document_id=%s job_id=%s", document_id, job_id)
    except AppError as exc:
        logger.warning(
            "Processing stopped document_id=%s job_id=%s code=%s",
            document_id,
            job_id,
            exc.code,
        )
        write_status(
            document_id,
            build_status(
                document_id,
                status_value="failed",
                current_step="done",
                progress=0,
                job_id=job_id,
                error={
                    "code": exc.code,
                    "message": exc.message,
                },
            ),
        )
    except Exception:
        logger.exception("Processing failed document_id=%s job_id=%s", document_id, job_id)
        write_status(
            document_id,
            build_status(
                document_id,
                status_value="failed",
                current_step="done",
                progress=0,
                job_id=job_id,
                error={
                    "code": "INTERNAL_ERROR",
                    "message": "Une erreur interne est survenue pendant le traitement.",
                },
            ),
        )
