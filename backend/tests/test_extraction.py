import shutil

import fitz
from fastapi.testclient import TestClient

from app.main import app
from app.services.extraction_service import extract_document_intermediate
from app.services.storage_service import get_intermediate_path, get_storage_root


def _cleanup_document(document_id: str) -> None:
    document_dir = get_storage_root() / document_id
    if document_dir.exists():
        shutil.rmtree(document_dir)


def _sample_pdf_bytes() -> bytes:
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((72, 80), "Service Agreement", fontsize=18)
    page.insert_text(
        (72, 140),
        "This agreement defines the responsibilities of each party.",
        fontsize=11,
    )
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


def test_extract_simple_pdf() -> None:
    client = TestClient(app)
    document_id = _upload_pdf(client)

    intermediate = extract_document_intermediate(document_id)

    assert intermediate.document_id == document_id
    assert intermediate.metadata.page_count == 1
    assert intermediate.pages[0].page_number == 1
    assert len(intermediate.pages[0].blocks) >= 2
    assert intermediate.pages[0].blocks[0].type == "title"
    assert intermediate.pages[0].blocks[0].translated_text == ""
    assert intermediate.pages[0].blocks[0].status == "pending"

    _cleanup_document(document_id)


def test_intermediate_json_is_created_after_process() -> None:
    client = TestClient(app)
    document_id = _upload_pdf(client)

    response = client.post(
        f"/api/documents/{document_id}/process",
        json={"target_language": "fr", "glossary": []},
    )

    assert response.status_code == 202
    assert get_intermediate_path(document_id).is_file()

    status_response = client.get(f"/api/documents/{document_id}/status")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "completed"
    assert status_response.json()["current_step"] == "done"
    assert status_response.json()["progress"] == 100

    _cleanup_document(document_id)


def test_intermediate_endpoint_returns_json() -> None:
    client = TestClient(app)
    document_id = _upload_pdf(client)
    extract_document_intermediate(document_id)

    response = client.get(f"/api/documents/{document_id}/intermediate")

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_id"] == document_id
    assert payload["pages"][0]["page_number"] == 1
    assert payload["pages"][0]["blocks"][0]["source_text"] == "Service Agreement"

    _cleanup_document(document_id)


def test_intermediate_unknown_document_returns_not_found() -> None:
    client = TestClient(app)

    response = client.get("/api/documents/doc_missing/intermediate")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"
