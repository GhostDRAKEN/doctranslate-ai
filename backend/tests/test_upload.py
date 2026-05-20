import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.storage_service import get_storage_root


def _cleanup_document(document_id: str) -> None:
    document_dir = get_storage_root() / document_id
    if document_dir.exists():
        shutil.rmtree(document_dir)


def test_upload_valid_pdf() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/documents/upload",
        files={
            "file": (
                "sample.pdf",
                b"%PDF-1.4\n% minimal test pdf",
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
