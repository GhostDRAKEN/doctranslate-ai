import shutil

import fitz
from fastapi.testclient import TestClient

from app.main import app
from app.services.storage_service import get_storage_root


def _cleanup_document(document_id: str) -> None:
    document_dir = get_storage_root() / document_id
    if document_dir.exists():
        shutil.rmtree(document_dir)


def _pdf_with_text(page_count: int = 1) -> bytes:
    pdf = fitz.open()
    for index in range(page_count):
        page = pdf.new_page()
        page.insert_text((72, 72), f"Sample page {index + 1}", fontsize=12)
    content = pdf.tobytes()
    pdf.close()
    return content


def _pdf_without_text() -> bytes:
    pdf = fitz.open()
    pdf.new_page()
    content = pdf.tobytes()
    pdf.close()
    return content


def _document_dirs() -> set[str]:
    storage_root = get_storage_root()
    if not storage_root.exists():
        return set()
    return {
        path.name
        for path in storage_root.iterdir()
        if path.is_dir() and path.name.startswith("doc_")
    }


def test_upload_valid_pdf() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/documents/upload",
        files={
            "file": (
                "sample.pdf",
                _pdf_with_text(),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["document_id"].startswith("doc_")
    assert payload["filename"] == "sample.pdf"
    assert payload["status"] == "uploaded"

    source_path = get_storage_root() / payload["document_id"] / "source.pdf"
    assert source_path.exists()
    assert source_path.read_bytes().startswith(b"%PDF")

    _cleanup_document(payload["document_id"])


def test_upload_rejects_wrong_file_type() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/documents/upload",
        files={
            "file": (
                "sample.txt",
                b"not a pdf",
                "text/plain",
            )
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "INVALID_FILE_TYPE",
            "message": "Le fichier doit etre un PDF.",
            "details": None,
        }
    }


def test_upload_rejects_file_above_size_limit() -> None:
    client = TestClient(app)
    oversized_pdf = b"%PDF" + (b"x" * ((10 * 1024 * 1024) + 1))

    response = client.post(
        "/api/documents/upload",
        files={
            "file": (
                "large.pdf",
                oversized_pdf,
                "application/pdf",
            )
        },
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_upload_rejects_pdf_above_page_limit_without_creating_document() -> None:
    client = TestClient(app)
    before_dirs = _document_dirs()

    response = client.post(
        "/api/documents/upload",
        files={
            "file": (
                "too-many-pages.pdf",
                _pdf_with_text(page_count=11),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PDF_TOO_MANY_PAGES"
    assert _document_dirs() == before_dirs


def test_upload_rejects_pdf_without_selectable_text() -> None:
    client = TestClient(app)
    before_dirs = _document_dirs()

    response = client.post(
        "/api/documents/upload",
        files={
            "file": (
                "scan-like.pdf",
                _pdf_without_text(),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PDF_NO_SELECTABLE_TEXT"
    assert _document_dirs() == before_dirs
