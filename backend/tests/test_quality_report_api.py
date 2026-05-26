import json
import shutil

from fastapi.testclient import TestClient

from app.main import app
from app.services.storage_service import (
    get_document_directory,
    get_intermediate_path,
    get_quality_report_path,
    save_source_pdf,
)


def _cleanup_document(document_id: str) -> None:
    document_dir = get_document_directory(document_id)
    if document_dir.exists():
        shutil.rmtree(document_dir)


def _create_document(document_id: str) -> None:
    _cleanup_document(document_id)
    save_source_pdf(document_id, b"%PDF-1.4\n% test\n%%EOF")


def _block() -> dict:
    return {
        "id": "block_001",
        "page_number": 1,
        "type": "paragraph",
        "source_text": "This agreement defines the responsibilities of each party.",
        "translated_text": "Ce contrat definit les responsabilites de chaque partie.",
        "bbox": [72, 100, 430, 130],
        "style": {"font": "Helvetica", "size": 11, "alignment": "left"},
        "reading_order": 1,
        "status": "translated",
        "warnings": [],
        "semantic_confidence_score": 0.92,
        "quality": {
            "translation_quality_score": 0.95,
            "english_residual_score": 0.0,
            "semantic_consistency_score": 0.94,
            "overlay_risk_score": 0.05,
        },
    }


def _intermediate_payload(document_id: str) -> dict:
    return {
        "document_id": document_id,
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
                "blocks": [_block()],
            }
        ],
        "sections": [],
        "document_quality": {
            "average_translation_quality": 0.95,
            "average_english_residual_score": 0.0,
            "average_semantic_consistency": 0.94,
            "average_overlay_risk": 0.05,
            "blocks_needing_review": 0,
            "total_blocks_scored": 1,
        },
        "warnings": [],
    }


def _write_intermediate(document_id: str, payload: dict | None = None) -> None:
    get_intermediate_path(document_id).write_text(
        json.dumps(payload or _intermediate_payload(document_id), ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def test_quality_report_endpoint_returns_existing_report() -> None:
    client = TestClient(app)
    document_id = "doc_quality_report_existing"
    _create_document(document_id)
    report = {
        "document_id": document_id,
        "overall_score": 0.91,
        "translation_score": 0.95,
        "overlay_score": 0.9,
        "semantic_score": 0.94,
        "table_score": 1.0,
        "english_residual_count": 0,
        "warnings_count": 0,
        "blocks_count": 1,
        "translated_blocks_count": 1,
        "tables_count": 0,
        "pages_count": 1,
        "recommendation": "document_ready",
        "major_issues": [],
        "minor_issues": [],
        "created_at": "2026-05-26T10:00:00Z",
    }
    get_quality_report_path(document_id).write_text(
        json.dumps(report, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )

    response = client.get(f"/api/documents/{document_id}/quality-report")

    assert response.status_code == 200
    assert response.json()["recommendation"] == "document_ready"
    assert response.json()["overall_score"] == 0.91

    _cleanup_document(document_id)


def test_quality_report_endpoint_generates_report_when_missing() -> None:
    client = TestClient(app)
    document_id = "doc_quality_report_generate"
    _create_document(document_id)
    _write_intermediate(document_id)

    response = client.get(f"/api/documents/{document_id}/quality-report")
    updated_payload = json.loads(get_intermediate_path(document_id).read_text("utf-8"))

    assert response.status_code == 200
    assert get_quality_report_path(document_id).is_file()
    assert response.json()["document_id"] == document_id
    assert response.json()["recommendation"] == "document_ready"
    assert "overall_score" in response.json()
    assert "translation_score" in response.json()
    assert updated_payload["quality_report_summary"]["recommendation"] == (
        response.json()["recommendation"]
    )

    _cleanup_document(document_id)


def test_quality_report_endpoint_returns_result_not_ready_without_intermediate() -> None:
    client = TestClient(app)
    document_id = "doc_quality_report_not_ready"
    _create_document(document_id)

    response = client.get(f"/api/documents/{document_id}/quality-report")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RESULT_NOT_READY"

    _cleanup_document(document_id)


def test_quality_report_endpoint_includes_batch_summary_fields() -> None:
    client = TestClient(app)
    document_id = "doc_quality_report_batch"
    _create_document(document_id)
    payload = _intermediate_payload(document_id)
    payload["batch_summary"] = {
        "enabled": True,
        "batch_size_pages": 5,
        "total_batches": 3,
        "completed_batches": 3,
        "failed_batches": 0,
    }
    _write_intermediate(document_id, payload)

    response = client.get(f"/api/documents/{document_id}/quality-report")

    assert response.status_code == 200
    assert response.json()["total_batches"] == 3
    assert response.json()["completed_batches"] == 3
    assert response.json()["failed_batches"] == 0

    _cleanup_document(document_id)
