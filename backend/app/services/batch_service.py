"""Experimental page-batch processing helpers for long documents."""

import json
from dataclasses import asdict, dataclass
from typing import Any

from fastapi import status

from app.core.config import get_settings
from app.core.errors import AppError
from app.services.storage_service import (
    get_batches_directory,
    get_intermediate_path,
)


@dataclass(frozen=True)
class PageBatch:
    """One inclusive page range prepared for batch processing."""

    batch_id: str
    page_start: int
    page_end: int


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
            "status": infer_batch_status(blocks),
            "blocks_count": len(blocks),
            "translated_blocks_count": count_translated_blocks(blocks),
            "warnings": collect_batch_warnings(blocks),
            "error": None,
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
        else:
            blocks = collect_batch_blocks(payload, batch)
            manifest = {
                **asdict(batch),
                "status": "pending",
                "blocks_count": len(blocks),
                "translated_blocks_count": 0,
                "warnings": [],
                "error": None,
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
    persist_intermediate_payload(intermediate_path, payload)
    return payload


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


def finalize_batch_payload(payload: dict[str, Any]) -> None:
    """Recompute document-level quality after all batches are complete."""

    from app.services.quality_service import score_document_quality

    settings = get_settings()
    score_document_quality(
        payload,
        mock_translation_enabled=settings.mock_translation_enabled,
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
        if str(block.get("translated_text") or "").strip()
    )


def collect_batch_warnings(blocks: list[dict[str, Any]]) -> list[str]:
    """Collect unique warning codes for a batch."""

    warnings: list[str] = []
    for block in blocks:
        for warning in block.get("warnings") or []:
            warning_value = str(warning)
            if warning_value not in warnings:
                warnings.append(warning_value)
    return warnings
