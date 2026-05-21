import json
import shutil

import fitz
import pytest
from fastapi.testclient import TestClient

from app.core.errors import AppError
from app.main import app
from app.services.mock_translation_provider import MockTranslationProvider
from app.services.storage_service import (
    get_intermediate_path,
    get_storage_root,
    save_source_pdf,
)
from app.services.translation_service import (
    TranslationService,
    translate_document_intermediate,
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


def _intermediate_payload(document_id: str) -> dict:
    return {
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
                        "type": "title",
                        "source_text": "Service Agreement",
                        "translated_text": "",
                        "bbox": [72, 60, 230, 85],
                        "style": {
                            "font": "Helvetica",
                            "size": 18,
                            "bold": False,
                            "italic": False,
                            "color": "#000000",
                            "alignment": "left",
                        },
                        "reading_order": 1,
                        "status": "pending",
                        "warnings": [],
                    },
                    {
                        "id": "block_002",
                        "page_number": 1,
                        "type": "paragraph",
                        "source_text": "This agreement defines responsibilities.",
                        "translated_text": "",
                        "bbox": [72, 110, 400, 140],
                        "style": {
                            "font": "Helvetica",
                            "size": 11,
                            "bold": False,
                            "italic": False,
                            "color": "#000000",
                            "alignment": "left",
                        },
                        "reading_order": 2,
                        "status": "pending",
                        "warnings": [],
                    },
                    {
                        "id": "block_003",
                        "page_number": 1,
                        "type": "table",
                        "source_text": "",
                        "translated_text": "",
                        "bbox": [72, 160, 400, 230],
                        "style": {
                            "font": "Helvetica",
                            "size": 10,
                            "bold": False,
                            "italic": False,
                            "color": "#000000",
                            "alignment": "left",
                        },
                        "reading_order": 3,
                        "status": "pending",
                        "warnings": [],
                        "rows": [
                            {
                                "cells": [
                                    {
                                        "row": 0,
                                        "column": 0,
                                        "source_text": "Term",
                                        "translated_text": "",
                                    }
                                ]
                            }
                        ],
                    },
                    {
                        "id": "block_004",
                        "page_number": 1,
                        "type": "image",
                        "source_text": "",
                        "translated_text": "",
                        "bbox": [72, 260, 200, 360],
                        "style": {
                            "font": None,
                            "size": None,
                            "bold": False,
                            "italic": False,
                            "color": None,
                            "alignment": "center",
                        },
                        "reading_order": 4,
                        "status": "pending",
                        "warnings": [],
                        "has_possible_text": True,
                    },
                ],
            }
        ],
        "warnings": [],
    }


def _write_intermediate(document_id: str, payload: dict) -> None:
    save_source_pdf(document_id, _sample_pdf_bytes())
    get_intermediate_path(document_id).write_text(
        json.dumps(payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def test_mock_translation_provider_translates_text_block() -> None:
    provider = MockTranslationProvider()
    block = {
        "type": "paragraph",
        "source_text": "Original text",
        "translated_text": "",
        "status": "pending",
        "warnings": [],
    }

    translated = provider.translate_block(block)

    assert translated is True
    assert block["translated_text"] == "[FR MOCK] Original text"
    assert block["status"] == "translated"


def test_translation_service_marks_unknown_text_block_for_review() -> None:
    document_id = "doc_translation_unknown_fragment"
    _cleanup_document(document_id)
    payload = _intermediate_payload(document_id)
    payload["pages"][0]["blocks"] = [
        {
            "id": "block_001",
            "page_number": 1,
            "type": "unknown",
            "source_text": "Who",
            "translated_text": "",
            "bbox": [72, 110, 100, 130],
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
    ]
    _write_intermediate(document_id, payload)

    intermediate = TranslationService(
        provider=MockTranslationProvider(),
    ).translate_document(document_id)
    block = intermediate.pages[0].blocks[0]

    assert block.translated_text == ""
    assert block.status == "needs_review"
    assert "unsupported_text_fragment" in block.warnings

    _cleanup_document(document_id)


def test_mock_translation_provider_does_not_translate_unknown_text_block() -> None:
    provider = MockTranslationProvider()
    block = {
        "type": "unknown",
        "source_text": "Short textual fragment",
        "translated_text": "",
        "status": "pending",
        "warnings": [],
    }

    translated = provider.translate_block(block)

    assert translated is False
    assert block["translated_text"] == ""
    assert block["status"] == "pending"


def test_translation_service_translates_supported_blocks_only() -> None:
    document_id = "doc_translation_multiple"
    _cleanup_document(document_id)
    _write_intermediate(document_id, _intermediate_payload(document_id))

    intermediate = TranslationService(
        provider=MockTranslationProvider(),
    ).translate_document(document_id)
    blocks = intermediate.pages[0].blocks

    assert blocks[0].translated_text == "[FR MOCK] Service Agreement"
    assert blocks[1].translated_text == (
        "[FR MOCK] This agreement defines responsibilities."
    )
    assert blocks[2].rows[0]["cells"][0]["translated_text"] == ""

    _cleanup_document(document_id)


def test_translation_preserves_image_block_without_translation() -> None:
    document_id = "doc_translation_image"
    _cleanup_document(document_id)
    _write_intermediate(document_id, _intermediate_payload(document_id))

    intermediate = TranslationService(
        provider=MockTranslationProvider(),
    ).translate_document(document_id)
    image_block = intermediate.pages[0].blocks[3]

    assert image_block.translated_text == ""
    assert image_block.status == "needs_review"
    assert "image_translation_not_supported" in image_block.warnings

    _cleanup_document(document_id)


def test_process_updates_intermediate_json_with_mock_translations(monkeypatch) -> None:
    from app.services import translation_service

    monkeypatch.setattr(
        translation_service,
        "build_translation_provider",
        lambda: MockTranslationProvider(),
    )

    client = TestClient(app)
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
    document_id = response.json()["document_id"]

    process_response = client.post(
        f"/api/documents/{document_id}/process",
        json={"target_language": "fr", "glossary": []},
    )

    assert process_response.status_code == 202
    payload = json.loads(get_intermediate_path(document_id).read_text(encoding="utf-8"))
    first_block = payload["pages"][0]["blocks"][0]
    assert first_block["translated_text"].startswith("[FR MOCK] ")
    assert first_block["status"] == "translated"

    _cleanup_document(document_id)


def test_translate_unknown_document_returns_controlled_error() -> None:
    with pytest.raises(AppError) as exc_info:
        translate_document_intermediate("doc_missing_translation")

    assert exc_info.value.code == "DOCUMENT_NOT_FOUND"
