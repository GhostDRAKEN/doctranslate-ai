import json
import shutil

import fitz
import pytest

from app.core.errors import AppError
from app.services.batch_service import build_page_batches
from app.services.batch_service import initialize_batch_manifests
from app.services.batch_service import process_document_in_batches
from app.services.batch_service import resume_incomplete_batches
from app.services.batch_service import write_batch_manifest
from app.services.pdf_overlay_service import generate_pdf_overlay
from app.services.mock_translation_provider import MockTranslationProvider
from app.services.storage_service import (
    get_batches_directory,
    get_intermediate_path,
    get_pdf_result_path,
    get_storage_root,
    save_source_pdf,
)
from app.services.translation_service import TranslationService


class ParagraphResidualProvider:
    provider_name = "llm"

    def translate_block(self, block: dict) -> bool:
        block["translated_text"] = (
            "Les impacts environnementaux sont importants. Scientists Climate"
        )
        block["status"] = "translated"
        return True


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


def _pdf_with_pages(page_count: int) -> bytes:
    pdf = fitz.open()
    for page_number in range(1, page_count + 1):
        page = pdf.new_page()
        page.insert_text(
            (72, 150),
            f"This batch page {page_number} contains text for translation.",
            fontsize=11,
        )
    content = pdf.tobytes()
    pdf.close()
    return content


def _pdf_with_paragraph_residual_source() -> bytes:
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text(
        (72, 150),
        "Scientists explain how climate affects local communities.",
        fontsize=11,
    )
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
    assert manifests[0]["document_id"] == document_id
    assert manifests[0]["created_at"]
    assert manifests[0]["updated_at"]

    _cleanup_document(document_id)


def test_process_document_in_batches_creates_final_intermediate(monkeypatch) -> None:
    from app.services import batch_service

    document_id = "doc_batch_real_pipeline"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _pdf_with_pages(3))
    settings = batch_service.get_settings()
    monkeypatch.setattr(settings, "batch_size_pages", 2)
    monkeypatch.setattr(settings, "enable_batch_mode", True)
    monkeypatch.setattr(batch_service, "get_settings", lambda: settings)
    monkeypatch.setattr(
        batch_service,
        "build_batch_translation_service",
        lambda: TranslationService(provider=MockTranslationProvider()),
    )
    status_events: list[tuple[str, int]] = []

    payload = process_document_in_batches(
        document_id,
        status_callback=lambda step, progress: status_events.append((step, progress)),
    )

    batches_dir = get_batches_directory(document_id)
    first_batch = json.loads((batches_dir / "batch_001.json").read_text())
    second_batch = json.loads((batches_dir / "batch_002.json").read_text())
    final_payload = json.loads(get_intermediate_path(document_id).read_text())

    assert first_batch["document_id"] == document_id
    assert first_batch["status"] == "completed"
    assert first_batch["page_start"] == 1
    assert first_batch["page_end"] == 2
    assert first_batch["created_at"]
    assert first_batch["updated_at"]
    assert second_batch["page_start"] == 3
    assert final_payload["batch_summary"] == {
        "enabled": True,
        "batch_size_pages": 2,
        "total_batches": 2,
        "completed_batches": 2,
        "failed_batches": 0,
    }
    assert payload["batch_summary"] == final_payload["batch_summary"]
    assert len(final_payload["pages"]) == 3
    assert all(
        block["status"] == "translated"
        for page in final_payload["pages"]
        for block in page["blocks"]
    )
    assert status_events[0] == ("analysis", 10)
    assert status_events[-1] == ("validation_report", 90)

    _cleanup_document(document_id)


def test_process_document_in_batches_skips_completed_batch(monkeypatch) -> None:
    from app.services import batch_service

    document_id = "doc_batch_process_skip_completed"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _pdf_with_pages(2))
    settings = batch_service.get_settings()
    monkeypatch.setattr(settings, "batch_size_pages", 1)
    monkeypatch.setattr(batch_service, "get_settings", lambda: settings)
    write_batch_manifest(
        document_id,
        {
            "batch_id": "batch_001",
            "document_id": document_id,
            "page_start": 1,
            "page_end": 1,
            "status": "completed",
            "blocks_count": 1,
            "translated_blocks_count": 1,
            "warnings": [],
            "error": None,
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
                            "source_text": "Completed page",
                            "translated_text": "Page terminee",
                            "bbox": [72, 60, 180, 90],
                            "style": {"font": "Helvetica", "size": 12},
                            "reading_order": 1,
                            "status": "translated",
                            "warnings": [],
                        }
                    ],
                }
            ],
        },
    )
    processed_batches: list[str] = []

    def fake_extract_and_translate(_: str, batch) -> dict:
        processed_batches.append(batch.batch_id)
        return {
            **_intermediate_payload(document_id),
            "pages": [
                {
                    "page_number": 2,
                    "width": 595,
                    "height": 842,
                    "blocks": [
                        {
                            "id": "block_001",
                            "page_number": 2,
                            "type": "paragraph",
                            "source_text": "Pending page",
                            "translated_text": "Page en attente",
                            "bbox": [72, 60, 180, 90],
                            "style": {"font": "Helvetica", "size": 12},
                            "reading_order": 1,
                            "status": "translated",
                            "warnings": [],
                        }
                    ],
                }
            ],
        }

    monkeypatch.setattr(
        batch_service,
        "extract_and_translate_batch",
        fake_extract_and_translate,
    )

    payload = process_document_in_batches(document_id)

    assert processed_batches == ["batch_002"]
    assert [page["page_number"] for page in payload["pages"]] == [1, 2]

    _cleanup_document(document_id)


def test_process_document_in_batches_retries_failed_batch(monkeypatch) -> None:
    from app.services import batch_service

    document_id = "doc_batch_process_retry_failed"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _pdf_with_pages(1))
    settings = batch_service.get_settings()
    monkeypatch.setattr(settings, "batch_size_pages", 1)
    monkeypatch.setattr(batch_service, "get_settings", lambda: settings)
    write_batch_manifest(
        document_id,
        {
            "batch_id": "batch_001",
            "document_id": document_id,
            "page_start": 1,
            "page_end": 1,
            "status": "failed",
            "blocks_count": 1,
            "translated_blocks_count": 0,
            "warnings": [],
            "error": {"code": "TRANSLATION_FAILED", "message": "failed once"},
        },
    )
    processed_batches: list[str] = []

    def fake_extract_and_translate(_: str, batch) -> dict:
        processed_batches.append(batch.batch_id)
        payload = _intermediate_payload(document_id)
        payload["metadata"]["page_count"] = 1
        payload["pages"] = payload["pages"][:1]
        payload["pages"][0]["blocks"][0]["translated_text"] = "[FR MOCK] Page"
        payload["pages"][0]["blocks"][0]["status"] = "translated"
        return payload

    monkeypatch.setattr(
        batch_service,
        "extract_and_translate_batch",
        fake_extract_and_translate,
    )

    process_document_in_batches(document_id)
    batch = json.loads((get_batches_directory(document_id) / "batch_001.json").read_text())

    assert processed_batches == ["batch_001"]
    assert batch["status"] == "completed"
    assert batch["error"] is None

    _cleanup_document(document_id)


def test_process_document_in_batches_rate_limit_stops_next_batches(monkeypatch) -> None:
    from app.services import batch_service

    document_id = "doc_batch_process_rate_limit"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _pdf_with_pages(2))
    settings = batch_service.get_settings()
    monkeypatch.setattr(settings, "batch_size_pages", 1)
    monkeypatch.setattr(batch_service, "get_settings", lambda: settings)

    def raise_rate_limit(_: str, batch) -> dict:
        raise AppError(
            code="LLM_RATE_LIMIT_EXCEEDED",
            message="La limite Groq a ete atteinte. Reessayez plus tard.",
        )

    monkeypatch.setattr(
        batch_service,
        "extract_and_translate_batch",
        raise_rate_limit,
    )

    with pytest.raises(AppError) as exc_info:
        process_document_in_batches(document_id)

    first_batch = json.loads((get_batches_directory(document_id) / "batch_001.json").read_text())
    second_batch = json.loads((get_batches_directory(document_id) / "batch_002.json").read_text())

    assert exc_info.value.code == "LLM_RATE_LIMIT_EXCEEDED"
    assert first_batch["status"] == "failed"
    assert first_batch["error"]["code"] == "LLM_RATE_LIMIT_EXCEEDED"
    assert second_batch["status"] == "pending"

    _cleanup_document(document_id)


def test_generate_pdf_accepts_final_batch_intermediate(monkeypatch) -> None:
    from app.services import batch_service

    document_id = "doc_batch_pdf_compatible"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _pdf_with_pages(1))
    settings = batch_service.get_settings()
    monkeypatch.setattr(settings, "batch_size_pages", 1)
    monkeypatch.setattr(batch_service, "get_settings", lambda: settings)
    monkeypatch.setattr(
        batch_service,
        "build_batch_translation_service",
        lambda: TranslationService(provider=MockTranslationProvider()),
    )

    process_document_in_batches(document_id)
    generate_pdf_overlay(document_id)

    assert get_pdf_result_path(document_id).is_file()

    _cleanup_document(document_id)


def test_batch_pipeline_cleans_paragraph_residuals(monkeypatch) -> None:
    from app.services import batch_service

    document_id = "doc_batch_paragraph_cleanup"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _pdf_with_paragraph_residual_source())
    settings = batch_service.get_settings()
    monkeypatch.setattr(settings, "batch_size_pages", 1)
    monkeypatch.setattr(settings, "mock_translation_enabled", False)
    monkeypatch.setattr(batch_service, "get_settings", lambda: settings)
    monkeypatch.setattr(
        batch_service,
        "build_batch_translation_service",
        lambda: TranslationService(provider=ParagraphResidualProvider()),
    )

    payload = process_document_in_batches(document_id)
    block = payload["pages"][0]["blocks"][0]

    assert block["translated_text"] == "Les impacts environnementaux sont importants."
    assert "paragraph_english_residual_cleaned" in block["warnings"]

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
