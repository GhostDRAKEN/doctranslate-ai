"""PDF extraction service based on PyMuPDF."""

import json
import logging
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import fitz
from fastapi import status

from app.core.config import get_settings
from app.core.errors import AppError
from app.schemas.document import DocumentIntermediate
from app.services.job_service import now_utc
from app.services.section_service import build_document_sections
from app.services.storage_service import (
    get_images_directory,
    get_intermediate_path,
    get_source_pdf_path,
)

logger = logging.getLogger(__name__)


def extract_document_intermediate(document_id: str) -> DocumentIntermediate:
    """Extract text blocks from source.pdf and persist intermediate.json."""

    source_path = get_source_pdf_path(document_id)
    if not source_path.is_file():
        raise AppError(
            code="DOCUMENT_NOT_FOUND",
            message="Le document demande est introuvable.",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"document_id": document_id},
        )

    try:
        with fitz.open(source_path) as pdf_document:
            intermediate = build_intermediate(document_id, source_path, pdf_document)
    except AppError:
        raise
    except Exception as exc:
        raise AppError(
            code="INTERNAL_ERROR",
            message="L'extraction du PDF a echoue.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        ) from exc

    write_intermediate(document_id, intermediate)
    return intermediate


def build_intermediate(
    document_id: str,
    source_path: Path,
    pdf_document: fitz.Document,
) -> DocumentIntermediate:
    """Build a validated intermediate model from an opened PDF."""

    settings = get_settings()
    warnings: list[str] = []
    max_page_count = (
        settings.max_batch_experimental_pages
        if settings.enable_batch_mode
        else settings.max_page_count
    )
    if pdf_document.page_count > max_page_count:
        raise AppError(
            code="PDF_TOO_MANY_PAGES",
            message=(
                "Le PDF depasse la limite MVP de "
                f"{max_page_count} pages."
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
            details={
                "page_count": pdf_document.page_count,
                "max_page_count": max_page_count,
            },
        )

    pages: list[dict[str, Any]] = []
    block_index = 1
    image_index = 1
    text_block_count = 0

    for page_number, page in enumerate(pdf_document, start=1):
        raw_blocks = page.get_text("dict").get("blocks", [])
        text_blocks = [block for block in raw_blocks if block.get("type") == 0]
        image_blocks = [block for block in raw_blocks if block.get("type") == 1]
        page_font_average = calculate_page_font_average(text_blocks)
        page_candidates = extract_line_candidates(
            text_blocks,
            page_number,
            page_font_average,
            page.rect.height,
        )
        text_block_count += len(page_candidates)
        table_blocks, page_candidates = detect_table_regions(page_candidates)
        page_candidates = remove_noise_candidates(page_candidates)
        candidate_count_before_deduplication = len(page_candidates)
        page_candidates = deduplicate_candidates(page_candidates)
        if len(page_candidates) < candidate_count_before_deduplication:
            if "duplicated_blocks_removed" not in warnings:
                warnings.append("duplicated_blocks_removed")
        page_candidates = merge_text_candidates(page_candidates)
        page_candidates = semantic_merge_blocks(page_candidates)
        block_count_before_deduplication = len(page_candidates)
        page_candidates = deduplicate_blocks(page_candidates)
        if len(page_candidates) < block_count_before_deduplication:
            if "duplicated_blocks_removed" not in warnings:
                warnings.append("duplicated_blocks_removed")
        mark_noise_blocks(page_candidates)
        page_candidates.extend(table_blocks)

        for image_block in image_blocks:
            image_payload = extract_image_block(
                document_id,
                image_block,
                page_number,
                image_index,
            )
            if image_payload:
                page_candidates.append(image_payload)
                image_index += 1

        page_candidates = sorted(
            page_candidates,
            key=lambda block: (block.get("bbox", [0, 0, 0, 0])[1], block.get("bbox", [0, 0, 0, 0])[0]),
        )

        page_blocks: list[dict[str, Any]] = []
        for reading_order, block in enumerate(page_candidates, start=1):
            block["id"] = f"block_{block_index:03d}"
            block["reading_order"] = reading_order
            page_blocks.append(block)
            block_index += 1

        if not page_blocks:
            warnings.append(f"page_{page_number}_without_text")

        pages.append(
            {
                "page_number": page_number,
                "width": round(float(page.rect.width), 2),
                "height": round(float(page.rect.height), 2),
                "blocks": page_blocks,
            }
        )

    mark_repeating_headers_and_footers(pages)
    sections = build_document_sections(
        [
            block
            for page in pages
            for block in page.get("blocks", [])
        ]
    )

    if text_block_count == 0:
        raise AppError(
            code="PDF_NO_SELECTABLE_TEXT",
            message="Le PDF doit contenir du texte selectionnable.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            details=None,
        )

    file_size_mb = round(source_path.stat().st_size / (1024 * 1024), 2)
    return DocumentIntermediate.model_validate(
        {
            "document_id": document_id,
            "source_language": "en",
            "target_language": "fr",
            "domain": "general",
            "metadata": {
                "filename": "source.pdf",
                "page_count": pdf_document.page_count,
                "file_size_mb": file_size_mb,
                "created_at": now_utc(),
            },
            "mvp_limits": {
                "max_pages": settings.max_page_count,
                "max_file_size_mb": settings.max_file_size_mb,
                "digital_pdf_only": True,
                "requires_selectable_text": True,
            },
            "glossary": [],
            "pages": pages,
            "sections": sections,
            "warnings": warnings,
        }
    )


def write_intermediate(
    document_id: str,
    intermediate: DocumentIntermediate,
) -> None:
    """Persist intermediate.json for backend debug and later pipeline stages."""

    intermediate_path = get_intermediate_path(document_id)
    intermediate_path.write_text(
        json.dumps(
            intermediate.model_dump(),
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )


def read_intermediate(document_id: str) -> dict[str, Any]:
    """Read intermediate.json without exposing local file paths."""

    intermediate_path = get_intermediate_path(document_id)
    if not intermediate_path.is_file():
        raise AppError(
            code="RESULT_NOT_READY",
            message="La representation intermediaire n'est pas encore disponible.",
            status_code=status.HTTP_409_CONFLICT,
            details={"document_id": document_id},
        )

    return json.loads(intermediate_path.read_text(encoding="utf-8"))


def extract_block_text(block: dict[str, Any]) -> str:
    """Extract normalized text from a PyMuPDF text block."""

    lines: list[str] = []
    for line in block.get("lines", []):
        spans = line.get("spans", [])
        line_text = " ".join(span.get("text", "") for span in spans)
        if line_text.strip():
            lines.append(line_text.strip())

    return normalize_text(" ".join(lines))


def extract_block_style(block: dict[str, Any]) -> dict[str, Any]:
    """Infer an approximate style from the first meaningful span."""

    spans = [
        span
        for line in block.get("lines", [])
        for span in line.get("spans", [])
        if span.get("text", "").strip()
    ]
    if not spans:
        return {
            "font": None,
            "size": None,
            "bold": False,
            "italic": False,
            "color": "#000000",
            "alignment": "left",
        }

    fonts = Counter(str(span.get("font", "")) for span in spans)
    sizes = [float(span.get("size", 0)) for span in spans if span.get("size")]
    first_span = spans[0]
    font = fonts.most_common(1)[0][0] or None
    flags = int(first_span.get("flags", 0))
    color_value = int(first_span.get("color", 0))

    return {
        "font": font,
        "size": round(sum(sizes) / len(sizes), 2) if sizes else None,
        "bold": bool(font and "bold" in font.lower()) or bool(flags & 16),
        "italic": bool(font and "italic" in font.lower()) or bool(flags & 2),
        "color": f"#{color_value:06x}",
        "alignment": "left",
    }


def extract_line_candidates(
    blocks: list[dict[str, Any]],
    page_number: int,
    page_font_average: float,
    page_height: float,
) -> list[dict[str, Any]]:
    """Convert PyMuPDF text lines into logical block candidates."""

    candidates: list[dict[str, Any]] = []
    sorted_blocks = sorted(
        blocks,
        key=lambda block: (
            block.get("bbox", [0, 0, 0, 0])[1],
            block.get("bbox", [0, 0, 0, 0])[0],
        ),
    )

    for block in sorted_blocks:
        for line in block.get("lines", []):
            spans = [
                span
                for span in line.get("spans", [])
                if span.get("text", "").strip()
            ]
            source_text = normalize_text(
                " ".join(str(span.get("text", "")).strip() for span in spans)
            )
            if not source_text:
                continue

            bbox = normalize_bbox(line.get("bbox") or union_span_bbox(spans))
            style = extract_style_from_spans(spans)
            block_type = classify_text_block(
                source_text,
                style["size"],
                page_font_average,
                bbox,
                page_height,
                style,
            )
            block_type = classify_header_footer(block_type, bbox, page_height)
            candidates.append(
                {
                    "page_number": page_number,
                    "source_page": page_number,
                    "type": block_type,
                    "role": role_for_block_type(block_type),
                    "confidence_score": confidence_for_block_type(block_type),
                    "source_text": source_text,
                    "translated_text": "",
                    "bbox": bbox,
                    "style": style,
                    "status": "pending",
                    "warnings": [],
                }
            )

    return candidates


def extract_style_from_spans(spans: list[dict[str, Any]]) -> dict[str, Any]:
    """Infer an approximate style from line spans."""

    if not spans:
        return {
            "font": None,
            "size": None,
            "bold": False,
            "italic": False,
            "color": "#000000",
            "alignment": "left",
        }

    fonts = Counter(str(span.get("font", "")) for span in spans)
    sizes = [float(span.get("size", 0)) for span in spans if span.get("size")]
    first_span = spans[0]
    font = fonts.most_common(1)[0][0] or None
    flags = int(first_span.get("flags", 0))
    color_value = int(first_span.get("color", 0))

    return {
        "font": font,
        "size": round(sum(sizes) / len(sizes), 2) if sizes else None,
        "bold": bool(font and "bold" in font.lower()) or bool(flags & 16),
        "italic": bool(font and "italic" in font.lower()) or bool(flags & 2),
        "color": f"#{color_value:06x}",
        "alignment": "left",
    }


def union_span_bbox(spans: list[dict[str, Any]]) -> list[float]:
    """Return a bbox containing all spans in a line."""

    bboxes = [span.get("bbox") for span in spans if span.get("bbox")]
    if not bboxes:
        return [0, 0, 0, 0]
    return [
        min(float(bbox[0]) for bbox in bboxes),
        min(float(bbox[1]) for bbox in bboxes),
        max(float(bbox[2]) for bbox in bboxes),
        max(float(bbox[3]) for bbox in bboxes),
    ]


def remove_noise_candidates(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove short PDF artifacts before logical paragraph grouping."""

    cleaned: list[dict[str, Any]] = []
    for block in blocks:
        if is_decorative_artifact(block):
            continue
        cleaned.append(block)
    return cleaned


def deduplicate_candidates(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicated candidates emitted by PDF internals."""

    seen: set[tuple[str, int, int]] = set()
    deduplicated: list[dict[str, Any]] = []
    for block in blocks:
        source_text = str(block.get("source_text", ""))
        text_key = normalize_repetition_key(source_text)
        bbox = block.get("bbox", [0, 0, 0, 0])
        page_number = int(block.get("page_number") or 0)
        position_bucket = int(round(float(bbox[1]) / 3)) if bbox else 0
        key = (text_key, page_number, position_bucket)
        if text_key and key in seen:
            continue
        if text_key:
            seen.add(key)
        deduplicated.append(block)
    return deduplicated


def deduplicate_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove overlapping logical blocks that represent the same content."""

    deduplicated: list[dict[str, Any]] = []
    for block in blocks:
        duplicate_index = find_duplicate_block_index(deduplicated, block)
        if duplicate_index is None:
            deduplicated.append(block)
            continue

        if should_replace_duplicate(deduplicated[duplicate_index], block):
            deduplicated[duplicate_index] = block

    return deduplicated


def detect_table_regions(
    page_blocks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Detect simple one-page table regions and remove their cells from prose."""

    table_rows = group_table_candidate_rows(page_blocks)
    table_groups = collect_table_row_groups(table_rows)
    logger.debug(
        "Table detection candidates rows=%s groups=%s",
        len(table_rows),
        len(table_groups),
    )
    if not table_groups:
        return [], page_blocks

    table_blocks: list[dict[str, Any]] = []
    consumed_ids: set[int] = set()
    table_index = 1
    for group in table_groups:
        structure = rebuild_table_grid([cell for row in group for cell in row])
        confidence = table_structure_confidence(structure)
        if confidence < 0.6:
            continue

        for row in group:
            for block in row:
                consumed_ids.add(id(block))

        table_block = build_table_block(
            group,
            structure,
            table_index=table_index,
            confidence=confidence,
        )
        table_blocks.append(table_block)
        logger.debug(
            "Table detected table_id=%s rows=%s columns=%s diagnostics=%s",
            table_block.get("table_id"),
            len(table_block.get("rows") or []),
            len(table_block.get("columns") or []),
            table_block.get("table_diagnostics"),
        )
        table_index += 1

    if not table_blocks:
        return [], page_blocks

    remaining_blocks = [
        block for block in page_blocks if id(block) not in consumed_ids
    ]
    near_rejected = find_blocks_near_table_regions(table_blocks, remaining_blocks)
    if near_rejected:
        logger.debug("Blocks near table but not integrated=%s", near_rejected)
    return table_blocks, remaining_blocks


def group_table_candidate_rows(
    page_blocks: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Group short aligned blocks into possible table rows."""

    candidates = [
        block
        for block in page_blocks
        if is_table_cell_candidate(block)
    ]
    rows: list[list[dict[str, Any]]] = []
    for block in sorted(
        candidates,
        key=lambda item: (
            float((item.get("bbox") or [0, 0, 0, 0])[1]),
            float((item.get("bbox") or [0, 0, 0, 0])[0]),
        ),
    ):
        bbox = block.get("bbox") or [0, 0, 0, 0]
        center_y = (float(bbox[1]) + float(bbox[3])) / 2
        matching_row = None
        for row in rows:
            row_bbox = row[0].get("bbox") or [0, 0, 0, 0]
            row_center_y = (float(row_bbox[1]) + float(row_bbox[3])) / 2
            if abs(center_y - row_center_y) <= 5:
                matching_row = row
                break
        if matching_row is None:
            rows.append([block])
        else:
            matching_row.append(block)

    return [
        sorted(row, key=lambda item: float((item.get("bbox") or [0, 0, 0, 0])[0]))
        for row in rows
        if len(row) >= 2
    ]


def collect_table_row_groups(
    rows: list[list[dict[str, Any]]],
) -> list[list[list[dict[str, Any]]]]:
    """Collect consecutive candidate rows with compatible column geometry."""

    groups: list[list[list[dict[str, Any]]]] = []
    current_group: list[list[dict[str, Any]]] = []
    for row in rows:
        if not current_group:
            current_group = [row]
            continue

        previous_row = current_group[-1]
        if are_compatible_table_rows(previous_row, row):
            current_group.append(row)
            continue

        if len(current_group) >= 2:
            groups.append(current_group)
        current_group = [row]

    if len(current_group) >= 2:
        groups.append(current_group)

    return groups


def are_compatible_table_rows(
    previous_row: list[dict[str, Any]],
    current_row: list[dict[str, Any]],
) -> bool:
    """Return whether two rows probably belong to the same simple table."""

    if len(previous_row) != len(current_row):
        return False
    previous_y = max(float((block.get("bbox") or [0, 0, 0, 0])[3]) for block in previous_row)
    current_y = min(float((block.get("bbox") or [0, 0, 0, 0])[1]) for block in current_row)
    if not 4 <= current_y - previous_y <= 32:
        return False

    previous_bboxes = [block.get("bbox") or [0, 0, 0, 0] for block in previous_row]
    current_bboxes = [block.get("bbox") or [0, 0, 0, 0] for block in current_row]
    previous_x = [float(bbox[0]) for bbox in previous_bboxes]
    current_x = [float(bbox[0]) for bbox in current_bboxes]
    previous_centers = [(float(bbox[0]) + float(bbox[2])) / 2 for bbox in previous_bboxes]
    current_centers = [(float(bbox[0]) + float(bbox[2])) / 2 for bbox in current_bboxes]
    aligned_left_edges = sum(
        1
        for first_x, second_x in zip(previous_x, current_x, strict=True)
        if abs(first_x - second_x) <= 18
    )
    aligned_centers = sum(
        1
        for first_center, second_center in zip(previous_centers, current_centers, strict=True)
        if abs(first_center - second_center) <= 24
    )
    aligned_columns = max(aligned_left_edges, aligned_centers)
    return aligned_columns >= max(2, len(previous_row) - 1)


def build_table_structure(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """Build MVP rows/cells from simple aligned cell blocks."""

    return rebuild_table_grid(blocks)


def detect_table_columns(table_blocks: list[dict[str, Any]]) -> list[dict[str, float | str]]:
    """Backward-compatible alias for the column clustering engine."""

    return cluster_table_columns(table_blocks)


def cluster_table_columns(cells: list[dict[str, Any]]) -> list[dict[str, float | str]]:
    """Cluster cells into stable columns using x position, center and width."""

    candidates = sorted(
        [block for block in cells if is_table_cell_candidate(block)],
        key=lambda block: float((block.get("bbox") or [0, 0, 0, 0])[0]),
    )
    columns: list[dict[str, Any]] = []
    for block in candidates:
        bbox = block.get("bbox") or [0, 0, 0, 0]
        x0 = float(bbox[0])
        x1 = float(bbox[2])
        width = max(0.0, x1 - x0)
        center = (x0 + x1) / 2
        matching_column = find_matching_column(columns, x0, center, width)
        if matching_column is None:
            columns.append(
                {
                    "x0_values": [x0],
                    "x1_values": [x1],
                    "width_values": [width],
                    "center_values": [center],
                    "page_y_values": [float(bbox[1])],
                    "count": 1,
                }
            )
            continue

        matching_column["x0_values"].append(x0)
        matching_column["x1_values"].append(x1)
        matching_column["width_values"].append(width)
        matching_column["center_values"].append(center)
        matching_column["page_y_values"].append(float(bbox[1]))
        matching_column["count"] += 1

    normalized_columns = []
    for index, column in enumerate(
        sorted(columns, key=lambda item: average(item["x0_values"])),
        start=1,
    ):
        normalized_columns.append(
            {
                "column_id": f"col_{index:03d}",
                "x0": round(min(column["x0_values"]), 2),
                "x1": round(max(column["x1_values"]), 2),
                "center": round(average(column["center_values"]), 2),
                "width": round(average(column["width_values"]), 2),
                "support_count": int(column["count"]),
                "vertical_repetition": len(
                    {round(float(value) / 8) for value in column["page_y_values"]}
                ),
            }
        )
    return add_column_boundaries(normalized_columns)


def cluster_table_rows(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cluster cells into stable rows using y position and vertical proximity."""

    candidates = sorted(
        [block for block in cells if is_table_cell_candidate(block)],
        key=lambda block: (
            cell_center_y(block),
            float((block.get("bbox") or [0, 0, 0, 0])[0]),
        ),
    )
    row_clusters: list[dict[str, Any]] = []
    for block in candidates:
        center = cell_center_y(block)
        bbox = block.get("bbox") or [0, 0, 0, 0]
        matching_row = None
        for row in row_clusters:
            if abs(center - average(row["center_values"])) <= 7:
                matching_row = row
                break
        if matching_row is None:
            row_clusters.append(
                {
                    "cells": [block],
                    "y0_values": [float(bbox[1])],
                    "y1_values": [float(bbox[3])],
                    "center_values": [center],
                }
            )
            continue

        matching_row["cells"].append(block)
        matching_row["y0_values"].append(float(bbox[1]))
        matching_row["y1_values"].append(float(bbox[3]))
        matching_row["center_values"].append(center)

    rows: list[dict[str, Any]] = []
    for index, row in enumerate(
        sorted(row_clusters, key=lambda item: average(item["center_values"])),
        start=1,
    ):
        rows.append(
            {
                "row_id": f"row_{index:03d}",
                "row_index": index - 1,
                "y0": round(min(row["y0_values"]), 2),
                "y1": round(max(row["y1_values"]), 2),
                "center": round(average(row["center_values"]), 2),
                "cells": sorted(
                    row["cells"],
                    key=lambda block: float((block.get("bbox") or [0, 0, 0, 0])[0]),
                ),
            }
        )
    return rows


def rebuild_table_grid(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """Build an explicit table grid with columns and empty cells."""

    rows = cluster_table_rows(blocks)
    columns = cluster_table_columns(blocks)
    if not rows or not columns:
        return {"columns": [], "rows": [], "grid": []}

    grid = build_grid_matrix(rows, columns)
    return {"columns": columns, "rows": [{"cells": row} for row in grid], "grid": grid}


def build_grid_matrix(
    rows: list[dict[str, Any]],
    columns: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Build a logical grid matrix from clustered rows and columns."""

    grid: list[list[dict[str, Any]]] = []
    for row_index, row in enumerate(rows):
        cells: list[dict[str, Any]] = []
        used_blocks: set[int] = set()
        row_top, row_bottom = row_boundaries(rows, row_index)
        for column_index, column in enumerate(columns):
            block = find_cell_for_column(row.get("cells") or [], column, used_blocks)
            cell_bbox = logical_cell_bbox(column, row_top, row_bottom)
            if block is None:
                cells.append(
                    {
                        "row_index": row_index,
                        "column_index": column_index,
                        "row": row_index,
                        "column": column_index,
                        "text": "",
                        "source_text": "",
                        "translated_text": "",
                        "bbox": cell_bbox,
                        "empty_cell": True,
                        "weak_alignment": True,
                    }
                )
                continue

            used_blocks.add(id(block))
            source_text = str(block.get("source_text") or "")
            weak_alignment = cell_column_distance(block, column) > 18
            source_bbox = block.get("bbox") or []
            cells.append(
                {
                    "row_index": row_index,
                    "column_index": column_index,
                    "row": row_index,
                    "column": column_index,
                    "text": source_text,
                    "source_text": source_text,
                    "translated_text": "",
                    "bbox": cell_bbox,
                    "source_bbox": source_bbox,
                    "empty_cell": False,
                    "weak_alignment": weak_alignment,
                }
            )
        grid.append(cells)
    return grid


def find_matching_column(
    columns: list[dict[str, Any]],
    x0: float,
    center: float,
    width: float,
) -> dict[str, Any] | None:
    """Find a compatible column bucket for a cell x position."""

    for column in columns:
        existing_x0 = average(column["x0_values"])
        existing_center = average(column["center_values"])
        existing_x1 = average(column["x1_values"])
        existing_width = average(column["width_values"])
        x0_close = abs(x0 - existing_x0) <= 10
        center_close = abs(center - existing_center) <= 10
        x1_close = abs((x0 + width) - existing_x1) <= 12
        width_close = abs(width - existing_width) <= max(14, existing_width * 0.45)
        far_left_edge = abs(x0 - existing_x0) > 34

        if x0_close:
            return column
        if not far_left_edge and center_close:
            return column
        if not far_left_edge and x1_close and width_close:
            return column
    return None


def find_cell_for_column(
    row: list[dict[str, Any]],
    column: dict[str, Any],
    used_blocks: set[int],
) -> dict[str, Any] | None:
    """Map one row cell candidate to a detected table column."""

    best_block = None
    best_distance = 9999.0
    for block in row:
        if id(block) in used_blocks:
            continue
        if not cell_is_inside_column(block, column):
            continue
        distance = cell_column_distance(block, column)
        if distance < best_distance:
            best_distance = distance
            best_block = block

    if best_block is not None and best_distance <= 52:
        return best_block
    return None


def cell_column_distance(block: dict[str, Any], column: dict[str, Any]) -> float:
    """Return horizontal distance between a cell center and a column center."""

    bbox = block.get("bbox") or [0, 0, 0, 0]
    x0 = float(bbox[0])
    center = (float(bbox[0]) + float(bbox[2])) / 2
    center_distance = abs(center - float(column.get("center") or 0))
    x0_distance = abs(x0 - float(column.get("x0") or 0))
    return min(center_distance, x0_distance)


def cell_is_inside_column(block: dict[str, Any], column: dict[str, Any]) -> bool:
    """Return whether a text cell belongs to a logical column band."""

    bbox = block.get("bbox") or [0, 0, 0, 0]
    x0 = float(bbox[0])
    x1 = float(bbox[2])
    center = (x0 + x1) / 2
    left = float(column.get("left_boundary") or column.get("x0") or 0)
    right = float(column.get("right_boundary") or column.get("x1") or 0)
    expected_x0 = float(column.get("x0") or 0)
    expected_center = float(column.get("center") or 0)

    if left - 3 <= center <= right + 3:
        return True
    if abs(x0 - expected_x0) <= 16:
        return True
    return abs(center - expected_center) <= 18 and left - 18 <= x0 <= right + 18


def cell_center_y(block: dict[str, Any]) -> float:
    """Return vertical center of a table cell candidate."""

    bbox = block.get("bbox") or [0, 0, 0, 0]
    return (float(bbox[1]) + float(bbox[3])) / 2


def empty_cell_bbox(row: list[dict[str, Any]], column: dict[str, Any]) -> list[float]:
    """Create an approximate bbox for a missing cell in a logical grid."""

    row_bbox = row[0].get("bbox") or [0, 0, 0, 0]
    y0 = min(float((block.get("bbox") or row_bbox)[1]) for block in row)
    y1 = max(float((block.get("bbox") or row_bbox)[3]) for block in row)
    return [
        round(float(column.get("x0") or 0), 2),
        round(y0, 2),
        round(float(column.get("x1") or column.get("x0") or 0), 2),
        round(y1, 2),
    ]


def add_column_boundaries(
    columns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Add stable logical cell boundaries between detected columns."""

    if not columns:
        return columns

    sorted_columns = sorted(columns, key=lambda column: float(column.get("x0") or 0))
    for index, column in enumerate(sorted_columns):
        previous_column = sorted_columns[index - 1] if index > 0 else None
        next_column = sorted_columns[index + 1] if index < len(sorted_columns) - 1 else None
        x0 = float(column.get("x0") or 0)
        x1 = float(column.get("x1") or x0)

        if previous_column is None:
            left_boundary = x0 - 4
        else:
            previous_right = float(previous_column.get("x1") or previous_column.get("x0") or x0)
            previous_center = float(previous_column.get("center") or previous_right)
            current_center = float(column.get("center") or x0)
            left_boundary = min(x0 - 3, (previous_center + current_center) / 2)
            left_boundary = max(previous_right + 2, left_boundary)

        if next_column is None:
            right_boundary = x1 + 10
        else:
            next_x0 = float(next_column.get("x0") or x1)
            current_center = float(column.get("center") or x1)
            next_center = float(next_column.get("center") or next_x0)
            right_boundary = max(x1 + 3, (current_center + next_center) / 2)
            right_boundary = min(next_x0 - 3, right_boundary)

        if right_boundary <= left_boundary:
            left_boundary = x0 - 3
            right_boundary = x1 + 6

        column["left_boundary"] = round(left_boundary, 2)
        column["right_boundary"] = round(right_boundary, 2)
        column["logical_width"] = round(right_boundary - left_boundary, 2)

    return sorted_columns


def row_boundaries(rows: list[dict[str, Any]], row_index: int) -> tuple[float, float]:
    """Return a logical vertical band for one table row."""

    row = rows[row_index]
    y0 = float(row.get("y0") or 0)
    y1 = float(row.get("y1") or y0)
    top = y0 - 2
    if row_index < len(rows) - 1:
        next_y0 = float(rows[row_index + 1].get("y0") or y1)
        bottom = max(y1 + 2, next_y0 - 3)
    else:
        previous_gap = 0.0
        if row_index > 0:
            previous_y0 = float(rows[row_index - 1].get("y0") or y0)
            previous_gap = max(0.0, y0 - previous_y0)
        bottom = y1 + max(8.0, min(previous_gap - 3, 20.0) if previous_gap else 10.0)

    if bottom <= top:
        bottom = y1 + 8
    return round(top, 2), round(bottom, 2)


def logical_cell_bbox(
    column: dict[str, Any],
    row_top: float,
    row_bottom: float,
) -> list[float]:
    """Create the renderable logical bbox for one table grid cell."""

    left = float(column.get("left_boundary") or column.get("x0") or 0)
    right = float(column.get("right_boundary") or column.get("x1") or left)
    return [
        round(left, 2),
        round(row_top, 2),
        round(max(right, left + 8), 2),
        round(max(row_bottom, row_top + 8), 2),
    ]


def average(values: list[float]) -> float:
    """Return an arithmetic average without importing statistics for tiny lists."""

    return sum(float(value) for value in values) / max(len(values), 1)


def table_structure_confidence(structure: dict[str, Any]) -> float:
    """Score simple table structure quality for MVP fallback decisions."""

    return table_grid_confidence(structure)


def table_grid_confidence(structure: dict[str, Any]) -> float:
    """Score table grid quality from clustered rows, columns and cells."""

    rows = structure.get("rows") or []
    grid = structure.get("grid") or [
        row.get("cells") or [] for row in rows
    ]
    if len(rows) < 2:
        return 0.0

    columns = structure.get("columns") or []
    column_counts = [len(row.get("cells") or []) for row in rows]
    if not column_counts or min(column_counts) < 2:
        return 0.0

    expected_columns = max(set(column_counts), key=column_counts.count)
    consistent_rows = sum(1 for count in column_counts if count == expected_columns)
    non_empty_cells = 0
    total_cells = 0
    weak_cells = 0
    empty_cells = 0
    for row in rows:
        for cell in row.get("cells") or []:
            total_cells += 1
            if str(cell.get("source_text") or cell.get("text") or "").strip():
                non_empty_cells += 1
            if cell.get("empty_cell"):
                empty_cells += 1
            if cell.get("weak_alignment"):
                weak_cells += 1

    consistency_score = consistent_rows / len(rows)
    fill_score = non_empty_cells / max(total_cells, 1)
    column_score = min(1.0, len(columns) / max(expected_columns, 1)) if columns else 0.0
    grid_score = 1.0
    if total_cells:
        grid_score -= min(0.45, empty_cells / total_cells * 0.8)
        grid_score -= min(0.3, weak_cells / total_cells * 0.5)
    if not grid:
        grid_score = 0.0
    return round(
        min(
            1.0,
            (consistency_score * 0.25)
            + (fill_score * 0.22)
            + (column_score * 0.23)
            + (grid_score * 0.3),
        ),
        3,
    )


def build_table_block(
    grouped_rows: list[list[dict[str, Any]]],
    structure: dict[str, Any],
    *,
    table_index: int,
    confidence: float,
) -> dict[str, Any]:
    """Create one intermediate table block from grouped cell candidates."""

    cells = [cell for row in grouped_rows for cell in row]
    bbox = cells[0].get("bbox", [0, 0, 0, 0])
    for cell in cells[1:]:
        bbox = union_bbox(bbox, cell.get("bbox", [0, 0, 0, 0]))

    page_number = int(cells[0].get("page_number") or 0)
    style = cells[0].get("style") or default_block_style()
    source_text = " ".join(
        str(cell.get("source_text") or "")
        for cell in cells
        if str(cell.get("source_text") or "").strip()
    )
    warnings: list[str] = []
    if confidence < 0.75:
        warnings.append("table_detection_uncertain")
    diagnostics = diagnose_table_structure(structure)
    if diagnostics.get("missing_cells"):
        warnings.append("table_missing_cells_detected")

    return {
        "page_number": page_number,
        "source_page": page_number,
        "type": "table",
        "table_id": f"table_{table_index:03d}",
        "role": "table",
        "confidence_score": confidence,
        "table_structure_confidence": confidence,
        "table_grid_confidence": confidence,
        "source_text": normalize_text(source_text),
        "translated_text": "",
        "bbox": normalize_bbox(bbox),
        "style": style,
        "status": "pending",
        "warnings": warnings,
        "columns": structure.get("columns") or [],
        "grid": structure.get("grid") or [],
        "rows": structure.get("rows") or [],
        "table_diagnostics": diagnostics,
    }


def diagnose_table_structure(structure: dict[str, Any]) -> dict[str, Any]:
    """Return compact diagnostics for table grid inspection."""

    columns = structure.get("columns") or []
    rows = structure.get("rows") or []
    grid = structure.get("grid") or [
        row.get("cells") or [] for row in rows if isinstance(row, dict)
    ]
    expected_cells = len(columns) * len(rows)
    mapped_cells = 0
    missing_cells: list[dict[str, int]] = []

    for row_index, row in enumerate(grid):
        if not isinstance(row, list):
            continue
        for column_index in range(len(columns)):
            cell = row[column_index] if column_index < len(row) else None
            if not cell or cell.get("empty_cell"):
                missing_cells.append(
                    {
                        "row_index": row_index,
                        "column_index": column_index,
                    }
                )
                continue
            if str(cell.get("source_text") or cell.get("text") or "").strip():
                mapped_cells += 1

    return {
        "columns_detected": len(columns),
        "rows_detected": len(rows),
        "expected_cells": expected_cells,
        "mapped_cells": mapped_cells,
        "missing_cells": len(missing_cells),
        "missing_cells_by_position": missing_cells,
    }


def find_blocks_near_table_regions(
    table_blocks: list[dict[str, Any]],
    remaining_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return compact debug info for candidate blocks close to table regions."""

    near_blocks: list[dict[str, Any]] = []
    for block in remaining_blocks:
        if not is_table_cell_candidate(block):
            continue
        block_bbox = block.get("bbox") or [0, 0, 0, 0]
        for table in table_blocks:
            table_bbox = table.get("bbox") or [0, 0, 0, 0]
            same_page = block.get("page_number") == table.get("page_number")
            close_y = abs(float(block_bbox[1]) - float(table_bbox[3])) <= 42
            overlaps_x = (
                float(block_bbox[2]) >= float(table_bbox[0]) - 20
                and float(block_bbox[0]) <= float(table_bbox[2]) + 20
            )
            if same_page and close_y and overlaps_x:
                near_blocks.append(
                    {
                        "source_text": block.get("source_text"),
                        "bbox": block_bbox,
                        "nearest_table_id": table.get("table_id"),
                    }
                )
                break
    return near_blocks


def is_table_cell_candidate(block: dict[str, Any]) -> bool:
    """Return whether a block can be considered a simple table cell."""

    if block.get("type") in {"header", "footer", "image", "noise"}:
        return False
    text = normalize_text(str(block.get("source_text") or ""))
    if not text:
        return False
    if len(text.split()) > 6:
        return False
    bbox = block.get("bbox") or []
    if len(bbox) != 4:
        return False
    width = float(bbox[2]) - float(bbox[0])
    height = float(bbox[3]) - float(bbox[1])
    return 8 <= width <= 180 and 5 <= height <= 28


def default_block_style() -> dict[str, Any]:
    """Return a conservative default style for synthetic blocks."""

    return {
        "font": None,
        "size": 10,
        "bold": False,
        "italic": False,
        "color": "#000000",
        "alignment": "left",
    }


def find_duplicate_block_index(
    existing_blocks: list[dict[str, Any]],
    candidate: dict[str, Any],
) -> int | None:
    """Return the index of a duplicate block when one is found."""

    for index, existing in enumerate(existing_blocks):
        if are_duplicate_blocks(existing, candidate):
            return index
    return None


def are_duplicate_blocks(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """Detect duplicate blocks by page, bbox overlap, text similarity and type."""

    if first.get("page_number") != second.get("page_number"):
        return False

    if not are_compatible_block_types(
        str(first.get("type") or ""),
        str(second.get("type") or ""),
    ):
        return False

    first_bbox = first.get("bbox", [0, 0, 0, 0])
    second_bbox = second.get("bbox", [0, 0, 0, 0])
    if bbox_overlap_ratio(first_bbox, second_bbox) <= 0.95:
        return False

    return text_similarity(
        str(first.get("source_text", "")),
        str(second.get("source_text", "")),
    ) >= 0.9


def are_compatible_block_types(first_type: str, second_type: str) -> bool:
    """Return whether two block types may represent the same visual content."""

    if first_type == second_type:
        return True

    compatible_groups = [
        {"title", "paragraph", "unknown"},
        {"header", "footer", "unknown"},
    ]
    return any(
        first_type in group and second_type in group
        for group in compatible_groups
    )


def should_replace_duplicate(existing: dict[str, Any], candidate: dict[str, Any]) -> bool:
    """Prefer the duplicate with more useful semantic and textual information."""

    existing_score = duplicate_quality_score(existing)
    candidate_score = duplicate_quality_score(candidate)
    return candidate_score > existing_score


def duplicate_quality_score(block: dict[str, Any]) -> float:
    """Score one duplicate candidate for retention."""

    block_type = str(block.get("type") or "")
    type_score = {
        "title": 5,
        "paragraph": 4,
        "list_item": 4,
        "caption": 4,
        "footnote": 4,
        "header": 3,
        "footer": 3,
        "unknown": 1,
        "image": 1,
    }.get(block_type, 0)
    source_text = normalize_text(str(block.get("source_text", "")))
    confidence_score = float(block.get("confidence_score") or 0)
    return type_score * 1000 + len(source_text) + confidence_score


def bbox_overlap_ratio(first_bbox: list[float], second_bbox: list[float]) -> float:
    """Return intersection area over the smallest bbox area."""

    if len(first_bbox) != 4 or len(second_bbox) != 4:
        return 0

    first_area = bbox_area(first_bbox)
    second_area = bbox_area(second_bbox)
    if first_area == 0 or second_area == 0:
        return 0

    x0 = max(float(first_bbox[0]), float(second_bbox[0]))
    y0 = max(float(first_bbox[1]), float(second_bbox[1]))
    x1 = min(float(first_bbox[2]), float(second_bbox[2]))
    y1 = min(float(first_bbox[3]), float(second_bbox[3]))
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    return intersection / min(first_area, second_area)


def bbox_area(bbox: list[float]) -> float:
    """Return the area of a bbox."""

    if len(bbox) != 4:
        return 0
    return max(0.0, float(bbox[2]) - float(bbox[0])) * max(
        0.0,
        float(bbox[3]) - float(bbox[1]),
    )


def text_similarity(first_text: str, second_text: str) -> float:
    """Return a normalized similarity ratio for extracted block text."""

    first = normalize_repetition_key(first_text)
    second = normalize_repetition_key(second_text)
    if not first or not second:
        return 0
    if first == second:
        return 1
    return SequenceMatcher(None, first, second).ratio()


def is_decorative_artifact(block: dict[str, Any]) -> bool:
    """Detect isolated labels that usually come from PDF decoration, not prose."""

    block_type = str(block.get("type", "unknown"))
    if block_type in {
        "title",
        "paragraph",
        "list_item",
        "footnote",
        "caption",
        "header",
        "footer",
        "image",
    }:
        return False

    source_text = normalize_text(str(block.get("source_text", "")))
    if not source_text:
        return True

    words = re.findall(r"[A-Za-z]+", source_text)
    if not words:
        return len(source_text) <= 3

    has_terminal_punctuation = bool(re.search(r"[.!?;:]$", source_text))
    has_digit = bool(re.search(r"\d", source_text))
    all_short_words = all(len(word) <= 6 for word in words)
    title_case_ratio = sum(1 for word in words if word[:1].isupper()) / len(words)
    looks_like_label_cluster = (
        1 <= len(words) <= 4
        and not has_terminal_punctuation
        and not has_digit
        and all_short_words
        and title_case_ratio >= 0.6
    )
    if looks_like_label_cluster:
        return True

    return len(source_text) <= 2 and not has_digit


NOISE_PHRASES = {
    "ai-powered",
    "however issues",
    "technology startups",
    "learning",
    "who",
    "what",
    "when",
    "if",
    "one",
    "it",
    "from",
}
PROTECTED_SHORT_TERMS = {"ai", "pdf", "url", "cefr"}


def mark_noise_blocks(blocks: list[dict[str, Any]]) -> None:
    """Mark obvious extraction fragments so they are not translated or overlaid."""

    for block in blocks:
        if is_noise_block(block, blocks):
            block["type"] = "noise"
            block["status"] = "needs_review"
            block["role"] = "noise"
            block["confidence_score"] = 0.2
            warnings = block.setdefault("warnings", [])
            if "noise_block" not in warnings:
                warnings.append("noise_block")


def is_noise_block(
    block: dict[str, Any],
    page_blocks: list[dict[str, Any]] | None = None,
) -> bool:
    """Detect isolated fragments produced by PDF extraction artifacts."""

    block_type = str(block.get("type") or "")
    if block_type in {"image", "header", "footer", "noise"}:
        return False
    if block_type in {"list_item", "caption", "footnote"}:
        return False
    if block_type == "title" and is_likely_valid_short_title(block):
        return False

    source_text = normalize_text(str(block.get("source_text") or ""))
    if not source_text:
        return True

    normalized = normalize_noise_text(source_text)
    if normalized in NOISE_PHRASES:
        return True

    words = re.findall(r"[A-Za-z][A-Za-z-]*", source_text)
    lower_words = [word.lower() for word in words]
    if is_protected_short_text(source_text, lower_words):
        return False

    if is_likely_person_name(words):
        return False

    has_sentence_punctuation = bool(re.search(r"[.!?:;]", source_text))
    has_probable_verb = bool(
        re.search(
            r"\b(is|are|was|were|be|being|been|has|have|had|can|will|would|"
            r"should|could|may|might|do|does|did)\b",
            source_text,
            flags=re.IGNORECASE,
        )
        or re.search(r"\b[A-Za-z]+(?:ed|ing|ize|ise|ates?|ifies?)\b", source_text)
    )

    if 1 <= len(words) <= 3 and not has_sentence_punctuation and not has_probable_verb:
        return True

    if page_blocks and is_contained_in_main_block(block, page_blocks):
        return True

    return False


def normalize_noise_text(source_text: str) -> str:
    """Normalize a candidate noise string for known-fragment matching."""

    normalized = normalize_text(source_text).lower()
    normalized = normalized.strip(".,;:!?()[]{}\"'")
    return re.sub(r"\s+", " ", normalized)


def is_likely_valid_short_title(block: dict[str, Any]) -> bool:
    """Keep real short titles even when they have few words."""

    source_text = normalize_text(str(block.get("source_text") or ""))
    words = re.findall(r"[A-Za-z][A-Za-z-]*", source_text)
    if not words:
        return False

    style = block.get("style") or {}
    font_size = float(style.get("size") or 0)
    if font_size >= 14 and len(source_text) >= 4:
        return True

    title_case_ratio = sum(1 for word in words if word[:1].isupper()) / len(words)
    return len(words) <= 5 and title_case_ratio >= 0.8 and len(source_text) >= 8


def is_protected_short_text(source_text: str, lower_words: list[str]) -> bool:
    """Keep useful acronyms and explicit short technical labels."""

    normalized = normalize_noise_text(source_text)
    if normalized in PROTECTED_SHORT_TERMS:
        return True
    return bool(lower_words) and all(word in PROTECTED_SHORT_TERMS for word in lower_words)


def is_likely_person_name(words: list[str]) -> bool:
    """Keep short proper names such as Emma, Shadow, or David Grey."""

    if not 1 <= len(words) <= 3:
        return False
    return all(word[:1].isupper() and word[1:].islower() for word in words)


def is_contained_in_main_block(
    block: dict[str, Any],
    page_blocks: list[dict[str, Any]],
) -> bool:
    """Detect text fragments already included in a longer nearby main block."""

    source_text = normalize_noise_text(str(block.get("source_text") or ""))
    if len(source_text) < 4:
        return False

    bbox = block.get("bbox", [0, 0, 0, 0])
    for other in page_blocks:
        if other is block:
            continue
        if other.get("page_number") != block.get("page_number"):
            continue
        if other.get("type") not in {"paragraph", "title"}:
            continue

        other_text = normalize_noise_text(str(other.get("source_text") or ""))
        if len(other_text) <= len(source_text) + 20:
            continue
        if source_text not in other_text:
            continue

        other_bbox = other.get("bbox", [0, 0, 0, 0])
        if bbox_overlap_ratio(bbox, other_bbox) > 0.2 or bbox_vertical_distance(
            bbox,
            other_bbox,
        ) <= 8:
            return True

    return False


def bbox_vertical_distance(first_bbox: list[float], second_bbox: list[float]) -> float:
    """Return vertical distance between two bboxes."""

    if len(first_bbox) != 4 or len(second_bbox) != 4:
        return 9999
    if first_bbox[3] < second_bbox[1]:
        return float(second_bbox[1]) - float(first_bbox[3])
    if second_bbox[3] < first_bbox[1]:
        return float(first_bbox[1]) - float(second_bbox[3])
    return 0


def calculate_page_font_average(blocks: list[dict[str, Any]]) -> float:
    """Calculate a simple average font size for title detection."""

    sizes: list[float] = []
    for block in blocks:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span.get("text", "").strip() and span.get("size"):
                    sizes.append(float(span["size"]))

    if not sizes:
        return 0

    return sum(sizes) / len(sizes)


def classify_text_block(
    source_text: str,
    font_size: float | None,
    page_font_average: float,
    bbox: list[float],
    page_height: float,
    style: dict[str, Any],
) -> str:
    """Classify text blocks with lightweight MVP heuristics."""

    text_length = len(source_text)
    is_short = text_length <= 120
    has_many_words = len(source_text.split()) >= 4
    punctuation_density = sum(1 for char in source_text if char in ".,;:!?") / max(
        text_length,
        1,
    )
    is_high_on_page = bbox[1] <= page_height * 0.35
    is_bold = bool(style.get("bold"))

    if is_list_item(source_text):
        return "list_item"

    if is_footnote(source_text, font_size, page_font_average, bbox, page_height):
        return "footnote"

    if is_caption(source_text, font_size, page_font_average):
        return "caption"

    if (
        font_size
        and is_short
        and punctuation_density <= 0.08
        and (
            font_size >= max(14, page_font_average + 1.5)
            or (is_bold and font_size >= page_font_average)
            or (is_high_on_page and font_size >= page_font_average + 1)
        )
    ):
        return "title"

    if has_many_words:
        return "paragraph"

    return "unknown"


def is_footnote(
    source_text: str,
    font_size: float | None,
    page_font_average: float,
    bbox: list[float],
    page_height: float,
) -> bool:
    """Detect small footnote-like text near the bottom of the page."""

    starts_like_note = bool(
        re.match(r"^\s*(\[\d+\]|\d+[\.)]|\d+)\s+", source_text)
    )
    is_small = bool(font_size and page_font_average and font_size <= page_font_average - 1)
    is_low = bbox[1] >= page_height * 0.65
    return starts_like_note and (is_small or is_low)


def is_caption(
    source_text: str,
    font_size: float | None,
    page_font_average: float,
) -> bool:
    """Detect simple figure/table captions."""

    if re.match(r"^\s*(fig\.?|figure|table)\s+\d+", source_text, re.IGNORECASE):
        return True
    return bool(
        font_size
        and page_font_average
        and font_size <= page_font_average - 1
        and source_text.lower().startswith(("source:", "caption:"))
    )


def is_list_item(source_text: str) -> bool:
    """Detect simple bullet, numbered and short Q/A list items."""

    return bool(
        re.match(
            r"^\s*([-*\u2022\u2023\u25aa]|\d+[\.)]|[A-Za-z][\.)])\s+",
            source_text,
        )
        or re.match(r"^\s*(Q|A)\s*[:.-]\s+", source_text, flags=re.IGNORECASE)
    )


def role_for_block_type(block_type: str) -> str | None:
    """Map block type to an optional semantic role."""

    roles = {
        "title": "heading",
        "paragraph": "body",
        "list_item": "list",
        "footnote": "footnote",
        "caption": "caption",
        "header": "page_header",
        "footer": "page_footer",
        "image": "figure",
    }
    return roles.get(block_type)


def confidence_for_block_type(block_type: str) -> float:
    """Return a simple confidence score for heuristic classification."""

    scores = {
        "title": 0.78,
        "paragraph": 0.72,
        "list_item": 0.82,
        "footnote": 0.78,
        "caption": 0.76,
        "header": 0.76,
        "footer": 0.76,
        "image": 0.9,
        "unknown": 0.45,
    }
    return scores.get(block_type, 0.5)


def classify_header_footer(
    block_type: str,
    bbox: list[float],
    page_height: float,
) -> str:
    """Mark blocks in extreme page zones as header/footer."""

    if block_type == "title":
        return block_type

    top_limit = page_height * 0.06
    bottom_limit = page_height * 0.92
    if bbox[1] <= top_limit:
        return "header"
    if bbox[3] >= bottom_limit:
        return "footer"

    return block_type


def merge_text_candidates(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge nearby text blocks that likely belong to one paragraph."""

    merged: list[dict[str, Any]] = []
    for block in blocks:
        if merged and should_merge_blocks(merged[-1], block):
            merge_block_into(merged[-1], block)
            continue
        merged.append(block)
    return merged


def should_merge_blocks(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    """Return whether two text candidates look like consecutive paragraph lines."""

    mergeable_types = {"paragraph", "unknown"}
    if previous.get("type") not in mergeable_types:
        return False
    if current.get("type") not in mergeable_types:
        return False

    previous_bbox = previous.get("bbox", [0, 0, 0, 0])
    current_bbox = current.get("bbox", [0, 0, 0, 0])
    previous_size = float((previous.get("style") or {}).get("size") or 0)
    current_size = float((current.get("style") or {}).get("size") or 0)
    vertical_gap = current_bbox[1] - previous_bbox[3]
    max_gap = max(8.0, previous_size * 1.35)
    x_delta = abs(current_bbox[0] - previous_bbox[0])
    x_aligned = x_delta <= 14
    hanging_indent = 0 <= current_bbox[0] - previous_bbox[0] <= 32
    size_close = abs(previous_size - current_size) <= 2
    same_page = previous.get("page_number") == current.get("page_number")

    return (
        same_page
        and -2.0 <= vertical_gap <= max_gap
        and (x_aligned or hanging_indent)
        and size_close
    )


def merge_block_into(previous: dict[str, Any], current: dict[str, Any]) -> None:
    """Merge current text candidate into previous in place."""

    previous_text = str(previous.get("source_text", ""))
    current_text = str(current.get("source_text", ""))
    if previous_text.endswith("-") and current_text:
        merged_text = f"{previous_text[:-1]}{current_text}"
    else:
        merged_text = f"{previous_text} {current_text}"
    previous["source_text"] = normalize_text(merged_text)
    previous["bbox"] = [
        min(previous["bbox"][0], current["bbox"][0]),
        min(previous["bbox"][1], current["bbox"][1]),
        max(previous["bbox"][2], current["bbox"][2]),
        max(previous["bbox"][3], current["bbox"][3]),
    ]
    previous["type"] = "paragraph"
    previous["role"] = "body"
    previous["confidence_score"] = max(
        float(previous.get("confidence_score") or 0.5),
        float(current.get("confidence_score") or 0.5),
    )


def semantic_merge_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge visually close and semantically complementary text fragments.

    This second-pass merge catches PDF span artifacts that survived line grouping,
    such as an acronym block beside its expansion or tiny fragments glued to the
    beginning of a paragraph. It deliberately avoids page furniture, captions,
    titles and probable multi-column jumps.
    """

    ordered_blocks = sorted(
        blocks,
        key=lambda block: (
            int(block.get("page_number") or 0),
            float((block.get("bbox") or [0, 0, 0, 0])[1]),
            float((block.get("bbox") or [0, 0, 0, 0])[0]),
        ),
    )
    merged: list[dict[str, Any]] = []
    for block in ordered_blocks:
        if not merged:
            merged.append(block)
            continue

        previous = merged[-1]
        score = compute_semantic_merge_score(previous, block)
        if score >= 0.72:
            merge_semantic_block_into(
                previous,
                block,
                reason=semantic_merge_reason(previous, block, score),
            )
            continue

        merged.append(block)

    return remove_residual_contained_fragments(merged)


def compute_semantic_merge_score(
    block_a: dict[str, Any],
    block_b: dict[str, Any],
) -> float:
    """Score whether two extracted blocks belong to the same logical paragraph."""

    if not are_semantic_merge_candidates(block_a, block_b):
        return 0.0

    bbox_a = block_a.get("bbox", [0, 0, 0, 0])
    bbox_b = block_b.get("bbox", [0, 0, 0, 0])
    style_a = block_a.get("style") or {}
    style_b = block_b.get("style") or {}
    text_a = normalize_text(str(block_a.get("source_text") or ""))
    text_b = normalize_text(str(block_b.get("source_text") or ""))

    vertical_gap = bbox_vertical_distance(bbox_a, bbox_b)
    horizontal_gap = bbox_horizontal_distance(bbox_a, bbox_b)
    line_height = max(
        float(style_a.get("size") or 0),
        float(style_b.get("size") or 0),
        10.0,
    )
    x_delta = abs(float(bbox_a[0]) - float(bbox_b[0]))
    same_line = bbox_vertical_overlap_ratio(bbox_a, bbox_b) >= 0.45
    font_close = are_fonts_close(style_a, style_b)
    type_close = are_semantic_types_close(
        str(block_a.get("type") or ""),
        str(block_b.get("type") or ""),
    )
    complementary = are_texts_complementary(text_a, text_b)

    score = 0.0
    if block_a.get("page_number") == block_b.get("page_number"):
        score += 0.15
    if type_close:
        score += 0.18
    if font_close:
        score += 0.17
    if same_line and 0 <= horizontal_gap <= max(90.0, line_height * 8):
        score += 0.25
    elif vertical_gap <= max(10.0, line_height * 0.9) and x_delta <= 28:
        score += 0.24
    elif vertical_gap <= max(14.0, line_height * 1.25) and x_delta <= 70:
        score += 0.14
    if complementary:
        score += 0.25
    if is_short_fragment(text_a) or is_short_fragment(text_b):
        score += 0.08
    if are_probably_different_columns(bbox_a, bbox_b):
        score -= 0.35
    if text_similarity(text_a, text_b) >= 0.9:
        score -= 0.3

    return max(0.0, min(score, 1.0))


def are_semantic_merge_candidates(
    block_a: dict[str, Any],
    block_b: dict[str, Any],
) -> bool:
    """Return whether two blocks are allowed to be considered for semantic merge."""

    if block_a.get("page_number") != block_b.get("page_number"):
        return False

    blocked_types = {"title", "header", "footer", "caption", "footnote", "image", "table", "noise"}
    if block_a.get("type") in blocked_types or block_b.get("type") in blocked_types:
        return False

    text_a = normalize_text(str(block_a.get("source_text") or ""))
    text_b = normalize_text(str(block_b.get("source_text") or ""))
    if not text_a or not text_b:
        return False

    if len(text_a.split()) > 80 or len(text_b.split()) > 80:
        return False

    bbox_a = block_a.get("bbox", [0, 0, 0, 0])
    bbox_b = block_b.get("bbox", [0, 0, 0, 0])
    if are_probably_different_columns(bbox_a, bbox_b):
        return False

    return are_semantic_types_close(
        str(block_a.get("type") or ""),
        str(block_b.get("type") or ""),
    )


def are_semantic_types_close(first_type: str, second_type: str) -> bool:
    """Return whether two block types may form one body paragraph."""

    if first_type == second_type and first_type in {"paragraph", "unknown"}:
        return True
    compatible = {"paragraph", "unknown"}
    return first_type in compatible and second_type in compatible


def are_fonts_close(style_a: dict[str, Any], style_b: dict[str, Any]) -> bool:
    """Return whether font family and size are close enough for merging."""

    size_a = float(style_a.get("size") or 0)
    size_b = float(style_b.get("size") or 0)
    size_close = not size_a or not size_b or abs(size_a - size_b) <= 1.5

    font_a = str(style_a.get("font") or "").lower()
    font_b = str(style_b.get("font") or "").lower()
    if not font_a or not font_b:
        return size_close
    return size_close and font_a == font_b


def are_texts_complementary(first_text: str, second_text: str) -> bool:
    """Detect fragments that look like parts of one sentence or term."""

    first = normalize_text(first_text)
    second = normalize_text(second_text)
    if not first or not second:
        return False
    if normalize_noise_text(first) == normalize_noise_text(second):
        return False
    if normalize_noise_text(first) in normalize_noise_text(second):
        return True
    if normalize_noise_text(second) in normalize_noise_text(first):
        return True
    if is_acronym_expansion_pair(first, second):
        return True
    if first.endswith("-"):
        return True
    if starts_like_sentence_continuation(second):
        return True
    return is_short_fragment(first) or is_short_fragment(second)


def is_acronym_expansion_pair(first_text: str, second_text: str) -> bool:
    """Return whether one text is an acronym and the other expands it."""

    first_words = re.findall(r"[A-Za-z]+", first_text)
    second_words = re.findall(r"[A-Za-z]+", second_text)
    return acronym_matches_words(first_words, second_words) or acronym_matches_words(
        second_words,
        first_words,
    )


def acronym_matches_words(acronym_words: list[str], expansion_words: list[str]) -> bool:
    """Check if a short acronym matches the initials of a neighboring phrase."""

    if len(acronym_words) != 1 or len(expansion_words) < 2:
        return False
    acronym = acronym_words[0]
    if not acronym.isupper() or len(acronym) < 2:
        return False
    initials = "".join(word[0].upper() for word in expansion_words if word)
    return initials.startswith(acronym)


def is_short_fragment(text: str) -> bool:
    """Return whether text is a small fragment likely glued to nearby prose."""

    words = re.findall(r"[A-Za-z0-9-]+", text)
    return 1 <= len(words) <= 3 and len(text) <= 36


def starts_like_sentence_continuation(text: str) -> bool:
    """Return whether text starts as a continuation of a previous line."""

    stripped = text.strip()
    return bool(stripped) and stripped[:1].islower()


def are_probably_different_columns(
    bbox_a: list[float],
    bbox_b: list[float],
) -> bool:
    """Avoid merging blocks that look like separate columns."""

    if len(bbox_a) != 4 or len(bbox_b) != 4:
        return False
    horizontal_gap = bbox_horizontal_distance(bbox_a, bbox_b)
    vertical_overlap = bbox_vertical_overlap_ratio(bbox_a, bbox_b)
    left_delta = abs(float(bbox_a[0]) - float(bbox_b[0]))
    if vertical_overlap >= 0.35 and horizontal_gap > 120:
        return True
    return vertical_overlap >= 0.2 and left_delta > 180


def bbox_horizontal_distance(first_bbox: list[float], second_bbox: list[float]) -> float:
    """Return horizontal distance between two bboxes."""

    if len(first_bbox) != 4 or len(second_bbox) != 4:
        return 9999
    if first_bbox[2] < second_bbox[0]:
        return float(second_bbox[0]) - float(first_bbox[2])
    if second_bbox[2] < first_bbox[0]:
        return float(first_bbox[0]) - float(second_bbox[2])
    return 0


def bbox_vertical_overlap_ratio(first_bbox: list[float], second_bbox: list[float]) -> float:
    """Return vertical intersection over the smallest bbox height."""

    if len(first_bbox) != 4 or len(second_bbox) != 4:
        return 0
    first_height = max(0.0, float(first_bbox[3]) - float(first_bbox[1]))
    second_height = max(0.0, float(second_bbox[3]) - float(second_bbox[1]))
    if not first_height or not second_height:
        return 0
    overlap = max(
        0.0,
        min(float(first_bbox[3]), float(second_bbox[3]))
        - max(float(first_bbox[1]), float(second_bbox[1])),
    )
    return overlap / min(first_height, second_height)


def merge_semantic_block_into(
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    reason: str,
) -> None:
    """Merge a semantic fragment into the previous block with debug metadata."""

    previous_text = str(previous.get("source_text", ""))
    current_text = str(current.get("source_text", ""))
    previous["source_text"] = normalize_text(join_semantic_text(previous_text, current_text))
    previous["bbox"] = union_bbox(previous.get("bbox", [0, 0, 0, 0]), current.get("bbox", [0, 0, 0, 0]))
    if previous.get("type") == "unknown" or current.get("type") == "paragraph":
        previous["type"] = "paragraph"
        previous["role"] = "body"

    merged_from = list(previous.get("merged_from") or [])
    current_label = str(current.get("id") or current.get("source_text") or "unassigned_block")
    merged_from.append(current_label)
    previous["merged_from"] = merged_from
    previous["merge_reason"] = reason
    previous["confidence_score"] = max(
        float(previous.get("confidence_score") or 0.5),
        float(current.get("confidence_score") or 0.5),
    )


def join_semantic_text(first_text: str, second_text: str) -> str:
    """Join semantic fragments while avoiding repeated acronym expansions."""

    first = normalize_text(first_text)
    second = normalize_text(second_text)
    acronym_joined = join_acronym_expansion(first, second)
    if acronym_joined:
        return acronym_joined

    first_key = normalize_noise_text(first)
    second_key = normalize_noise_text(second)
    if first_key and first_key in second_key:
        return second
    if second_key and second_key in first_key:
        return first
    if first.endswith("-"):
        return f"{first[:-1]}{second}"
    return f"{first} {second}"


def join_acronym_expansion(first_text: str, second_text: str) -> str | None:
    """Join acronym + expansion as one clean source phrase."""

    first_words = re.findall(r"[A-Za-z]+", first_text)
    second_words = re.findall(r"[A-Za-z]+", second_text)
    if acronym_matches_words(first_words, second_words):
        return f"{second_text} ({first_text})"
    if acronym_matches_words(second_words, first_words):
        return f"{first_text} ({second_text})"
    return None


def union_bbox(first_bbox: list[float], second_bbox: list[float]) -> list[float]:
    """Return a bbox containing both input bboxes."""

    return [
        round(min(float(first_bbox[0]), float(second_bbox[0])), 2),
        round(min(float(first_bbox[1]), float(second_bbox[1])), 2),
        round(max(float(first_bbox[2]), float(second_bbox[2])), 2),
        round(max(float(first_bbox[3]), float(second_bbox[3])), 2),
    ]


def semantic_merge_reason(
    block_a: dict[str, Any],
    block_b: dict[str, Any],
    score: float,
) -> str:
    """Return a compact debug reason for semantic merge metadata."""

    text_a = str(block_a.get("source_text") or "")
    text_b = str(block_b.get("source_text") or "")
    if is_acronym_expansion_pair(text_a, text_b):
        return "acronym_expansion"
    if is_short_fragment(text_a) or is_short_fragment(text_b):
        return "nearby_short_fragment"
    return f"semantic_score_{score:.2f}"


def remove_residual_contained_fragments(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop tiny fragments already absorbed into a nearby merged block."""

    cleaned: list[dict[str, Any]] = []
    for block in blocks:
        text = normalize_noise_text(str(block.get("source_text") or ""))
        if not is_short_fragment(str(block.get("source_text") or "")):
            cleaned.append(block)
            continue

        contained = False
        for other in blocks:
            if other is block or other.get("page_number") != block.get("page_number"):
                continue
            other_text = normalize_noise_text(str(other.get("source_text") or ""))
            if len(other_text) <= len(text) + 5:
                continue
            if text and text in other_text and bbox_vertical_distance(
                block.get("bbox", [0, 0, 0, 0]),
                other.get("bbox", [0, 0, 0, 0]),
            ) <= 12:
                contained = True
                break
        if not contained:
            cleaned.append(block)
    return cleaned


def extract_image_block(
    document_id: str,
    image_block: dict[str, Any],
    page_number: int,
    image_index: int,
) -> dict[str, Any] | None:
    """Persist a simple native PDF image and return its intermediate block."""

    image_bytes = image_block.get("image")
    if not image_bytes:
        return None

    extension = str(image_block.get("ext") or "png").lower()
    if extension == "jpeg":
        extension = "jpg"

    images_dir = get_images_directory(document_id)
    images_dir.mkdir(parents=True, exist_ok=True)
    image_path = images_dir / f"image_{image_index:03d}.{extension}"
    image_path.write_bytes(image_bytes)

    return {
        "page_number": page_number,
        "source_page": page_number,
        "type": "image",
        "role": "figure",
        "confidence_score": 0.9,
        "source_text": "",
        "translated_text": "",
        "bbox": normalize_bbox(image_block.get("bbox", [0, 0, 0, 0])),
        "style": {
            "font": None,
            "size": None,
            "bold": False,
            "italic": False,
            "color": None,
            "alignment": "center",
        },
        "status": "skipped",
        "warnings": [],
        "image_path": str(image_path),
        "has_possible_text": False,
    }


def mark_repeating_headers_and_footers(pages: list[dict[str, Any]]) -> None:
    """Promote repeated extreme-zone blocks to headers or footers."""

    candidates: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for page in pages:
        page_height = float(page.get("height", 0))
        for block in page.get("blocks", []):
            if block.get("type") not in {"paragraph", "unknown", "header", "footer"}:
                continue
            text_key = normalize_repetition_key(str(block.get("source_text", "")))
            if not text_key:
                continue

            bbox = block.get("bbox", [0, 0, 0, 0])
            zone = None
            if bbox[1] <= page_height * 0.12:
                zone = "header"
            elif bbox[3] >= page_height * 0.88:
                zone = "footer"

            if zone:
                candidates.setdefault((zone, text_key), []).append(block)

    for (zone, _), blocks in candidates.items():
        if len(blocks) < 2:
            continue
        for block in blocks:
            block["type"] = zone
            block["role"] = f"repeating_{zone}"
            block["confidence_score"] = 0.9
            warnings = block.setdefault("warnings", [])
            if "repeating_page_artifact" not in warnings:
                warnings.append("repeating_page_artifact")


def normalize_repetition_key(source_text: str) -> str:
    """Normalize text for repeated header/footer detection."""

    normalized = normalize_text(source_text).lower()
    normalized = re.sub(r"\bpage\s+\d+\b", "page <n>", normalized)
    normalized = re.sub(r"\b\d+\b", "<n>", normalized)
    return normalized


def normalize_bbox(raw_bbox: list[float]) -> list[float]:
    """Round PyMuPDF bbox coordinates for stable JSON output."""

    return [round(float(value), 2) for value in raw_bbox]


def normalize_text(value: str) -> str:
    """Normalize whitespace while preserving readable text."""

    return re.sub(r"\s+", " ", value).strip()
