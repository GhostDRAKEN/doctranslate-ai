import shutil
import json
from base64 import b64decode

import fitz
from fastapi.testclient import TestClient

from app.main import app
from app.services.extraction_service import (
    build_table_structure,
    build_grid_matrix,
    cluster_table_columns,
    cluster_table_rows,
    compute_semantic_merge_score,
    deduplicate_blocks,
    detect_table_columns,
    detect_table_regions,
    diagnose_table_structure,
    extract_document_intermediate,
    is_noise_block,
    merge_text_candidates,
    semantic_merge_blocks,
    table_grid_confidence,
    table_structure_confidence,
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


def _pdf_with_simple_table() -> bytes:
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    x_positions = [72, 180, 288]
    y_positions = [100, 124, 148]
    rows = [
        ["Name", "Age", "Role"],
        ["Alice", "30", "Engineer"],
        ["Bob", "41", "Manager"],
    ]
    for y, row in zip(y_positions, rows, strict=True):
        for x, value in zip(x_positions, row, strict=True):
            page.insert_text((x, y), value, fontsize=10)
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


def _pdf_with_duplicate_text_layer() -> bytes:
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((72, 80), "Duplicate Heading", fontsize=18)
    page.insert_text((72.4, 80.4), "Duplicate Heading", fontsize=18)
    page.insert_text(
        (72, 140),
        "This paragraph should only appear once after extraction.",
        fontsize=11,
    )
    page.insert_text(
        (72.4, 140.4),
        "This paragraph should only appear once after extraction.",
        fontsize=11,
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
    assert payload["sections"][0]["section_id"] == "section_001"
    assert payload["sections"][0]["title"] == "Service Agreement"
    assert payload["sections"][0]["block_ids"][0] == "block_001"

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


def test_deduplicate_blocks_keeps_one_identical_block() -> None:
    blocks = [
        {
            "page_number": 1,
            "type": "paragraph",
            "source_text": "This is duplicated content.",
            "bbox": [72, 100, 300, 130],
            "confidence_score": 0.72,
        },
        {
            "page_number": 1,
            "type": "paragraph",
            "source_text": "This is duplicated content.",
            "bbox": [72.2, 100.2, 300.2, 130.2],
            "confidence_score": 0.72,
        },
    ]

    deduplicated = deduplicate_blocks(blocks)

    assert len(deduplicated) == 1
    assert deduplicated[0]["source_text"] == "This is duplicated content."


def test_deduplicate_blocks_keeps_nearby_different_blocks() -> None:
    blocks = [
        {
            "page_number": 1,
            "type": "paragraph",
            "source_text": "First paragraph with different content.",
            "bbox": [72, 100, 300, 130],
            "confidence_score": 0.72,
        },
        {
            "page_number": 1,
            "type": "paragraph",
            "source_text": "Second paragraph with other meaning.",
            "bbox": [72.2, 100.2, 300.2, 130.2],
            "confidence_score": 0.72,
        },
    ]

    deduplicated = deduplicate_blocks(blocks)

    assert len(deduplicated) == 2


def _candidate_block(source_text: str, block_type: str = "unknown") -> dict:
    return {
        "page_number": 1,
        "type": block_type,
        "source_text": source_text,
        "bbox": [72, 100, 180, 118],
        "style": {
            "font": "Helvetica",
            "size": 11,
            "bold": False,
            "italic": False,
            "color": "#000000",
            "alignment": "left",
        },
        "status": "pending",
        "warnings": [],
    }


def _semantic_block(
    source_text: str,
    bbox: list[float],
    block_type: str = "paragraph",
    reading_order: int = 1,
    page_number: int = 1,
) -> dict:
    return {
        "page_number": page_number,
        "type": block_type,
        "source_text": source_text,
        "translated_text": "",
        "bbox": bbox,
        "style": {
            "font": "Helvetica",
            "size": 11,
            "bold": False,
            "italic": False,
            "color": "#000000",
            "alignment": "left",
        },
        "reading_order": reading_order,
        "status": "pending",
        "warnings": [],
    }


def _table_cell(text: str, bbox: list[float], row: int, column: int) -> dict:
    return _semantic_block(
        text,
        bbox,
        "paragraph",
        row * 10 + column,
    )


def _four_column_table_cells() -> list[dict]:
    rows = [
        ["Name", "Age", "Role", "Dept"],
        ["Alice", "30", "Engineer", "AI"],
        ["Bob", "41", "Manager", "Ops"],
    ]
    x_positions = [72, 160, 250, 360]
    y_positions = [100, 124, 148]
    cells = []
    for row_index, (y, values) in enumerate(zip(y_positions, rows, strict=True)):
        for column_index, (x, value) in enumerate(zip(x_positions, values, strict=True)):
            cells.append(
                _table_cell(
                    value,
                    [x, y, x + max(24, len(value) * 7), y + 14],
                    row_index,
                    column_index,
                )
            )
    return cells


def _ai_application_table_cells() -> list[dict]:
    rows = [
        [
            "Industry",
            "Main AI Application",
            "Primary Benefit",
            "Potential Risk",
        ],
        [
            "Transportation",
            "Autonomous vehicles",
            "Reduced accidents",
            "Job displacement",
        ],
        [
            "Marketing",
            "Personalized ads",
            "Higher conversion",
            "Consumer manipulation",
        ],
        [
            "Retail",
            "Recommendation systems",
            "Higher sales",
            "Consumer manipulation",
        ],
    ]
    x_positions = [72, 186, 328, 452]
    y_positions = [180, 208, 236, 264]
    cells = []
    for row_index, (y, values) in enumerate(zip(y_positions, rows, strict=True)):
        for column_index, (x, value) in enumerate(zip(x_positions, values, strict=True)):
            cells.append(
                _table_cell(
                    value,
                    [x, y, x + max(34, len(value) * 5.5), y + 14],
                    row_index,
                    column_index,
                )
            )
    return cells


def _ai_impact_table_page_blocks() -> list[dict]:
    blocks = [
        _semantic_block(
            (
                "Artificial Intelligence technologies are increasingly integrated into "
                "multiple industries. The table below summarizes the impact of AI in "
                "selected sectors."
            ),
            [56, 120, 556, 158],
            "paragraph",
            1,
        )
    ]
    rows = [
        ["Industry", "Main AI Application", "Primary Benefit", "Potential Risk"],
        ["Healthcare", "Medical diagnosis", "Faster detection", "Privacy concerns"],
        ["Finance", "Fraud detection", "Improved security", "Algorithmic bias"],
        ["Education", "Adaptive learning", "Personalized education", "Data collection issues"],
        ["Transportation", "Autonomous vehicles", "Reduced accidents", "Job displacement"],
        ["Retail", "Recommendation systems", "Higher sales", "Consumer manipulation"],
    ]
    bboxes = [
        [[84.68, 182.9, 124.12, 196.67], [187.6, 182.9, 280.39, 196.67], [333.85, 182.9, 407.76, 196.67], [467.33, 182.9, 533.46, 196.67]],
        [[80.22, 210.85, 128.57, 224.59], [194.26, 210.85, 273.73, 224.59], [334.95, 210.85, 406.65, 224.59], [462.33, 210.85, 538.46, 224.59]],
        [[86.61, 238.85, 122.18, 252.59], [199.26, 238.85, 268.74, 252.59], [331.35, 238.85, 410.25, 252.59], [465.11, 238.85, 535.68, 252.59]],
        [[82.17, 266.85, 126.64, 280.59], [195.37, 266.85, 272.63, 280.59], [318.83, 266.85, 422.77, 280.59], [452.05, 266.85, 548.75, 280.59]],
        [[72.17, 294.85, 136.63, 308.59], [186.48, 294.85, 281.52, 308.59], [328.28, 294.85, 413.32, 308.59], [461.49, 294.85, 539.3, 308.59]],
        [[91.62, 322.85, 117.18, 336.59], [175.1, 322.85, 292.9, 336.59], [343.01, 322.85, 398.58, 336.59], [447.6, 322.85, 553.19, 336.59]],
    ]
    reading_order = 2
    for row_values, row_bboxes in zip(rows, bboxes, strict=True):
        for value, bbox in zip(row_values, row_bboxes, strict=True):
            blocks.append(_semantic_block(value, bbox, "unknown", reading_order))
            reading_order += 1
    return blocks


def test_noise_block_detects_known_english_fragments() -> None:
    assert is_noise_block(_candidate_block("AI-powered"))
    assert is_noise_block(_candidate_block("However Issues"))
    assert is_noise_block(_candidate_block("Technology Startups"))
    assert is_noise_block(_candidate_block("Learning"))


def test_noise_block_keeps_short_real_title_and_names() -> None:
    assert not is_noise_block(_candidate_block("Overview", "title"))
    assert not is_noise_block(_candidate_block("David Grey"))


def test_noise_block_detects_text_included_in_main_block() -> None:
    main_block = _candidate_block(
        "Technology Startups rely on analytics to make better decisions.",
        "paragraph",
    )
    fragment = _candidate_block("Technology Startups")
    fragment["bbox"] = [74, 102, 180, 116]

    assert is_noise_block(fragment, [main_block, fragment])


def test_semantic_merge_combines_acronym_and_expansion() -> None:
    blocks = [
        _semantic_block("AI", [72, 100, 86, 114], "unknown", 1),
        _semantic_block(
            "Artificial Intelligence",
            [92, 100, 220, 114],
            "unknown",
            2,
        ),
    ]

    merged = semantic_merge_blocks(blocks)

    assert len(merged) == 1
    assert merged[0]["source_text"] == "Artificial Intelligence (AI)"
    assert merged[0]["merged_from"] == ["Artificial Intelligence"]
    assert merged[0]["merge_reason"] == "acronym_expansion"


def test_semantic_merge_combines_multiline_paragraph_fragments() -> None:
    blocks = [
        _semantic_block(
            "This platform translates complete document sections",
            [72, 100, 350, 114],
            "paragraph",
            1,
        ),
        _semantic_block(
            "with neighboring context for better quality.",
            [72, 118, 330, 132],
            "paragraph",
            2,
        ),
    ]

    score = compute_semantic_merge_score(blocks[0], blocks[1])
    merged = semantic_merge_blocks(blocks)

    assert score >= 0.72
    assert len(merged) == 1
    assert merged[0]["source_text"] == (
        "This platform translates complete document sections "
        "with neighboring context for better quality."
    )


def test_semantic_merge_does_not_merge_two_columns() -> None:
    blocks = [
        _semantic_block(
            "First column paragraph text continues here.",
            [72, 100, 240, 114],
            "paragraph",
            1,
        ),
        _semantic_block(
            "Second column paragraph starts separately.",
            [360, 100, 530, 114],
            "paragraph",
            2,
        ),
    ]

    merged = semantic_merge_blocks(blocks)

    assert len(merged) == 2


def test_semantic_merge_does_not_merge_titles() -> None:
    blocks = [
        _semantic_block("Artificial Intelligence", [72, 80, 240, 100], "title", 1),
        _semantic_block("Modern Technology", [72, 108, 240, 128], "title", 2),
    ]

    merged = semantic_merge_blocks(blocks)

    assert len(merged) == 2


def test_semantic_merge_ignores_headers() -> None:
    blocks = [
        _semantic_block("Confidential", [72, 20, 150, 32], "header", 1),
        _semantic_block("Company", [155, 20, 215, 32], "header", 2),
    ]

    merged = semantic_merge_blocks(blocks)

    assert len(merged) == 2


def test_build_table_structure_from_aligned_cells() -> None:
    cells = [
        _table_cell("Name", [72, 100, 110, 114], 0, 0),
        _table_cell("Age", [180, 100, 205, 114], 0, 1),
        _table_cell("Alice", [72, 124, 112, 138], 1, 0),
        _table_cell("30", [180, 124, 198, 138], 1, 1),
    ]

    structure = build_table_structure(cells)

    assert len(structure["rows"]) == 2
    assert structure["rows"][0]["cells"][0]["source_text"] == "Name"
    assert structure["rows"][1]["cells"][1]["column"] == 1
    assert table_structure_confidence(structure) >= 0.9


def test_detect_table_columns_from_four_column_table() -> None:
    cells = _four_column_table_cells()

    columns = cluster_table_columns(cells)

    assert len(columns) == 4
    assert columns[0]["column_id"] == "col_001"
    assert columns[3]["support_count"] == 3
    assert detect_table_columns(cells) == columns


def test_cluster_table_rows_from_four_column_table() -> None:
    cells = _four_column_table_cells()

    rows = cluster_table_rows(cells)

    assert len(rows) == 3
    assert rows[0]["row_id"] == "row_001"
    assert len(rows[1]["cells"]) == 4


def test_build_grid_matrix_maps_cells_to_rows_and_columns() -> None:
    cells = _four_column_table_cells()
    rows = cluster_table_rows(cells)
    columns = cluster_table_columns(cells)

    grid = build_grid_matrix(rows, columns)

    assert len(grid) == 3
    assert len(grid[0]) == 4
    assert grid[0][0]["text"] == "Name"
    assert grid[1][2]["column_index"] == 2


def test_rebuild_table_grid_inserts_empty_cells() -> None:
    cells = _four_column_table_cells()
    cells = [
        cell
        for cell in cells
        if not (cell["source_text"] == "41" and cell["bbox"][0] == 160)
    ]

    structure = build_table_structure(cells)

    assert len(structure["columns"]) == 4
    assert len(structure["grid"]) == 3
    assert len(structure["rows"]) == 3
    assert structure["rows"][2]["cells"][1]["source_text"] == ""
    assert structure["rows"][2]["cells"][1]["column_index"] == 1
    assert structure["rows"][2]["cells"][1]["empty_cell"] is True
    assert table_grid_confidence(structure) < 1.0


def test_ai_table_preserves_four_columns_and_short_cells() -> None:
    structure = build_table_structure(_ai_application_table_cells())

    assert len(structure["columns"]) == 4
    assert all(len(row["cells"]) == 4 for row in structure["rows"])
    assert structure["rows"][1]["cells"][2]["source_text"] == "Reduced accidents"
    assert structure["rows"][2]["cells"][3]["source_text"] == "Consumer manipulation"
    assert structure["rows"][1]["cells"][2]["empty_cell"] is False
    assert structure["rows"][2]["cells"][3]["empty_cell"] is False


def test_table_diagnostics_reports_missing_cells() -> None:
    cells = _ai_application_table_cells()[:-1]

    structure = build_table_structure(cells)
    diagnostics = diagnose_table_structure(structure)

    assert diagnostics["columns_detected"] == 4
    assert diagnostics["rows_detected"] == 4
    assert diagnostics["expected_cells"] == 16
    assert diagnostics["mapped_cells"] == 15
    assert diagnostics["missing_cells"] == 1
    assert diagnostics["missing_cells_by_position"] == [
        {"row_index": 3, "column_index": 3}
    ]


def test_table_cell_bboxes_use_logical_column_width() -> None:
    structure = build_table_structure(_ai_application_table_cells())
    source_bbox = [
        cell["bbox"]
        for cell in _ai_application_table_cells()
        if cell["source_text"] == "Reduced accidents"
    ][0]
    grid_cell = structure["rows"][1]["cells"][2]

    assert grid_cell["source_bbox"] == source_bbox
    assert grid_cell["bbox"][0] <= source_bbox[0]
    assert grid_cell["bbox"][2] > source_bbox[2]


def test_table_detection_keeps_retail_row_in_table() -> None:
    table_blocks, remaining = detect_table_regions(_ai_impact_table_page_blocks())

    assert len(table_blocks) == 1
    table = table_blocks[0]
    assert len(table["rows"]) == 6
    assert len(table["columns"]) == 4
    assert table["table_diagnostics"] == {
        "columns_detected": 4,
        "rows_detected": 6,
        "expected_cells": 24,
        "mapped_cells": 24,
        "missing_cells": 0,
        "missing_cells_by_position": [],
    }
    retail_row = table["rows"][5]["cells"]
    assert [cell["source_text"] for cell in retail_row] == [
        "Retail",
        "Recommendation systems",
        "Higher sales",
        "Consumer manipulation",
    ]
    remaining_text = " ".join(block["source_text"] for block in remaining)
    assert "Recommendation systems" not in remaining_text
    assert "Higher sales" not in remaining_text
    assert "Consumer manipulation" not in remaining_text


def test_detect_table_regions_extracts_simple_table_block() -> None:
    cells = [
        _table_cell("Name", [72, 100, 110, 114], 0, 0),
        _table_cell("Age", [180, 100, 205, 114], 0, 1),
        _table_cell("Alice", [72, 124, 112, 138], 1, 0),
        _table_cell("30", [180, 124, 198, 138], 1, 1),
    ]

    table_blocks, remaining = detect_table_regions(cells)

    assert len(table_blocks) == 1
    assert remaining == []
    assert table_blocks[0]["type"] == "table"
    assert len(table_blocks[0]["columns"]) == 2
    assert len(table_blocks[0]["grid"]) == 2
    assert table_blocks[0]["rows"][0]["cells"][0]["text"] == "Name"


def test_detect_table_regions_falls_back_when_structure_is_weak() -> None:
    cells = [
        _table_cell("Name", [72, 100, 110, 114], 0, 0),
        _table_cell("Age", [180, 100, 205, 114], 0, 1),
        _table_cell("Alice", [72, 124, 112, 138], 1, 0),
    ]

    table_blocks, remaining = detect_table_regions(cells)

    assert table_blocks == []
    assert remaining == cells


def test_semantic_merge_preserves_reading_order_after_extraction() -> None:
    document_id = "doc_semantic_order"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _sample_pdf_bytes())

    intermediate = extract_document_intermediate(document_id)
    blocks = intermediate.pages[0].blocks

    assert [block.reading_order for block in blocks] == list(
        range(1, len(blocks) + 1)
    )

    _cleanup_document(document_id)


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


def test_extract_detects_simple_table() -> None:
    document_id = "doc_simple_table"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _pdf_with_simple_table())

    intermediate = extract_document_intermediate(document_id)
    table_blocks = [
        block for block in intermediate.pages[0].blocks if block.type == "table"
    ]

    assert len(table_blocks) == 1
    table = table_blocks[0]
    assert table.table_structure_confidence is not None
    assert table.table_structure_confidence >= 0.6
    assert table.columns is not None
    assert len(table.columns) == 3
    assert len(table.rows or []) == 3
    assert table.rows[0]["cells"][0]["source_text"] == "Name"
    assert table.rows[2]["cells"][2]["source_text"] == "Manager"

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


def test_extract_recalculates_reading_order_after_duplicate_removal() -> None:
    document_id = "doc_duplicate_text_layer"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _pdf_with_duplicate_text_layer())

    intermediate = extract_document_intermediate(document_id)
    blocks = intermediate.pages[0].blocks

    assert intermediate.warnings == ["duplicated_blocks_removed"]
    assert [block.reading_order for block in blocks] == list(
        range(1, len(blocks) + 1)
    )
    assert sum(
        1 for block in blocks if block.source_text == "Duplicate Heading"
    ) == 1
    assert sum(
        1
        for block in blocks
        if block.source_text == (
            "This paragraph should only appear once after extraction."
        )
    ) == 1

    _cleanup_document(document_id)


def test_intermediate_json_final_has_no_duplicate_pairs() -> None:
    document_id = "doc_duplicate_json"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _pdf_with_duplicate_text_layer())

    extract_document_intermediate(document_id)
    payload = json.loads(get_intermediate_path(document_id).read_text(encoding="utf-8"))
    blocks = payload["pages"][0]["blocks"]
    source_texts = [block["source_text"] for block in blocks]

    assert payload["warnings"] == ["duplicated_blocks_removed"]
    assert len(source_texts) == len(set(source_texts))
    assert [block["reading_order"] for block in blocks] == list(
        range(1, len(blocks) + 1)
    )

    _cleanup_document(document_id)


def test_intermediate_json_contains_sections() -> None:
    document_id = "doc_sections_json"
    _cleanup_document(document_id)
    save_source_pdf(document_id, _sample_pdf_bytes())

    extract_document_intermediate(document_id)
    payload = json.loads(get_intermediate_path(document_id).read_text(encoding="utf-8"))
    sections = payload["sections"]

    assert len(sections) == 1
    assert sections[0]["section_id"] == "section_001"
    assert sections[0]["title"] == "Service Agreement"
    assert sections[0]["page_start"] == 1
    assert sections[0]["page_end"] == 1
    assert sections[0]["blocks_count"] == len(sections[0]["block_ids"])

    _cleanup_document(document_id)
