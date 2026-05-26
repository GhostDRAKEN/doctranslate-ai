import shutil

import fitz
from fastapi.testclient import TestClient
from fastapi import status

from app.core.errors import AppError
from app.main import app
from app.services.job_service import build_status, write_status
from app.services.storage_service import (
    get_intermediate_path,
    get_storage_root,
    save_source_pdf,
)


def _cleanup_document(document_id: str) -> None:
    document_dir = get_storage_root() / document_id
    if document_dir.exists():
        shutil.rmtree(document_dir)


def _sample_pdf_bytes() -> bytes:
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Service Agreement", fontsize=18)
    page.insert_text(
        (72, 120),
        "This agreement defines the responsibilities of each party.",
        fontsize=11,
    )
    content = pdf.tobytes()
    pdf.close()
    return content


def _pdf_with_pages(page_count: int) -> bytes:
    pdf = fitz.open()
    for index in range(page_count):
        page = pdf.new_page()
        page.insert_text((72, 72), f"Legacy page {index + 1}", fontsize=12)
    content = pdf.tobytes()
    pdf.close()
    return content


def _upload_pdf(client: TestClient) -> str:
    response = client.post(
        "/api/documents/upload",
        files={
            "file": (
                "sample.pdf",
                _sample_pdf_bytes(),
                "application/pdf",
            )
        },
    )
    assert response.status_code == 201
    return str(response.json()["document_id"])


def test_status_existing_document_after_upload() -> None:
    client = TestClient(app)
    document_id = _upload_pdf(client)

    response = client.get(f"/api/documents/{document_id}/status")

    assert response.status_code == 200
    assert response.json()["document_id"] == document_id
    assert response.json()["status"] == "uploaded"
    assert response.json()["current_step"] == "upload"
    assert response.json()["progress"] == 0

    _cleanup_document(document_id)


def test_process_existing_document() -> None:
    client = TestClient(app)
    document_id = _upload_pdf(client)

    response = client.post(
        f"/api/documents/{document_id}/process",
        json={"target_language": "fr", "glossary": []},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["document_id"] == document_id
    assert payload["job_id"].startswith("job_")
    assert payload["status"] == "queued"
    assert payload["translation_provider"] == "mock"

    status_response = client.get(f"/api/documents/{document_id}/status")
    assert status_response.status_code == 200
    assert status_response.json()["status"] in {"queued", "processing", "completed"}
    assert status_response.json()["current_step"] in {
        "analysis",
        "extraction",
        "domain_detection",
        "translation",
        "terminology_check",
        "reconstruction",
        "validation_report",
        "done",
    }

    _cleanup_document(document_id)


def test_process_unknown_document_returns_not_found() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/documents/doc_missing/process",
        json={"target_language": "fr", "glossary": []},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_double_process_is_rejected_when_job_is_running() -> None:
    client = TestClient(app)
    document_id = _upload_pdf(client)
    write_status(
        document_id,
        build_status(
            document_id,
            status_value="processing",
            current_step="translation",
            progress=60,
            job_id="job_running",
        ),
    )

    response = client.post(
        f"/api/documents/{document_id}/process",
        json={"target_language": "fr", "glossary": []},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PROCESS_ALREADY_RUNNING"

    _cleanup_document(document_id)


def test_process_existing_over_limit_document_fails_without_intermediate() -> None:
    client = TestClient(app)
    document_id = "doc_legacy_over_limit"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _pdf_with_pages(11))

    response = client.post(
        f"/api/documents/{document_id}/process",
        json={"target_language": "fr", "glossary": []},
    )

    assert response.status_code == 202
    status_response = client.get(f"/api/documents/{document_id}/status")
    assert status_response.status_code == 200
    payload = status_response.json()
    assert payload["status"] == "failed"
    assert payload["error"]["code"] == "PDF_TOO_MANY_PAGES"
    assert not get_intermediate_path(document_id).exists()

    _cleanup_document(document_id)


def test_process_stops_when_llm_rate_limit_is_reached(monkeypatch) -> None:
    from app.services import translation_service

    def raise_rate_limit(_: str) -> None:
        raise AppError(
            code="LLM_RATE_LIMIT_EXCEEDED",
            message="La limite Groq a été atteinte. Réessayez plus tard.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    monkeypatch.setattr(
        translation_service,
        "translate_document_intermediate",
        raise_rate_limit,
    )

    client = TestClient(app)
    document_id = _upload_pdf(client)

    response = client.post(
        f"/api/documents/{document_id}/process",
        json={"target_language": "fr", "glossary": []},
    )

    assert response.status_code == 202
    status_response = client.get(f"/api/documents/{document_id}/status")
    payload = status_response.json()
    assert payload["status"] == "failed"
    assert payload["error"]["code"] == "LLM_RATE_LIMIT_EXCEEDED"
    assert payload["error"]["message"] == (
        "La limite Groq a été atteinte. Réessayez plus tard."
    )

    _cleanup_document(document_id)


def test_process_uses_batch_pipeline_when_enabled(monkeypatch) -> None:
    from app.core import config
    from app.services import batch_service

    settings = config.get_settings()
    monkeypatch.setattr(settings, "enable_batch_mode", True)
    monkeypatch.setattr(config, "get_settings", lambda: settings)

    processed_documents: list[str] = []

    def fake_process_document_in_batches(document_id: str, *, status_callback=None):
        processed_documents.append(document_id)
        if status_callback:
            status_callback("translation", 50)
            status_callback("validation_report", 90)
        return {"document_id": document_id, "pages": []}

    monkeypatch.setattr(
        batch_service,
        "process_document_in_batches",
        fake_process_document_in_batches,
    )

    client = TestClient(app)
    document_id = _upload_pdf(client)

    response = client.post(
        f"/api/documents/{document_id}/process",
        json={"target_language": "fr", "glossary": []},
    )
    status_response = client.get(f"/api/documents/{document_id}/status")

    assert response.status_code == 202
    assert processed_documents == [document_id]
    assert status_response.json()["status"] == "completed"
    assert status_response.json()["progress"] == 100

    _cleanup_document(document_id)
