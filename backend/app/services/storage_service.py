"""Temporary local storage service."""

from pathlib import Path

from app.core.config import get_settings


def get_storage_root() -> Path:
    """Return the configured temporary storage root."""

    return Path(get_settings().storage_tmp_dir)


def get_document_directory(document_id: str) -> Path:
    """Return the temporary directory path for a document."""

    return get_storage_root() / document_id


def create_document_directory(document_id: str) -> Path:
    """Create and return the temporary directory for a document."""

    document_dir = get_document_directory(document_id)
    document_dir.mkdir(parents=True, exist_ok=False)
    return document_dir


def document_exists(document_id: str) -> bool:
    """Return whether a document has an uploaded source PDF."""

    return (get_document_directory(document_id) / "source.pdf").is_file()


def get_status_path(document_id: str) -> Path:
    """Return the internal status.json path for a document."""

    return get_document_directory(document_id) / "status.json"


def get_source_pdf_path(document_id: str) -> Path:
    """Return the internal source.pdf path for a document."""

    return get_document_directory(document_id) / "source.pdf"


def get_intermediate_path(document_id: str) -> Path:
    """Return the internal intermediate.json path for a document."""

    return get_document_directory(document_id) / "intermediate.json"


def get_docx_result_path(document_id: str) -> Path:
    """Return the internal result.docx path for a document."""

    return get_document_directory(document_id) / "result.docx"


def get_pdf_result_path(document_id: str) -> Path:
    """Return the internal result.pdf path for a document."""

    return get_document_directory(document_id) / "result.pdf"


def get_quality_report_path(document_id: str) -> Path:
    """Return the internal quality_report.json path for a document."""

    return get_document_directory(document_id) / "quality_report.json"


def get_images_directory(document_id: str) -> Path:
    """Return the internal images directory for extracted PDF images."""

    return get_document_directory(document_id) / "images"


def get_batches_directory(document_id: str) -> Path:
    """Return the internal batches directory for future batch processing."""

    return get_document_directory(document_id) / "batches"


def save_source_pdf(document_id: str, content: bytes) -> Path:
    """Save uploaded PDF bytes as source.pdf for the document."""

    document_dir = create_document_directory(document_id)
    source_path = get_source_pdf_path(document_id)
    source_path.write_bytes(content)
    return source_path
