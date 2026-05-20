"""Temporary local storage service."""

from pathlib import Path

from app.core.config import get_settings


def get_storage_root() -> Path:
    """Return the configured temporary storage root."""

    return Path(get_settings().storage_tmp_dir)


def create_document_directory(document_id: str) -> Path:
    """Create and return the temporary directory for a document."""

    document_dir = get_storage_root() / document_id
    document_dir.mkdir(parents=True, exist_ok=False)
    return document_dir


def save_source_pdf(document_id: str, content: bytes) -> Path:
    """Save uploaded PDF bytes as source.pdf for the document."""

    document_dir = create_document_directory(document_id)
    source_path = document_dir / "source.pdf"
    source_path.write_bytes(content)
    return source_path
