import base64
import shutil
import json

import fitz
from fastapi.testclient import TestClient

from app.main import app
from app.services import translation_service
from app.services.docx.docx_generator import generate_docx
from app.services.mock_translation_provider import MockTranslationProvider
from app.services import pdf_overlay_service
from app.services.pdf_overlay_service import (
    apply_overlay_operations,
    expand_bbox,
    fit_text_to_box,
    overlay_block,
    prepare_mask_operations,
    prepare_overlay_operations,
    should_mask_source_block,
    should_write_translation,
)
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


def _sample_pdf_with_image_bytes() -> bytes:
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQ"
        "DJ/pLvAAAAAElFTkSuQmCC"
    )
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((72, 80), "Service Agreement", fontsize=18)
    page.insert_image(fitz.Rect(72, 120, 140, 188), stream=png_bytes)
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


def test_pdf_overlay_masks_source_text_before_writing_translation() -> None:
    client = TestClient(app)
    document_id = "doc_pdf_masks_source"
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
                                "type": "title",
                                "source_text": "Service Agreement",
                                "translated_text": "Contrat de service",
                                "bbox": [72, 60, 250, 95],
                                "style": {
                                    "font": "Helvetica",
                                    "size": 18,
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
    with fitz.open(get_pdf_result_path(document_id)) as pdf:
        text = pdf[0].get_text()
    assert "Contrat de service" in text
    assert "Service Agreement" not in text

    _cleanup_document(document_id)


def test_expand_bbox_adds_configurable_padding() -> None:
    rect = fitz.Rect(10, 20, 30, 40)

    expanded = expand_bbox(rect, padding=1.5)

    assert expanded == fitz.Rect(8.5, 18.5, 31.5, 41.5)


def test_pdf_overlay_applies_mask_before_writing_text(monkeypatch) -> None:
    calls = []
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    operations = prepare_overlay_operations(
        page,
        [
            {
                "id": "block_001",
                "type": "paragraph",
                "status": "translated",
                "translated_text": "Premier texte francais",
                "bbox": [72, 100, 250, 130],
                "style": {"size": 11, "alignment": "left"},
                "warnings": [],
            },
            {
                "id": "block_002",
                "type": "paragraph",
                "status": "translated",
                "translated_text": "Second texte francais",
                "bbox": [72, 150, 250, 180],
                "style": {"size": 11, "alignment": "left"},
                "warnings": [],
            },
        ],
    )

    def fake_mask_source_text_zones(page, rects):
        calls.append(("mask", len(rects)))

    def fake_write_overlay_text(page, operation):
        calls.append(("write", operation.block["id"]))
        return False

    monkeypatch.setattr(
        pdf_overlay_service,
        "mask_source_text_zones",
        fake_mask_source_text_zones,
    )
    monkeypatch.setattr(
        pdf_overlay_service,
        "write_overlay_text",
        fake_write_overlay_text,
    )

    apply_overlay_operations(page, operations)
    pdf.close()

    assert calls == [("mask", 2), ("write", "block_001"), ("write", "block_002")]


def test_pdf_overlay_masks_rejected_block_without_writing_translation() -> None:
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((72, 150), "AI has the potential to increase productivity.", fontsize=11)
    block = {
        "id": "block_rejected",
        "type": "paragraph",
        "source_text": "AI has the potential to increase productivity.",
        "translated_text": "Texte suspect Who",
        "status": "needs_review",
        "bbox": [72, 135, 340, 165],
        "style": {"size": 11, "alignment": "left"},
        "warnings": ["english_residual"],
    }

    changed = apply_overlay_operations(
        page,
        prepare_mask_operations(page, [block]),
        prepare_overlay_operations(page, [block]),
    )
    text = page.get_text()
    pdf.close()

    assert changed is True
    assert "AI has the potential" not in text
    assert "Texte suspect Who" in text
    assert "source_masked_translation_rejected" in block["warnings"]
    assert "overlay_written_with_review" in block["warnings"]


def test_pdf_overlay_writes_review_note_when_translation_is_empty() -> None:
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((72, 150), "Pending source text.", fontsize=11)
    block = {
        "id": "block_empty_translation",
        "type": "paragraph",
        "source_text": "Pending source text.",
        "translated_text": "",
        "status": "needs_review",
        "bbox": [72, 135, 260, 165],
        "style": {"size": 11, "alignment": "left"},
        "warnings": ["suspicious_translation"],
    }

    changed = apply_overlay_operations(
        page,
        prepare_mask_operations(page, [block]),
        prepare_overlay_operations(page, [block]),
    )
    text = page.get_text()
    pdf.close()

    assert changed is True
    assert "Pending source text" not in text
    assert "[Traduction à vérifier]" in text
    assert "masked_without_translation" in block["warnings"]


def test_pdf_overlay_writes_translated_block_after_masking() -> None:
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((72, 150), "This agreement defines responsibilities.", fontsize=11)
    block = {
        "id": "block_valid",
        "type": "paragraph",
        "source_text": "This agreement defines responsibilities.",
        "translated_text": "Ce contrat definit les responsabilites.",
        "status": "translated",
        "bbox": [72, 135, 340, 165],
        "style": {"size": 11, "alignment": "left"},
        "warnings": [],
        "semantic_confidence_score": 0.9,
        "semantic_category": "strong_document_block",
    }

    apply_overlay_operations(
        page,
        prepare_mask_operations(page, [block]),
        prepare_overlay_operations(page, [block]),
    )
    text = page.get_text()
    pdf.close()

    assert "This agreement defines" not in text
    assert "Ce contrat definit" in text


def test_pdf_overlay_writes_table_cells() -> None:
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((72, 105), "Name", fontsize=10)
    page.insert_text((180, 105), "Age", fontsize=10)
    page.insert_text((72, 129), "Alice", fontsize=10)
    page.insert_text((180, 129), "30", fontsize=10)
    block = {
        "id": "table_001",
        "type": "table",
        "source_text": "Name Age Alice 30",
        "translated_text": "",
        "status": "translated",
        "bbox": [72, 92, 220, 140],
        "style": {"size": 10, "alignment": "left"},
        "warnings": [],
        "table_structure_confidence": 0.95,
        "columns": [
            {"column_id": "col_001", "x0": 72, "x1": 120},
            {"column_id": "col_002", "x0": 180, "x1": 220},
        ],
        "grid": [
            [
                {
                    "row": 0,
                    "column": 0,
                    "source_text": "Name",
                    "translated_text": "Nom",
                    "bbox": [72, 94, 120, 112],
                },
                {
                    "row": 0,
                    "column": 1,
                    "source_text": "Age",
                    "translated_text": "Age",
                    "bbox": [180, 94, 220, 112],
                },
            ],
            [
                {
                    "row": 1,
                    "column": 0,
                    "source_text": "Alice",
                    "translated_text": "Alice",
                    "bbox": [72, 118, 120, 136],
                },
                {
                    "row": 1,
                    "column": 1,
                    "source_text": "30",
                    "translated_text": "30",
                    "bbox": [180, 118, 220, 136],
                },
            ],
        ],
        "rows": [
            {
                "cells": [
                    {
                        "row": 0,
                        "column": 0,
                        "source_text": "Name",
                        "translated_text": "Nom",
                        "bbox": [72, 94, 120, 112],
                    },
                    {
                        "row": 0,
                        "column": 1,
                        "source_text": "Age",
                        "translated_text": "Age",
                        "bbox": [180, 94, 220, 112],
                    },
                ]
            },
            {
                "cells": [
                    {
                        "row": 1,
                        "column": 0,
                        "source_text": "Alice",
                        "translated_text": "Alice",
                        "bbox": [72, 118, 120, 136],
                    },
                    {
                        "row": 1,
                        "column": 1,
                        "source_text": "30",
                        "translated_text": "30",
                        "bbox": [180, 118, 220, 136],
                    },
                ]
            },
        ],
    }

    apply_overlay_operations(
        page,
        prepare_mask_operations(page, [block]),
        prepare_overlay_operations(page, [block]),
    )
    text = page.get_text()
    pdf.close()

    assert "Name" not in text
    assert "Nom" in text
    assert "Alice" in text


def test_pdf_overlay_writes_all_four_table_columns() -> None:
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    block = {
        "id": "table_004",
        "type": "table",
        "source_text": (
            "Industry Main AI Application Primary Benefit Potential Risk "
            "Transportation Autonomous vehicles Reduced accidents "
            "Consumer manipulation"
        ),
        "translated_text": "",
        "status": "translated",
        "bbox": [72, 92, 552, 152],
        "style": {"size": 10, "alignment": "left"},
        "warnings": [],
        "table_structure_confidence": 0.95,
        "table_grid_confidence": 0.95,
        "columns": [
            {"column_id": "col_001", "x0": 72, "x1": 178},
            {"column_id": "col_002", "x0": 186, "x1": 320},
            {"column_id": "col_003", "x0": 328, "x1": 444},
            {"column_id": "col_004", "x0": 452, "x1": 552},
        ],
        "grid": [],
        "rows": [
            {
                "cells": [
                    {
                        "row": 0,
                        "column": 0,
                        "source_text": "Industry",
                        "translated_text": "Secteur",
                        "bbox": [72, 94, 178, 116],
                    },
                    {
                        "row": 0,
                        "column": 1,
                        "source_text": "Main AI Application",
                        "translated_text": "Application IA",
                        "bbox": [186, 94, 320, 116],
                    },
                    {
                        "row": 0,
                        "column": 2,
                        "source_text": "Primary Benefit",
                        "translated_text": "Benefice principal",
                        "bbox": [328, 94, 444, 116],
                    },
                    {
                        "row": 0,
                        "column": 3,
                        "source_text": "Potential Risk",
                        "translated_text": "Risque potentiel",
                        "bbox": [452, 94, 552, 116],
                    },
                ]
            },
            {
                "cells": [
                    {
                        "row": 1,
                        "column": 0,
                        "source_text": "Transportation",
                        "translated_text": "Transport",
                        "bbox": [72, 122, 178, 146],
                    },
                    {
                        "row": 1,
                        "column": 1,
                        "source_text": "Autonomous vehicles",
                        "translated_text": "Vehicules autonomes",
                        "bbox": [186, 122, 320, 146],
                    },
                    {
                        "row": 1,
                        "column": 2,
                        "source_text": "Reduced accidents",
                        "translated_text": "Accidents reduits",
                        "bbox": [328, 122, 444, 146],
                    },
                    {
                        "row": 1,
                        "column": 3,
                        "source_text": "Consumer manipulation",
                        "translated_text": "Manipulation consommateurs",
                        "bbox": [452, 122, 552, 146],
                    },
                ]
            },
        ],
    }

    operations = prepare_overlay_operations(page, [block])
    texts = [operation.text for operation in operations]
    apply_overlay_operations(
        page,
        prepare_mask_operations(page, [block]),
        operations,
    )
    text = page.get_text()
    pdf.close()

    assert len(operations) == 8
    assert "Accidents reduits" in texts
    assert "Manipulation consommateurs" in texts
    assert "Accidents reduits" in text
    assert "Manipulation" in text
    assert "consommateurs" in text


def test_pdf_overlay_keeps_tiny_table_cell_visible() -> None:
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    block = {
        "id": "table_tiny",
        "type": "table",
        "source_text": "Potential Risk",
        "translated_text": "",
        "status": "translated",
        "bbox": [72, 92, 130, 112],
        "style": {"size": 10, "alignment": "left"},
        "warnings": [],
        "table_structure_confidence": 0.95,
        "table_grid_confidence": 0.95,
        "columns": [{"column_id": "col_001", "x0": 72, "x1": 130}],
        "grid": [],
        "rows": [
            {
                "cells": [
                    {
                        "row": 0,
                        "column": 0,
                        "source_text": "Potential Risk",
                        "translated_text": "Risque potentiel important",
                        "bbox": [72, 94, 130, 108],
                    },
                ]
            }
        ],
    }

    operations = prepare_overlay_operations(page, [block])
    pdf.close()

    assert len(operations) == 1
    assert operations[0].text == "Risque potentiel important"
    assert operations[0].font_size <= 9


def test_pdf_overlay_table_falls_back_when_grid_is_weak() -> None:
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((72, 105), "Name", fontsize=10)
    page.insert_text((180, 105), "Age", fontsize=10)
    block = {
        "id": "table_weak",
        "type": "table",
        "source_text": "Name Age",
        "translated_text": "",
        "status": "translated",
        "bbox": [72, 92, 220, 116],
        "style": {"size": 10, "alignment": "left"},
        "warnings": [],
        "table_structure_confidence": 0.4,
        "columns": [],
        "rows": [
            {
                "cells": [
                    {
                        "row": 0,
                        "column": 0,
                        "source_text": "Name",
                        "translated_text": "Nom",
                        "bbox": [72, 94, 120, 112],
                    },
                    {
                        "row": 0,
                        "column": 1,
                        "source_text": "Age",
                        "translated_text": "Age",
                        "bbox": [180, 94, 220, 112],
                    },
                ]
            }
        ],
    }

    apply_overlay_operations(
        page,
        prepare_mask_operations(page, [block]),
        prepare_overlay_operations(page, [block]),
    )
    text = page.get_text()
    pdf.close()

    assert "Name" not in text
    assert "Nom | Age" in text
    assert "weak_table_grid_detection" in block["warnings"]


def test_overlay_decisions_are_separated_for_english_residual_block() -> None:
    block = {
        "type": "paragraph",
        "source_text": "AI has the potential to increase productivity.",
        "translated_text": "Texte suspect Who",
        "bbox": [72, 135, 340, 165],
        "style": {"size": 11},
        "status": "needs_review",
        "warnings": ["english_residual"],
    }

    assert should_mask_source_block(block) is True
    assert should_write_translation(block) is False


def test_short_introduction_title_remains_writable() -> None:
    block = {
        "type": "title",
        "source_text": "Introduction",
        "translated_text": "Introduction",
        "bbox": [72, 80, 220, 110],
        "style": {"size": 18, "alignment": "left"},
        "status": "translated",
        "warnings": ["probable_fragment"],
        "semantic_confidence_score": 0.25,
        "semantic_category": "probable_fragment",
    }

    assert should_mask_source_block(block) is True
    assert should_write_translation(block) is True


def test_fit_text_to_box_reduces_font_size_for_small_bbox() -> None:
    font_size, overflow = fit_text_to_box(
        "Texte francais beaucoup trop long pour cette petite zone",
        fitz.Rect(72, 140, 105, 148),
        {"style": {"size": 12, "alignment": "left"}},
    )

    assert font_size == 7
    assert overflow is True


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
    assert "overlay_overflow_risk" in warnings
    assert "overlay_text_truncated" in warnings

    _cleanup_document(document_id)


def test_pdf_routes_are_visible_in_openapi_schema() -> None:
    client = TestClient(app)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/documents/{document_id}/generate-pdf" in paths
    assert "/api/documents/{document_id}/download/pdf" in paths


def test_pdf_overlay_skips_noise_and_english_residual_blocks() -> None:
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)

    noise_written = overlay_block(
        page,
        {
            "type": "noise",
            "status": "needs_review",
            "translated_text": "Noise text",
            "bbox": [72, 100, 250, 130],
            "style": {"size": 11, "alignment": "left"},
            "warnings": ["noise_block"],
        },
    )
    residual_written = overlay_block(
        page,
        {
            "type": "paragraph",
            "source_text": "Suspicious source text",
            "status": "needs_review",
            "translated_text": "Texte suspect Who",
            "bbox": [72, 140, 250, 170],
            "style": {"size": 11, "alignment": "left"},
            "warnings": ["english_residual"],
        },
    )
    valid_written = overlay_block(
        page,
        {
            "type": "paragraph",
            "status": "translated",
            "translated_text": "Texte francais valide",
            "bbox": [72, 180, 300, 210],
            "style": {"size": 11, "alignment": "left"},
            "warnings": [],
        },
    )
    text = page.get_text()
    pdf.close()

    assert noise_written is False
    assert residual_written is True
    assert valid_written is False
    assert "Noise text" not in text
    assert "Texte suspect Who" in text
    assert "Texte francais valide" in text


def test_true_noise_is_ignored_without_mask_or_note() -> None:
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((72, 110), "Decorative noise", fontsize=11)
    block = {
        "id": "block_noise",
        "type": "noise",
        "source_text": "Decorative noise",
        "translated_text": "",
        "status": "needs_review",
        "bbox": [72, 95, 240, 125],
        "style": {"size": 11, "alignment": "left"},
        "warnings": ["noise_block"],
    }

    changed = apply_overlay_operations(
        page,
        prepare_mask_operations(page, [block]),
        prepare_overlay_operations(page, [block]),
    )
    text = page.get_text()
    pdf.close()

    assert changed is False
    assert "Decorative noise" in text
    assert "[Traduction à vérifier]" not in text


def test_pdf_overlay_skips_low_quality_blocks() -> None:
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)

    written = overlay_block(
        page,
        {
            "type": "paragraph",
            "source_text": "Low quality source text",
            "status": "translated",
            "translated_text": "Texte de mauvaise qualite",
            "bbox": [72, 180, 300, 210],
            "style": {"size": 11, "alignment": "left"},
            "warnings": [],
            "quality": {"translation_quality_score": 0.2},
        },
    )
    text = page.get_text()
    pdf.close()

    assert written is True
    assert "Texte de mauvaise qualite" in text


def test_pdf_overlay_skips_semantic_noise_blocks() -> None:
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)

    written = overlay_block(
        page,
        {
            "type": "paragraph",
            "source_text": "AI",
            "status": "translated",
            "translated_text": "IA",
            "bbox": [72, 180, 100, 195],
            "style": {"size": 11, "alignment": "left"},
            "warnings": ["semantic_noise"],
            "semantic_confidence_score": 0.2,
            "semantic_category": "semantic_noise",
        },
    )
    text = page.get_text()
    pdf.close()

    assert written is True
    assert "IA" in text


def test_pdf_overlay_debug_mode_draws_red_bbox(monkeypatch) -> None:
    class DebugSettings:
        debug_overlay = True
        debug_overlay_bbox = True
        overlay_bbox_padding = 1.5

    monkeypatch.setattr(
        pdf_overlay_service,
        "get_settings",
        lambda: DebugSettings(),
    )
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)

    overlay_block(
        page,
        {
            "type": "paragraph",
            "source_text": "Valid source text",
            "status": "translated",
            "translated_text": "Texte francais valide",
            "bbox": [72, 180, 300, 210],
            "style": {"size": 11, "alignment": "left"},
            "warnings": [],
        },
    )
    drawings = page.get_drawings()
    pdf.close()

    assert any(
        tuple(round(value, 2) for value in drawing.get("color", ())) == (1.0, 0.0, 0.0)
        for drawing in drawings
    )


def test_pdf_overlay_debug_semantic_writes_score(monkeypatch) -> None:
    class DebugSettings:
        debug_overlay = False
        debug_overlay_bbox = False
        debug_semantic = True
        overlay_bbox_padding = 1.5
        min_semantic_confidence_overlay = 0.45

    monkeypatch.setattr(
        pdf_overlay_service,
        "get_settings",
        lambda: DebugSettings(),
    )
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)

    overlay_block(
        page,
        {
            "type": "paragraph",
            "status": "translated",
            "translated_text": "Texte francais valide",
            "bbox": [72, 180, 300, 210],
            "style": {"size": 11, "alignment": "left"},
            "warnings": [],
            "semantic_confidence_score": 0.88,
            "semantic_category": "strong_document_block",
        },
    )
    text = page.get_text()
    pdf.close()

    assert "0.88 strong_document_block" in text


def test_pdf_overlay_preserves_source_images() -> None:
    client = TestClient(app)
    document_id = "doc_pdf_preserves_images"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _sample_pdf_with_image_bytes())
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
                                "type": "title",
                                "source_text": "Service Agreement",
                                "translated_text": "Contrat de service",
                                "bbox": [72, 60, 250, 95],
                                "style": {"font": "Helvetica", "size": 18},
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
    with fitz.open(get_pdf_result_path(document_id)) as pdf:
        assert len(pdf[0].get_images(full=True)) >= 1

    _cleanup_document(document_id)
