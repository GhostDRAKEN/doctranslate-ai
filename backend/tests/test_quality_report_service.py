import json
import shutil

from app.services.quality_report_service import (
    generate_and_save_quality_report,
    generate_quality_report,
)
from app.services.storage_service import (
    get_document_directory,
    get_intermediate_path,
    get_quality_report_path,
)


def _block(
    *,
    block_id: str = "block_001",
    translated_text: str = "Ce contrat definit les responsabilites de chaque partie.",
    status: str = "translated",
    warnings: list[str] | None = None,
    quality: dict | None = None,
) -> dict:
    return {
        "id": block_id,
        "page_number": 1,
        "type": "paragraph",
        "source_text": "This agreement defines the responsibilities of each party.",
        "translated_text": translated_text,
        "bbox": [72, 100, 430, 130],
        "style": {"font": "Helvetica", "size": 11, "alignment": "left"},
        "reading_order": 1,
        "status": status,
        "warnings": warnings or [],
        "semantic_confidence_score": 0.92,
        "quality": quality
        or {
            "translation_quality_score": 0.95,
            "english_residual_score": 0.0,
            "semantic_consistency_score": 0.94,
            "overlay_risk_score": 0.05,
        },
    }


def _payload(*, blocks: list[dict] | None = None, document_quality: dict | None = None) -> dict:
    return {
        "document_id": "doc_quality_report",
        "source_language": "en",
        "target_language": "fr",
        "domain": "business",
        "metadata": {
            "filename": "sample.pdf",
            "page_count": 1,
            "file_size_mb": 0.1,
            "created_at": "2026-05-26T10:00:00Z",
        },
        "mvp_limits": {
            "max_pages": 10,
            "max_file_size_mb": 10,
            "digital_pdf_only": True,
            "requires_selectable_text": True,
        },
        "glossary": [],
        "pages": [
            {
                "page_number": 1,
                "width": 595,
                "height": 842,
                "blocks": blocks or [_block()],
            }
        ],
        "sections": [],
        "document_quality": document_quality
        or {
            "average_translation_quality": 0.95,
            "average_english_residual_score": 0.0,
            "average_semantic_consistency": 0.94,
            "average_overlay_risk": 0.05,
            "blocks_needing_review": 0,
            "total_blocks_scored": 1,
        },
        "warnings": [],
    }


def _cleanup_document(document_id: str) -> None:
    document_dir = get_document_directory(document_id)
    if document_dir.exists():
        shutil.rmtree(document_dir)


def test_quality_report_recommends_document_ready() -> None:
    report = generate_quality_report(_payload())

    assert report["recommendation"] == "document_ready"
    assert report["overall_score"] >= 0.9
    assert report["english_residual_count"] == 0
    assert report["warnings_count"] == 0


def test_quality_report_recommends_minor_review_for_non_critical_warnings() -> None:
    payload = _payload(
        blocks=[
            _block(
                warnings=["paragraph_english_residual_cleaned"],
                quality={
                    "translation_quality_score": 0.9,
                    "english_residual_score": 0.0,
                    "semantic_consistency_score": 0.9,
                    "overlay_risk_score": 0.1,
                },
            )
        ],
        document_quality={
            "average_translation_quality": 0.9,
            "average_english_residual_score": 0.0,
            "average_semantic_consistency": 0.9,
            "average_overlay_risk": 0.1,
            "blocks_needing_review": 1,
            "total_blocks_scored": 1,
        },
    )

    report = generate_quality_report(payload)

    assert report["recommendation"] == "document_ready_with_minor_review"
    assert "manual_review_recommended" in report["minor_issues"]


def test_quality_report_recommends_review_for_residual_english() -> None:
    payload = _payload(
        blocks=[
            _block(
                block_id="block_001",
                warnings=["english_residual_detected"],
                quality={
                    "translation_quality_score": 0.82,
                    "english_residual_score": 0.4,
                    "semantic_consistency_score": 0.82,
                    "overlay_risk_score": 0.2,
                },
            ),
            _block(
                block_id="block_002",
                warnings=["english_residual_detected"],
                quality={
                    "translation_quality_score": 0.82,
                    "english_residual_score": 0.4,
                    "semantic_consistency_score": 0.82,
                    "overlay_risk_score": 0.2,
                },
            ),
            _block(
                block_id="block_003",
                warnings=["english_residual_detected"],
                quality={
                    "translation_quality_score": 0.82,
                    "english_residual_score": 0.4,
                    "semantic_consistency_score": 0.82,
                    "overlay_risk_score": 0.2,
                },
            ),
        ],
        document_quality={
            "average_translation_quality": 0.82,
            "average_english_residual_score": 0.4,
            "average_semantic_consistency": 0.82,
            "average_overlay_risk": 0.2,
            "blocks_needing_review": 3,
            "total_blocks_scored": 3,
        },
    )

    report = generate_quality_report(payload)

    assert report["recommendation"] == "document_needs_review"
    assert report["english_residual_count"] == 3
    assert "english_residuals_detected" in report["major_issues"]


def test_quality_report_recommends_not_ready_for_empty_translation() -> None:
    payload = _payload(
        blocks=[
            _block(
                translated_text="",
                status="pending",
                quality={
                    "translation_quality_score": 0.0,
                    "english_residual_score": 0.0,
                    "semantic_consistency_score": 0.0,
                    "overlay_risk_score": 0.0,
                },
            )
        ],
        document_quality={
            "average_translation_quality": 0.0,
            "average_english_residual_score": 0.0,
            "average_semantic_consistency": 0.0,
            "average_overlay_risk": 0.0,
            "blocks_needing_review": 1,
            "total_blocks_scored": 1,
        },
    )

    report = generate_quality_report(payload)

    assert report["recommendation"] == "document_not_ready"
    assert "translation_incomplete" in report["major_issues"]


def test_quality_report_counts_warnings_and_english_residuals() -> None:
    payload = _payload(
        blocks=[
            _block(
                warnings=["english_residual_detected", "high_overlay_risk"],
                quality={
                    "translation_quality_score": 0.8,
                    "english_residual_score": 0.5,
                    "semantic_consistency_score": 0.8,
                    "overlay_risk_score": 0.6,
                },
            )
        ],
    )
    payload["warnings"] = ["document_warning"]

    report = generate_quality_report(payload)

    assert report["warnings_count"] == 3
    assert report["english_residual_count"] == 1


def test_quality_report_penalizes_failed_batch() -> None:
    payload = _payload()
    payload["batch_summary"] = {
        "enabled": True,
        "batch_size_pages": 5,
        "total_batches": 3,
        "completed_batches": 2,
        "failed_batches": 1,
    }

    report = generate_quality_report(payload)

    assert report["recommendation"] == "document_not_ready"
    assert report["failed_batches"] == 1
    assert "batch_failed" in report["major_issues"]


def test_quality_report_flags_untranslated_table_cells() -> None:
    table_block = {
        "id": "block_table_001",
        "page_number": 1,
        "type": "table",
        "source_text": "",
        "translated_text": "",
        "bbox": [72, 160, 500, 240],
        "style": {"font": "Helvetica", "size": 9, "alignment": "left"},
        "reading_order": 2,
        "status": "translated",
        "warnings": [],
        "table_grid_confidence": 0.95,
        "rows": [
            {
                "cells": [
                    {
                        "row": 0,
                        "column": 0,
                        "source_text": "Industry",
                        "translated_text": "Secteur",
                    },
                    {
                        "row": 0,
                        "column": 1,
                        "source_text": "Potential Risk",
                        "translated_text": "",
                    },
                ]
            }
        ],
    }
    payload = _payload(blocks=[_block(), table_block])

    report = generate_quality_report(payload)

    assert report["recommendation"] == "document_not_ready"
    assert report["tables_count"] == 1
    assert "table_translation_incomplete" in report["major_issues"]


def test_quality_report_file_and_intermediate_summary_are_generated() -> None:
    document_id = "doc_quality_report_save"
    _cleanup_document(document_id)
    get_document_directory(document_id).mkdir(parents=True)
    payload = _payload()
    payload["document_id"] = document_id
    get_intermediate_path(document_id).write_text(
        json.dumps(payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )

    report = generate_and_save_quality_report(document_id)
    updated_payload = json.loads(get_intermediate_path(document_id).read_text("utf-8"))

    assert get_quality_report_path(document_id).is_file()
    assert report["document_id"] == document_id
    assert updated_payload["quality_report_summary"]["overall_score"] == report[
        "overall_score"
    ]
    assert updated_payload["quality_report_summary"]["recommendation"] == report[
        "recommendation"
    ]

    _cleanup_document(document_id)
