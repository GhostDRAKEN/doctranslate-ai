import shutil
import json

import fitz
from fastapi.testclient import TestClient

from app.main import app
from app.services import translation_service
from app.services.docx.docx_generator import generate_docx
from app.services.mock_translation_provider import MockTranslationProvider
from app.services.storage_service import (
    get_docx_result_path,
    get_intermediate_path,
    get_pdf_result_path,
    get_storage_root,
    save_source_pdf,
)


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


def _processed_document_id(client: TestClient) -> str:
    translation_service.build_translation_provider = lambda: MockTranslationProvider()
    upload_response = client.post(
        "/api/documents/upload",
        files={
            "file": (
                "sample.pdf",
                _sample_pdf_bytes(),
                "application/pdf",
            )
        },
    )
    assert upload_response.status_code == 201
    document_id = str(upload_response.json()["document_id"])

    process_response = client.post(
        f"/api/documents/{document_id}/process",
        json={"target_language": "fr", "glossary": []},
    )
    assert process_response.status_code == 202
    assert get_intermediate_path(document_id).is_file()
    return document_id


def test_generate_pdf_overlay_from_processed_document() -> None:
    client = TestClient(app)
    document_id = _processed_document_id(client)

    response = client.post(f"/api/documents/{document_id}/generate-pdf")

    assert response.status_code == 200
    assert response.json() == {
        "document_id": document_id,
        "status": "pdf_generated",
        "download_url": f"/api/documents/{document_id}/download/pdf",
    }
    assert get_pdf_result_path(document_id).is_file()

    _cleanup_document(document_id)


def test_download_pdf_returns_file() -> None:
    client = TestClient(app)
    document_id = _processed_document_id(client)
    generate_response = client.post(f"/api/documents/{document_id}/generate-pdf")
    assert generate_response.status_code == 200

    response = client.get(f"/api/documents/{document_id}/download/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "translated_document.pdf" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")

    _cleanup_document(document_id)


def test_download_pdf_missing_file_returns_not_found() -> None:
    client = TestClient(app)
    document_id = "doc_pdf_missing_file"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _sample_pdf_bytes())

    response = client.get(f"/api/documents/{document_id}/download/pdf")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PDF_NOT_FOUND"
    assert response.json()["error"]["message"] == "Le PDF genere est introuvable."

    _cleanup_document(document_id)


def test_generate_pdf_unknown_document_returns_not_found() -> None:
    client = TestClient(app)

    response = client.post("/api/documents/doc_missing/generate-pdf")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_generate_pdf_without_intermediate_returns_result_not_ready() -> None:
    client = TestClient(app)
    document_id = "doc_pdf_not_ready"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _sample_pdf_bytes())

    response = client.post(f"/api/documents/{document_id}/generate-pdf")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RESULT_NOT_READY"
    assert not get_pdf_result_path(document_id).exists()

    _cleanup_document(document_id)


def test_generate_pdf_refuses_when_translation_is_not_ready() -> None:
    client = TestClient(app)
    document_id = "doc_pdf_translation_not_ready"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _sample_pdf_bytes())
    get_intermediate_path(document_id).write_text(
        json.dumps(
            {
                "document_id": document_id,
                "source_language": "en",
                "target_language": "fr",
                "domain": "general",
                "metadata": {
                    "filename": "source.pdf",
                    "page_count": 1,
                    "file_size_mb": 0.01,
                    "created_at": "2026-05-20T10:00:00Z",
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
                        "blocks": [
                            {
                                "id": "block_001",
                                "page_number": 1,
                                "type": "paragraph",
                                "source_text": "This agreement defines responsibilities.",
                                "translated_text": "",
                                "bbox": [72, 140, 300, 160],
                                "style": {
                                    "font": "Helvetica",
                                    "size": 11,
                                    "bold": False,
                                    "italic": False,
                                    "color": "#000000",
                                    "alignment": "left",
                                },
                                "reading_order": 1,
                                "status": "pending",
                                "warnings": [],
                            }
                        ],
                    }
                ],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )

    response = client.post(f"/api/documents/{document_id}/generate-pdf")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TRANSLATION_NOT_READY"
    assert not get_pdf_result_path(document_id).exists()

    _cleanup_document(document_id)


def test_generate_pdf_refuses_incomplete_translation() -> None:
    client = TestClient(app)
    document_id = "doc_pdf_translation_incomplete"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _sample_pdf_bytes())
    payload = {
        "document_id": document_id,
        "source_language": "en",
        "target_language": "fr",
        "domain": "general",
        "metadata": {
            "filename": "source.pdf",
            "page_count": 1,
            "file_size_mb": 0.01,
            "created_at": "2026-05-20T10:00:00Z",
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
                "blocks": [
                    {
                        "id": "block_001",
                        "page_number": 1,
                        "type": "paragraph",
                        "source_text": "Main content",
                        "translated_text": "Contenu principal",
                        "bbox": [72, 140, 300, 160],
                        "style": {"font": "Helvetica", "size": 11},
                        "reading_order": 1,
                        "status": "translated",
                        "warnings": [],
                    },
                    {
                        "id": "block_002",
                        "page_number": 1,
                        "type": "paragraph",
                        "source_text": "Second content",
                        "translated_text": "",
                        "bbox": [72, 180, 300, 200],
                        "style": {"font": "Helvetica", "size": 11},
                        "reading_order": 2,
                        "status": "pending",
                        "warnings": [],
                    },
                ],
            }
        ],
        "warnings": [],
    }
    get_intermediate_path(document_id).write_text(json.dumps(payload), encoding="utf-8")

    response = client.post(f"/api/documents/{document_id}/generate-pdf")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TRANSLATION_INCOMPLETE"
    assert not get_pdf_result_path(document_id).exists()

    _cleanup_document(document_id)


def test_docx_generation_still_works_after_pdf_overlay() -> None:
    client = TestClient(app)
    document_id = _processed_document_id(client)
    pdf_response = client.post(f"/api/documents/{document_id}/generate-pdf")
    assert pdf_response.status_code == 200

    docx_path = generate_docx(document_id)

    assert docx_path == get_docx_result_path(document_id)
    assert docx_path.is_file()

    _cleanup_document(document_id)


def test_generate_pdf_marks_overflow_risk_in_intermediate() -> None:
    client = TestClient(app)
    document_id = "doc_pdf_overflow"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _sample_pdf_bytes())
    get_intermediate_path(document_id).write_text(
        json.dumps(
            {
                "document_id": document_id,
                "source_language": "en",
                "target_language": "fr",
                "domain": "general",
                "metadata": {
                    "filename": "source.pdf",
                    "page_count": 1,
                    "file_size_mb": 0.01,
                    "created_at": "2026-05-20T10:00:00Z",
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
                        "blocks": [
                            {
                                "id": "block_001",
                                "page_number": 1,
                                "type": "paragraph",
                                "source_text": "Short text",
                                "translated_text": (
                                    "Texte francais beaucoup trop long pour rentrer "
                                    "dans une zone aussi petite du document traduit."
                                ),
                                "bbox": [72, 140, 110, 150],
                                "style": {
                                    "font": "Helvetica",
                                    "size": 11,
                                    "bold": False,
                                    "italic": False,
                                    "color": "#000000",
                                    "alignment": "left",
                                },
                                "reading_order": 1,
                                "status": "translated",
                                "warnings": [],
                            }
                        ],
                    }
                ],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )

    response = client.post(f"/api/documents/{document_id}/generate-pdf")

    assert response.status_code == 200
    payload = json.loads(get_intermediate_path(document_id).read_text(encoding="utf-8"))
    warnings = payload["pages"][0]["blocks"][0]["warnings"]
    assert "overflow_risk" in warnings

    _cleanup_document(document_id)


def test_pdf_routes_are_visible_in_openapi_schema() -> None:
    client = TestClient(app)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/documents/{document_id}/generate-pdf" in paths
    assert "/api/documents/{document_id}/download/pdf" in paths
