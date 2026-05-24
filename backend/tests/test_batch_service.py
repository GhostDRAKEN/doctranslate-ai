import json
import shutil

import fitz
import pytest

from app.core.errors import AppError
from app.services.batch_service import build_page_batches
from app.services.batch_service import initialize_batch_manifests
from app.services.batch_service import resume_incomplete_batches
from app.services.batch_service import write_batch_manifest
from app.services.mock_translation_provider import MockTranslationProvider
from app.services.storage_service import (
    get_batches_directory,
    get_intermediate_path,
    get_storage_root,
    save_source_pdf,
)
from app.services.translation_service import TranslationService


def _cleanup_document(document_id: str) -> None:
    document_dir = get_storage_root() / document_id
    if document_dir.exists():
        shutil.rmtree(document_dir)


def _sample_pdf_bytes() -> bytes:
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Batch sample", fontsize=12)
    content = pdf.tobytes()
    pdf.close()
    return content


def _intermediate_payload(document_id: str) -> dict:
    pages = []
    for page_number in range(1, 4):
        pages.append(
            {
                "page_number": page_number,
                "width": 595,
                "height": 842,
                "blocks": [
                    {
                        "id": f"block_{page_number:03d}",
                        "page_number": page_number,
                        "type": "paragraph",
                        "source_text": f"Paragraph on page {page_number}.",
                        "translated_text": "",
                        "bbox": [72, 100, 300, 130],
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
        )

    return {
        "document_id": document_id,
        "source_language": "en",
        "target_language": "fr",
        "domain": "general",
        "metadata": {
            "filename": "source.pdf",
            "page_count": 3,
            "file_size_mb": 0.01,
            "created_at": "2026-05-22T10:00:00Z",
        },
        "mvp_limits": {
            "max_pages": 10,
            "max_file_size_mb": 10,
            "digital_pdf_only": True,
            "requires_selectable_text": True,
        },
        "glossary": [],
        "pages": pages,
        "warnings": [],
    }


def test_build_page_batches_splits_ranges() -> None:
    batches = build_page_batches(total_pages=12, batch_size=5)

    assert [(batch.page_start, batch.page_end) for batch in batches] == [
        (1, 5),
        (6, 10),
        (11, 12),
    ]
    assert [batch.batch_id for batch in batches] == [
        "batch_001",
        "batch_002",
        "batch_003",
    ]


def test_translation_writes_batch_manifests(monkeypatch) -> None:
    from app.services import translation_service

    document_id = "doc_batch_manifest"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _sample_pdf_bytes())
    get_intermediate_path(document_id).write_text(
        json.dumps(_intermediate_payload(document_id)),
        encoding="utf-8",
    )
    settings = translation_service.get_settings()
    monkeypatch.setattr(settings, "batch_size_pages", 2)
    monkeypatch.setattr(translation_service, "get_settings", lambda: settings)

    TranslationService(provider=MockTranslationProvider()).translate_document(document_id)

    batches_dir = get_batches_directory(document_id)
    first_batch = json.loads((batches_dir / "batch_001.json").read_text())
    second_batch = json.loads((batches_dir / "batch_002.json").read_text())

    assert first_batch["page_start"] == 1
    assert first_batch["page_end"] == 2
    assert first_batch["blocks_count"] == 2
    assert first_batch["translated_blocks_count"] == 2
    assert first_batch["status"] == "completed"
    assert second_batch["page_start"] == 3
    assert second_batch["page_end"] == 3

    _cleanup_document(document_id)


def test_initialize_batch_manifests_creates_pending_files() -> None:
    document_id = "doc_batch_init"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _sample_pdf_bytes())
    payload = _intermediate_payload(document_id)

    manifests = initialize_batch_manifests(document_id, payload, batch_size=2)

    batches_dir = get_batches_directory(document_id)
    assert len(manifests) == 2
    assert (batches_dir / "batch_001.json").is_file()
    assert (batches_dir / "batch_002.json").is_file()
    assert manifests[0]["status"] == "pending"
    assert manifests[0]["error"] is None

    _cleanup_document(document_id)


def test_resume_skips_completed_batch(monkeypatch) -> None:
    from app.services import batch_service

    document_id = "doc_batch_skip_completed"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _sample_pdf_bytes())
    get_intermediate_path(document_id).write_text(
        json.dumps(_intermediate_payload(document_id)),
        encoding="utf-8",
    )
    initialize_batch_manifests(document_id, _intermediate_payload(document_id), 1)
    write_batch_manifest(
        document_id,
        {
            "batch_id": "batch_001",
            "page_start": 1,
            "page_end": 1,
            "status": "completed",
            "blocks_count": 1,
            "translated_blocks_count": 1,
            "warnings": [],
            "error": None,
        },
    )
    processed_ranges: list[tuple[int, int]] = []
    settings = batch_service.get_settings()
    monkeypatch.setattr(settings, "batch_size_pages", 1)
    monkeypatch.setattr(batch_service, "get_settings", lambda: settings)

    def fake_translate(_: dict, page_start: int, page_end: int) -> int:
        processed_ranges.append((page_start, page_end))
        return 1

    monkeypatch.setattr(batch_service, "translate_batch_payload", fake_translate)

    resume_incomplete_batches(document_id)

    assert processed_ranges == [(2, 2), (3, 3)]

    _cleanup_document(document_id)


def test_resume_retries_failed_batch(monkeypatch) -> None:
    from app.services import batch_service

    document_id = "doc_batch_retry_failed"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _sample_pdf_bytes())
    payload = _intermediate_payload(document_id)
    get_intermediate_path(document_id).write_text(json.dumps(payload), encoding="utf-8")
    initialize_batch_manifests(document_id, payload, 2)
    write_batch_manifest(
        document_id,
        {
            "batch_id": "batch_001",
            "page_start": 1,
            "page_end": 2,
            "status": "failed",
            "blocks_count": 2,
            "translated_blocks_count": 0,
            "warnings": [],
            "error": {"code": "TRANSLATION_FAILED", "message": "failed once"},
        },
    )
    processed_ranges: list[tuple[int, int]] = []

    def fake_translate(_: dict, page_start: int, page_end: int) -> int:
        processed_ranges.append((page_start, page_end))
        return page_end - page_start + 1

    monkeypatch.setattr(batch_service, "translate_batch_payload", fake_translate)

    resume_incomplete_batches(document_id)
    batch = json.loads(
        (get_batches_directory(document_id) / "batch_001.json").read_text()
    )

    assert processed_ranges[0] == (1, 2)
    assert batch["status"] == "completed"
    assert batch["error"] is None

    _cleanup_document(document_id)


def test_rate_limit_stops_current_batch(monkeypatch) -> None:
    from app.services import batch_service

    document_id = "doc_batch_rate_limit"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _sample_pdf_bytes())
    payload = _intermediate_payload(document_id)
    get_intermediate_path(document_id).write_text(json.dumps(payload), encoding="utf-8")
    initialize_batch_manifests(document_id, payload, 1)
    settings = batch_service.get_settings()
    monkeypatch.setattr(settings, "batch_size_pages", 1)
    monkeypatch.setattr(batch_service, "get_settings", lambda: settings)

    def raise_rate_limit(_: dict, page_start: int, page_end: int) -> int:
        raise AppError(
            code="LLM_RATE_LIMIT_EXCEEDED",
            message="La limite Groq a été atteinte. Réessayez plus tard.",
        )

    monkeypatch.setattr(batch_service, "translate_batch_payload", raise_rate_limit)

    with pytest.raises(AppError) as exc_info:
        resume_incomplete_batches(document_id)

    batch = json.loads(
        (get_batches_directory(document_id) / "batch_001.json").read_text()
    )
    second_batch = json.loads(
        (get_batches_directory(document_id) / "batch_002.json").read_text()
    )

    assert exc_info.value.code == "LLM_RATE_LIMIT_EXCEEDED"
    assert batch["status"] == "failed"
    assert batch["error"]["code"] == "LLM_RATE_LIMIT_EXCEEDED"
    assert second_batch["status"] == "pending"

    _cleanup_document(document_id)


def test_resume_generates_final_intermediate_after_all_batches(monkeypatch) -> None:
    from app.services import batch_service

    document_id = "doc_batch_final"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _sample_pdf_bytes())
    payload = _intermediate_payload(document_id)
    get_intermediate_path(document_id).write_text(json.dumps(payload), encoding="utf-8")

    def fake_translate(payload: dict, page_start: int, page_end: int) -> int:
        count = 0
        for page in payload["pages"]:
            if page_start <= page["page_number"] <= page_end:
                for block in page["blocks"]:
                    block["translated_text"] = f"[FR MOCK] {block['source_text']}"
                    block["status"] = "translated"
                    count += 1
        return count

    monkeypatch.setattr(batch_service, "translate_batch_payload", fake_translate)

    resume_incomplete_batches(document_id)
    final_payload = json.loads(get_intermediate_path(document_id).read_text())
    batches = [
        json.loads(path.read_text())
        for path in sorted(get_batches_directory(document_id).glob("batch_*.json"))
    ]

    assert all(batch["status"] == "completed" for batch in batches)
    assert all(
        block["status"] == "translated"
        for page in final_payload["pages"]
        for block in page["blocks"]
    )
    assert "document_quality" in final_payload

    _cleanup_document(document_id)
