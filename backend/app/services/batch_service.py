"""Experimental page-batch processing helpers for long documents."""

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import fitz
from fastapi import status

from app.core.config import get_settings
from app.core.errors import AppError
from app.services.storage_service import document_exists
from app.services.storage_service import (
    get_batches_directory,
    get_intermediate_path,
    get_source_pdf_path,
)


@dataclass(frozen=True)
class PageBatch:
    """One inclusive page range prepared for batch processing."""

    batch_id: str
    page_start: int
    page_end: int


def now_utc() -> str:
    """Return an ISO timestamp for batch manifests."""

    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_page_batches(total_pages: int, batch_size: int) -> list[PageBatch]:
    """Split pages into inclusive page ranges."""

    if total_pages <= 0:
        return []
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    batches: list[PageBatch] = []
    page_start = 1
    while page_start <= total_pages:
        page_end = min(page_start + batch_size - 1, total_pages)
        batches.append(
            PageBatch(
                batch_id=f"batch_{len(batches) + 1:03d}",
                page_start=page_start,
                page_end=page_end,
            )
        )
        page_start = page_end + 1

    return batches


def write_batch_manifests(
    document_id: str,
    payload: dict[str, Any],
    batch_size: int,
) -> list[dict[str, Any]]:
    """Persist lightweight per-batch metadata for inspection and future resumes."""

    total_pages = int((payload.get("metadata") or {}).get("page_count") or 0)
    if total_pages <= 0:
        total_pages = len(payload.get("pages", []))

    batches_dir = get_batches_directory(document_id)
    batches_dir.mkdir(parents=True, exist_ok=True)

    manifests: list[dict[str, Any]] = []
    for batch in build_page_batches(total_pages, batch_size):
        blocks = collect_batch_blocks(payload, batch)
        manifest = {
            **asdict(batch),
            "document_id": document_id,
            "status": infer_batch_status(blocks),
            "blocks_count": len(blocks),
            "translated_blocks_count": count_translated_blocks(blocks),
            "warnings": collect_batch_warnings(blocks),
            "error": None,
            "created_at": now_utc(),
            "updated_at": now_utc(),
        }
        (batches_dir / f"{batch.batch_id}.json").write_text(
            json.dumps(manifest, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        manifests.append(manifest)

    return manifests


def initialize_batch_manifests(
    document_id: str,
    payload: dict[str, Any],
    batch_size: int,
) -> list[dict[str, Any]]:
    """Create missing batch manifests while preserving completed batch state."""

    total_pages = int((payload.get("metadata") or {}).get("page_count") or 0)
    if total_pages <= 0:
        total_pages = len(payload.get("pages", []))

    batches_dir = get_batches_directory(document_id)
    batches_dir.mkdir(parents=True, exist_ok=True)

    manifests: list[dict[str, Any]] = []
    for batch in build_page_batches(total_pages, batch_size):
        path = batches_dir / f"{batch.batch_id}.json"
        if path.is_file():
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest.setdefault("document_id", document_id)
            manifest.setdefault("created_at", now_utc())
            manifest.setdefault("updated_at", now_utc())
            write_batch_manifest(document_id, manifest)
        else:
            blocks = collect_batch_blocks(payload, batch)
            manifest = {
                **asdict(batch),
                "document_id": document_id,
                "status": "pending",
                "blocks_count": len(blocks),
                "translated_blocks_count": 0,
                "warnings": [],
                "error": None,
                "created_at": now_utc(),
                "updated_at": now_utc(),
            }
            write_batch_manifest(document_id, manifest)
        manifests.append(manifest)

    return manifests


def resume_incomplete_batches(document_id: str) -> dict[str, Any]:
    """Translate pending or failed page batches and persist progress."""

    intermediate_path = get_intermediate_path(document_id)
    if not intermediate_path.is_file():
        raise AppError(
            code="RESULT_NOT_READY",
            message="La representation intermediaire n'est pas encore disponible.",
            status_code=status.HTTP_409_CONFLICT,
            details={"document_id": document_id},
        )

    payload = json.loads(intermediate_path.read_text(encoding="utf-8"))
    settings = get_settings()
    manifests = initialize_batch_manifests(
        document_id,
        payload,
        settings.batch_size_pages,
    )

    for manifest in manifests:
        if manifest.get("status") == "completed":
            continue

        manifest["status"] = "processing"
        manifest["error"] = None
        write_batch_manifest(document_id, manifest)

        try:
            translated_count = translate_batch_payload(
                payload,
                int(manifest["page_start"]),
                int(manifest["page_end"]),
            )
            blocks = collect_batch_blocks(
                payload,
                PageBatch(
                    batch_id=str(manifest["batch_id"]),
                    page_start=int(manifest["page_start"]),
                    page_end=int(manifest["page_end"]),
                ),
            )
            manifest.update(
                {
                    "status": "completed",
                    "blocks_count": len(blocks),
                    "translated_blocks_count": translated_count,
                    "warnings": collect_batch_warnings(blocks),
                    "error": None,
                }
            )
            persist_intermediate_payload(intermediate_path, payload)
            write_batch_manifest(document_id, manifest)
        except AppError as exc:
            manifest.update(
                {
                    "status": "failed",
                    "error": {"code": exc.code, "message": exc.message},
                }
            )
            write_batch_manifest(document_id, manifest)
            persist_intermediate_payload(intermediate_path, payload)
            raise
        except Exception as exc:
            manifest.update(
                {
                    "status": "failed",
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "Une erreur interne est survenue pendant le batch.",
                    },
                }
            )
            write_batch_manifest(document_id, manifest)
            persist_intermediate_payload(intermediate_path, payload)
            raise AppError(
                code="INTERNAL_ERROR",
                message="Une erreur interne est survenue pendant le batch.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from exc

    finalize_batch_payload(payload)
    payload["batch_summary"] = build_batch_summary(
        document_id,
        settings.batch_size_pages,
    )
    persist_intermediate_payload(intermediate_path, payload)
    return payload


def process_document_in_batches(
    document_id: str,
    *,
    status_callback: Any | None = None,
) -> dict[str, Any]:
    """Extract, translate, score and merge a document page range by page range."""

    if not document_exists(document_id):
        raise AppError(
            code="DOCUMENT_NOT_FOUND",
            message="Le document demande est introuvable.",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"document_id": document_id},
        )

    settings = get_settings()
    source_path = get_source_pdf_path(document_id)
    with fitz.open(source_path) as pdf_document:
        total_pages = pdf_document.page_count

    if total_pages > settings.max_batch_experimental_pages:
        raise AppError(
            code="PDF_TOO_MANY_PAGES",
            message=(
                "Le PDF depasse la limite batch experimentale de "
                f"{settings.max_batch_experimental_pages} pages."
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
            details={
                "page_count": total_pages,
                "max_page_count": settings.max_batch_experimental_pages,
            },
        )

    batches = build_page_batches(total_pages, settings.batch_size_pages)
    notify_status(status_callback, "analysis", 10)
    initialize_empty_batch_manifests(document_id, batches)

    batch_payloads: list[dict[str, Any]] = []
    total_batches = len(batches)
    for batch_index, batch in enumerate(batches, start=1):
        manifest = read_batch_manifest(document_id, batch)
        if manifest.get("status") == "completed" and manifest.get("pages"):
            batch_payloads.append(build_payload_from_completed_manifest(manifest))
            continue

        start_progress = 20 + int(((batch_index - 1) / max(total_batches, 1)) * 60)
        notify_status(status_callback, "translation", start_progress)
        manifest.update(
            {
                "status": "processing",
                "error": None,
                "updated_at": now_utc(),
            }
        )
        write_batch_manifest(document_id, manifest)

        try:
            batch_payload = extract_and_translate_batch(document_id, batch)
            batch_blocks = collect_batch_blocks(batch_payload, batch)
            manifest.update(
                {
                    "status": "completed",
                    "blocks_count": len(batch_blocks),
                    "translated_blocks_count": count_translated_blocks(batch_blocks),
                    "warnings": collect_batch_warnings(batch_blocks),
                    "error": None,
                    "source_language": batch_payload.get("source_language", "en"),
                    "target_language": batch_payload.get("target_language", "fr"),
                    "domain": batch_payload.get("domain", "general"),
                    "metadata": batch_payload.get("metadata") or {},
                    "mvp_limits": batch_payload.get("mvp_limits") or {},
                    "glossary": batch_payload.get("glossary") or [],
                    "pages": batch_payload.get("pages", []),
                    "sections": batch_payload.get("sections", []),
                    "updated_at": now_utc(),
                }
            )
            write_batch_manifest(document_id, manifest)
            batch_payloads.append(batch_payload)
        except AppError as exc:
            manifest.update(
                {
                    "status": "failed",
                    "error": {"code": exc.code, "message": exc.message},
                    "updated_at": now_utc(),
                }
            )
            write_batch_manifest(document_id, manifest)
            raise
        except Exception as exc:
            manifest.update(
                {
                    "status": "failed",
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "Une erreur interne est survenue pendant le batch.",
                    },
                    "updated_at": now_utc(),
                }
            )
            write_batch_manifest(document_id, manifest)
            raise AppError(
                code="INTERNAL_ERROR",
                message="Une erreur interne est survenue pendant le batch.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from exc

    notify_status(status_callback, "validation_report", 90)
    final_payload = merge_batch_payloads(
        document_id,
        batch_payloads,
        batch_size=settings.batch_size_pages,
    )
    persist_intermediate_payload(get_intermediate_path(document_id), final_payload)
    return final_payload


def initialize_empty_batch_manifests(
    document_id: str,
    batches: list[PageBatch],
) -> list[dict[str, Any]]:
    """Create missing batch manifests without requiring an intermediate payload."""

    manifests: list[dict[str, Any]] = []
    for batch in batches:
        path = get_batches_directory(document_id) / f"{batch.batch_id}.json"
        if path.is_file():
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest.setdefault("document_id", document_id)
            manifest.setdefault("created_at", now_utc())
            manifest.setdefault("updated_at", now_utc())
            write_batch_manifest(document_id, manifest)
        else:
            manifest = {
                **asdict(batch),
                "document_id": document_id,
                "status": "pending",
                "blocks_count": 0,
                "translated_blocks_count": 0,
                "warnings": [],
                "error": None,
                "created_at": now_utc(),
                "updated_at": now_utc(),
            }
            write_batch_manifest(document_id, manifest)
        manifests.append(manifest)
    return manifests


def read_batch_manifest(document_id: str, batch: PageBatch) -> dict[str, Any]:
    """Read an existing batch manifest or create a pending one."""

    path = get_batches_directory(document_id) / f"{batch.batch_id}.json"
    if not path.is_file():
        return initialize_empty_batch_manifests(document_id, [batch])[0]
    return json.loads(path.read_text(encoding="utf-8"))


def extract_and_translate_batch(
    document_id: str,
    batch: PageBatch,
) -> dict[str, Any]:
    """Extract and translate one page batch payload."""

    from app.services.extraction_service import extract_document_batch_payload

    batch_payload = extract_document_batch_payload(
        document_id,
        page_start=batch.page_start,
        page_end=batch.page_end,
    )
    service = build_batch_translation_service()
    translated_count = service.translate_payload_page_range(
        batch_payload,
        page_start=batch.page_start,
        page_end=batch.page_end,
    )
    mock_output_allowed = (
        service.provider.provider_name == "mock"
        or get_settings().mock_translation_enabled
    )
    finalize_batch_payload(
        batch_payload,
        mock_translation_enabled=mock_output_allowed,
    )
    batch_payload["_translated_blocks_count"] = translated_count
    return batch_payload


def build_batch_translation_service() -> Any:
    """Build the translation service used for one batch."""

    from app.services.translation_service import TranslationService

    return TranslationService()


def build_payload_from_completed_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build a minimal payload from a completed manifest's stored pages."""

    return {
        "document_id": manifest.get("document_id"),
        "source_language": manifest.get("source_language", "en"),
        "target_language": manifest.get("target_language", "fr"),
        "domain": manifest.get("domain", "general"),
        "metadata": manifest.get("metadata") or {},
        "mvp_limits": manifest.get("mvp_limits") or {},
        "glossary": manifest.get("glossary") or [],
        "pages": manifest.get("pages") or [],
        "sections": manifest.get("sections") or [],
        "warnings": manifest.get("warnings") or [],
        "_translated_blocks_count": manifest.get("translated_blocks_count") or 0,
    }


def merge_batch_payloads(
    document_id: str,
    batch_payloads: list[dict[str, Any]],
    *,
    batch_size: int,
) -> dict[str, Any]:
    """Merge completed batch payloads into the final intermediate.json."""

    if not batch_payloads:
        raise AppError(
            code="INTERNAL_ERROR",
            message="Aucun lot batch n'a ete produit.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    base_payload = next(
        (payload for payload in batch_payloads if payload.get("metadata")),
        batch_payloads[0],
    )
    pages = [
        page
        for payload in batch_payloads
        for page in payload.get("pages", [])
    ]
    pages = sorted(pages, key=lambda page: int(page.get("page_number") or 0))
    reassign_block_ids(pages)
    warnings = collect_payload_warnings(batch_payloads)
    final_payload: dict[str, Any] = {
        "document_id": document_id,
        "source_language": base_payload.get("source_language", "en"),
        "target_language": base_payload.get("target_language", "fr"),
        "domain": base_payload.get("domain", "general"),
        "metadata": base_payload.get("metadata") or {},
        "mvp_limits": base_payload.get("mvp_limits") or {},
        "glossary": base_payload.get("glossary") or [],
        "pages": pages,
        "warnings": warnings,
    }
    rebuild_final_sections(final_payload)
    finalize_batch_payload(final_payload)
    final_payload["batch_summary"] = build_batch_summary(document_id, batch_size)
    return final_payload


def reassign_block_ids(pages: list[dict[str, Any]]) -> None:
    """Assign final unique block ids after merging batch pages."""

    block_index = 1
    for page in pages:
        blocks = sorted(
            page.get("blocks", []),
            key=lambda block: int(block.get("reading_order") or 0),
        )
        page["blocks"] = blocks
        for reading_order, block in enumerate(blocks, start=1):
            block["id"] = f"block_{block_index:03d}"
            block["reading_order"] = reading_order
            block_index += 1


def rebuild_final_sections(payload: dict[str, Any]) -> None:
    """Rebuild sections after final block ids have been assigned."""

    from app.services.section_service import build_document_sections

    payload["sections"] = build_document_sections(
        [
            block
            for page in payload.get("pages", [])
            for block in page.get("blocks", [])
        ]
    )


def collect_payload_warnings(payloads: list[dict[str, Any]]) -> list[str]:
    """Collect unique payload-level warnings from batch payloads."""

    warnings: list[str] = []
    for payload in payloads:
        for warning in payload.get("warnings") or []:
            warning_value = str(warning)
            if warning_value not in warnings:
                warnings.append(warning_value)
    return warnings


def build_batch_summary(document_id: str, batch_size: int) -> dict[str, Any]:
    """Build final batch summary from persisted manifests."""

    manifests = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(get_batches_directory(document_id).glob("batch_*.json"))
    ]
    return {
        "enabled": True,
        "batch_size_pages": batch_size,
        "total_batches": len(manifests),
        "completed_batches": sum(
            1 for manifest in manifests if manifest.get("status") == "completed"
        ),
        "failed_batches": sum(
            1 for manifest in manifests if manifest.get("status") == "failed"
        ),
    }


def translate_batch_payload(
    payload: dict[str, Any],
    page_start: int,
    page_end: int,
) -> int:
    """Translate one page range using the configured translation service."""

    from app.services.translation_service import TranslationService

    return TranslationService().translate_payload_page_range(
        payload,
        page_start=page_start,
        page_end=page_end,
    )


def finalize_batch_payload(
    payload: dict[str, Any],
    *,
    mock_translation_enabled: bool | None = None,
) -> None:
    """Recompute document-level quality after all batches are complete."""

    from app.services.quality_service import score_document_quality

    settings = get_settings()
    score_document_quality(
        payload,
        mock_translation_enabled=(
            settings.mock_translation_enabled
            if mock_translation_enabled is None
            else mock_translation_enabled
        ),
    )


def persist_intermediate_payload(path: Any, payload: dict[str, Any]) -> None:
    """Persist the evolving intermediate payload."""

    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def write_batch_manifest(document_id: str, manifest: dict[str, Any]) -> None:
    """Persist one batch manifest."""

    batches_dir = get_batches_directory(document_id)
    batches_dir.mkdir(parents=True, exist_ok=True)
    batch_id = str(manifest["batch_id"])
    manifest.setdefault("document_id", document_id)
    manifest.setdefault("created_at", now_utc())
    manifest["updated_at"] = manifest.get("updated_at") or now_utc()
    (batches_dir / f"{batch_id}.json").write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def collect_batch_blocks(
    payload: dict[str, Any],
    batch: PageBatch,
) -> list[dict[str, Any]]:
    """Return all blocks whose page is inside a batch range."""

    blocks: list[dict[str, Any]] = []
    for page in payload.get("pages", []):
        page_number = int(page.get("page_number") or 0)
        if batch.page_start <= page_number <= batch.page_end:
            blocks.extend(page.get("blocks", []))
    return blocks


def infer_batch_status(blocks: list[dict[str, Any]]) -> str:
    """Infer a simple batch status from its blocks."""

    if any(block.get("status") == "failed" for block in blocks):
        return "failed"
    if any(block.get("status") == "needs_review" for block in blocks):
        return "needs_review"
    if blocks and all(
        block.get("status") in {"translated", "skipped", "pending"}
        for block in blocks
    ):
        return "completed"
    return "pending"


def count_translated_blocks(blocks: list[dict[str, Any]]) -> int:
    """Count blocks with non-empty translated text."""

    return sum(
        1
        for block in blocks
        if block_has_translation(block)
    )


def block_has_translation(block: dict[str, Any]) -> bool:
    """Return whether a text or table block has translated content."""

    if str(block.get("translated_text") or "").strip():
        return True
    if block.get("type") == "table":
        for row in block.get("rows") or []:
            for cell in row.get("cells") or []:
                if str(cell.get("translated_text") or "").strip():
                    return True
    return False


def collect_batch_warnings(blocks: list[dict[str, Any]]) -> list[str]:
    """Collect unique warning codes for a batch."""

    warnings: list[str] = []
    for block in blocks:
        for warning in block.get("warnings") or []:
            warning_value = str(warning)
            if warning_value not in warnings:
                warnings.append(warning_value)
        if block.get("type") == "table":
            for row in block.get("rows") or []:
                for cell in row.get("cells") or []:
                    for warning in cell.get("warnings") or []:
                        warning_value = str(warning)
                        if warning_value not in warnings:
                            warnings.append(warning_value)
    return warnings


def notify_status(
    status_callback: Any | None,
    current_step: str,
    progress: int,
) -> None:
    """Call the optional job status callback."""

    if status_callback is not None:
        status_callback(current_step, progress)
