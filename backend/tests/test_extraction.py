import shutil
import json
from base64 import b64decode

import fitz
from fastapi.testclient import TestClient

from app.main import app
from app.services.extraction_service import (
    extract_document_intermediate,
    merge_text_candidates,
)
from app.services.storage_service import (
    get_images_directory,
    get_intermediate_path,
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


def _pdf_with_header_footer() -> bytes:
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((72, 24), "Confidential", fontsize=8)
    page.insert_text((72, 120), "Main content paragraph for extraction.", fontsize=11)
    page.insert_text((72, 820), "Page 1", fontsize=8)
    content = pdf.tobytes()
    pdf.close()
    return content


def _pdf_with_image() -> bytes:
    png_bytes = b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
        "/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((72, 80), "Image example paragraph.", fontsize=11)
    page.insert_image(fitz.Rect(72, 140, 172, 240), stream=png_bytes)
    content = pdf.tobytes()
    pdf.close()
    return content


def _pdf_with_repeating_footer() -> bytes:
    pdf = fitz.open()
    for index in range(2):
        page = pdf.new_page(width=595, height=842)
        page.insert_text((72, 80), f"Section {index + 1}", fontsize=18)
        page.insert_text(
            (72, 140),
            f"This is the main body content for page {index + 1}.",
            fontsize=11,
        )
        page.insert_text((72, 820), "Company Confidential", fontsize=8)
    content = pdf.tobytes()
    pdf.close()
    return content


def _pdf_with_list_items() -> bytes:
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((72, 80), "Project Checklist", fontsize=18)
    page.insert_text((72, 130), "- First requirement", fontsize=11)
    page.insert_text((72, 150), "1. Second requirement", fontsize=11)
    content = pdf.tobytes()
    pdf.close()
    return content


def _pdf_with_fragmented_paragraph_and_artifacts() -> bytes:
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((72, 76), "Implementation Scope", fontsize=18)
    page.insert_text(
        (72, 130),
        "This agreement describes the service scope and delivery",
        fontsize=11,
    )
    page.insert_text(
        (72, 145),
        "requirements for the customer implementation team.",
        fontsize=11,
    )
    page.insert_text(
        (72, 160),
        "It also defines acceptance criteria and reporting duties.",
        fontsize=11,
    )
    page.insert_text((420, 210), "Who What When", fontsize=9)
    page.insert_text((420, 225), "One It", fontsize=9)
    page.insert_text((420, 240), "FUN If When", fontsize=9)
    page.insert_text((72, 300), "Figure 1: Workflow overview", fontsize=9)
    page.insert_text(
        (72, 760),
        "1 This note explains the acceptance timeline.",
        fontsize=8,
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


def test_merge_nearby_text_candidates_into_paragraph() -> None:
    blocks = [
        {
            "type": "paragraph",
            "source_text": "This is the first line",
            "bbox": [72, 100, 300, 112],
            "style": {"size": 11},
        },
        {
            "type": "paragraph",
            "source_text": "and this is the second line.",
            "bbox": [73, 116, 310, 128],
            "style": {"size": 11},
        },
    ]

    merged = merge_text_candidates(blocks)

    assert len(merged) == 1
    assert merged[0]["source_text"] == (
        "This is the first line and this is the second line."
    )


def test_extract_marks_header_and_footer() -> None:
    document_id = "doc_header_footer"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _pdf_with_header_footer())

    intermediate = extract_document_intermediate(document_id)
    block_types = [block.type for block in intermediate.pages[0].blocks]

    assert "header" in block_types
    assert "footer" in block_types

    _cleanup_document(document_id)


def test_extract_simple_native_image() -> None:
    document_id = "doc_image_extraction"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _pdf_with_image())

    intermediate = extract_document_intermediate(document_id)
    image_blocks = [
        block for block in intermediate.pages[0].blocks if block.type == "image"
    ]

    assert len(image_blocks) == 1
    assert image_blocks[0].page_number == 1
    assert image_blocks[0].bbox
    assert image_blocks[0].image_path
    assert image_blocks[0].has_possible_text is False
    assert image_blocks[0].status == "skipped"
    assert image_blocks[0].warnings == []
    assert get_images_directory(document_id).is_dir()

    _cleanup_document(document_id)


def test_intermediate_json_contains_image_block() -> None:
    document_id = "doc_image_json"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _pdf_with_image())

    extract_document_intermediate(document_id)
    payload = json.loads(get_intermediate_path(document_id).read_text(encoding="utf-8"))
    image_blocks = [
        block
        for page in payload["pages"]
        for block in page["blocks"]
        if block["type"] == "image"
    ]

    assert len(image_blocks) == 1
    assert image_blocks[0]["image_path"]
    assert image_blocks[0]["has_possible_text"] is False
    assert image_blocks[0]["status"] == "skipped"
    assert image_blocks[0]["warnings"] == []

    _cleanup_document(document_id)


def test_extract_marks_repeating_footer() -> None:
    document_id = "doc_repeating_footer"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _pdf_with_repeating_footer())

    intermediate = extract_document_intermediate(document_id)
    footer_blocks = [
        block
        for page in intermediate.pages
        for block in page.blocks
        if block.type == "footer"
    ]

    assert len(footer_blocks) == 2
    assert all(block.role == "repeating_footer" for block in footer_blocks)
    assert all(block.confidence_score == 0.9 for block in footer_blocks)

    _cleanup_document(document_id)


def test_extract_detects_title_and_list_items() -> None:
    document_id = "doc_title_list"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _pdf_with_list_items())

    intermediate = extract_document_intermediate(document_id)
    blocks = intermediate.pages[0].blocks

    assert any(block.type == "title" for block in blocks)
    assert sum(1 for block in blocks if block.type == "list_item") == 2
    assert all(
        block.source_page == block.page_number
        for block in blocks
        if block.type in {"title", "list_item"}
    )

    _cleanup_document(document_id)


def test_extract_groups_fragmented_lines_into_logical_paragraph() -> None:
    document_id = "doc_logical_paragraph"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _pdf_with_fragmented_paragraph_and_artifacts())

    intermediate = extract_document_intermediate(document_id)
    paragraphs = [
        block
        for block in intermediate.pages[0].blocks
        if block.type == "paragraph"
    ]

    assert any(
        "service scope and delivery requirements" in block.source_text
        and "acceptance criteria" in block.source_text
        for block in paragraphs
    )
    assert max(len(block.source_text.split()) for block in paragraphs) >= 20

    _cleanup_document(document_id)


def test_extract_removes_short_decorative_fragments() -> None:
    document_id = "doc_decorative_fragments"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _pdf_with_fragmented_paragraph_and_artifacts())

    intermediate = extract_document_intermediate(document_id)
    source_texts = [
        block.source_text
        for block in intermediate.pages[0].blocks
        if block.source_text
    ]

    assert "Who What When" not in source_texts
    assert "One It" not in source_texts
    assert "FUN If When" not in source_texts
    assert not any(
        block.type == "unknown" and len(block.source_text.split()) <= 3
        for block in intermediate.pages[0].blocks
    )

    _cleanup_document(document_id)


def test_extract_detects_caption_and_footnote() -> None:
    document_id = "doc_caption_footnote"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _pdf_with_fragmented_paragraph_and_artifacts())

    intermediate = extract_document_intermediate(document_id)
    block_types = [block.type for block in intermediate.pages[0].blocks]

    assert "caption" in block_types
    assert "footnote" in block_types

    _cleanup_document(document_id)
