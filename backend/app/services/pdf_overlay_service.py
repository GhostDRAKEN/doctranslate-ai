"""MVP translated PDF generation by overlaying text on the source PDF."""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz
from fastapi import status

from app.core.config import get_settings
from app.core.errors import AppError
from app.services.storage_service import (
    document_exists,
    get_intermediate_path,
    get_pdf_result_path,
    get_source_pdf_path,
)

logger = logging.getLogger(__name__)

TEXT_BLOCK_TYPES = {
    "title",
    "paragraph",
    "list_item",
    "footnote",
    "caption",
}

IGNORED_BLOCK_TYPES = {
    "image",
    "header",
    "footer",
    "noise",
    "unknown",
}

MIN_FONT_SIZE = 7.0
DEFAULT_OVERLAY_BBOX_PADDING = 1.5
LOW_QUALITY_THRESHOLD = 0.35
DEFAULT_MIN_SEMANTIC_CONFIDENCE_OVERLAY = 0.45
MAX_EMPTY_TRANSLATION_RATIO = 0.2
MAX_ENGLISH_RESIDUAL_REVIEW_RATIO = 0.3
REVIEW_NOTE_TEXT = "[Traduction à vérifier]"


@dataclass
class OverlayOperation:
    """Prepared translation writing operation for the overlay renderer."""

    block: dict[str, Any]
    rect: fitz.Rect
    text: str
    font_size: float
    overflow: bool
    color: tuple[float, float, float] = (0, 0, 0)


@dataclass
class MaskOperation:
    """Prepared source text masking operation for the overlay renderer."""

    block: dict[str, Any]
    rect: fitz.Rect


def generate_pdf_overlay(document_id: str) -> Path:
    """Generate result.pdf by masking source text and writing translated text."""

    if not document_exists(document_id):
        raise AppError(
            code="DOCUMENT_NOT_FOUND",
            message="Le document demande est introuvable.",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"document_id": document_id},
        )

    intermediate_path = get_intermediate_path(document_id)
    if not intermediate_path.is_file():
        raise AppError(
            code="RESULT_NOT_READY",
            message="La representation intermediaire n'est pas encore disponible.",
            status_code=status.HTTP_409_CONFLICT,
            details={"document_id": document_id},
        )

    payload = json.loads(intermediate_path.read_text(encoding="utf-8"))
    validate_translation_ready(payload)
    source_path = get_source_pdf_path(document_id)
    output_path = get_pdf_result_path(document_id)
    changed = False

    try:
        with fitz.open(source_path) as pdf_document:
            for page_payload in payload.get("pages", []):
                page_number = int(page_payload.get("page_number") or 0)

                if page_number < 1 or page_number > pdf_document.page_count:
                    continue

                page = pdf_document[page_number - 1]
                sorted_blocks = sorted(
                    page_payload.get("blocks", []),
                    key=lambda item: int(item.get("reading_order", 0)),
                )
                mask_operations = prepare_mask_operations(page, sorted_blocks)
                write_operations = prepare_overlay_operations(
                    page,
                    sorted_blocks,
                )
                changed = (
                    apply_overlay_operations(
                        page,
                        mask_operations,
                        write_operations,
                    )
                    or changed
                )

            pdf_document.save(output_path, garbage=4, deflate=True)
    except AppError:
        raise
    except Exception as exc:
        logger.exception("PDF overlay generation failed document_id=%s", document_id)
        raise AppError(
            code="INTERNAL_ERROR",
            message="La generation PDF a echoue.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={"document_id": document_id},
        ) from exc

    if changed:
        intermediate_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    logger.info("PDF overlay generated document_id=%s", document_id)
    return output_path


def validate_translation_ready(payload: dict[str, Any]) -> None:
    """Refuse PDF generation when translated text is not minimally ready."""

    text_blocks = [
        block
        for page in payload.get("pages", [])
        for block in page.get("blocks", [])
        if block.get("type") in TEXT_BLOCK_TYPES
    ]
    translated_blocks = [
        block
        for block in text_blocks
        if str(block.get("translated_text") or "").strip()
        and block.get("status") == "translated"
    ]
    translated_table_blocks = [
        block
        for page in payload.get("pages", [])
        for block in page.get("blocks", [])
        if block.get("type") == "table"
        and block.get("status") == "translated"
        and table_has_translated_cells(block)
    ]

    if not translated_blocks and not translated_table_blocks:
        raise AppError(
            code="TRANSLATION_NOT_READY",
            message="La traduction n'est pas encore disponible.",
            status_code=status.HTTP_409_CONFLICT,
            details=None,
        )

    empty_blocks = [
        block
        for block in text_blocks
        if not str(block.get("translated_text") or "").strip()
        and block.get("status") not in {"skipped", "needs_review"}
    ]
    if text_blocks and len(empty_blocks) / len(text_blocks) > MAX_EMPTY_TRANSLATION_RATIO:
        raise AppError(
            code="TRANSLATION_INCOMPLETE",
            message="La traduction du document est incomplete.",
            status_code=status.HTTP_409_CONFLICT,
            details={
                "text_block_count": len(text_blocks),
                "empty_translation_count": len(empty_blocks),
            },
        )

    residual_blocks = [
        block
        for block in text_blocks
        if block.get("status") == "needs_review"
        and "english_residual" in (block.get("warnings") or [])
    ]
    if (
        text_blocks
        and len(residual_blocks) / len(text_blocks) > MAX_ENGLISH_RESIDUAL_REVIEW_RATIO
    ):
        raise AppError(
            code="TRANSLATION_QUALITY_FAILED",
            message="La traduction contient trop de residus anglais.",
            status_code=status.HTTP_409_CONFLICT,
            details={
                "text_block_count": len(text_blocks),
                "english_residual_count": len(residual_blocks),
            },
        )


def prepare_overlay_operations(
    page: fitz.Page,
    blocks: list[dict[str, Any]],
) -> list[OverlayOperation]:
    """Build translation writing operations before touching the page."""

    operations: list[OverlayOperation] = []

    for block in blocks:
        if block.get("type") == "table":
            operations.extend(prepare_table_overlay_operations(page, block))
            continue
        operation = prepare_overlay_operation(page, block)
        if operation is not None:
            operations.append(operation)

    return operations


def prepare_mask_operations(
    page: fitz.Page,
    blocks: list[dict[str, Any]],
) -> list[MaskOperation]:
    """Build source text masking operations independently from translation."""

    operations: list[MaskOperation] = []
    for block in blocks:
        operation = prepare_mask_operation(page, block)
        if operation is not None:
            operations.append(operation)
    return operations


def prepare_mask_operation(
    page: fitz.Page,
    block: dict[str, Any],
) -> MaskOperation | None:
    """Return a source masking operation for a reliable text block."""

    if not should_mask_source_block(block):
        return None

    rect = rect_from_block(block)
    if rect is None:
        return None

    mask_rect = expand_bbox(rect, page_rect=page.rect)
    if mask_rect.is_empty or mask_rect.is_infinite:
        return None

    return MaskOperation(block=block, rect=mask_rect)


def prepare_overlay_operation(
    page: fitz.Page,
    block: dict[str, Any],
) -> OverlayOperation | None:
    """Return a prepared operation for a valid translated text block."""

    if not should_write_translation(block):
        return None

    rect = rect_from_block(block)
    if rect is None:
        return None

    mask_rect = expand_bbox(rect, page_rect=page.rect)
    if mask_rect.is_empty or mask_rect.is_infinite:
        return None

    text = get_overlay_text(block)
    font_size, overflow = fit_text_to_box(text, mask_rect, block)
    return OverlayOperation(
        block=block,
        rect=mask_rect,
        text=text,
        font_size=font_size,
        overflow=overflow,
    )


def prepare_table_overlay_operations(
    page: fitz.Page,
    block: dict[str, Any],
) -> list[OverlayOperation]:
    """Build cell-level writing operations for a simple table block."""

    operations: list[OverlayOperation] = []
    if not should_write_translation(block):
        return operations
    if is_weak_table_grid(block):
        return [prepare_plain_table_overlay_operation(page, block)]

    for row in iter_table_grid_rows(block):
        for cell in row:
            if cell.get("empty_cell"):
                continue
            text = str(cell.get("translated_text") or "").strip()
            if not text:
                if str(cell.get("source_text") or cell.get("text") or "").strip():
                    text = REVIEW_NOTE_TEXT
                    add_cell_warning(cell, "masked_without_translation")
                else:
                    continue
            rect = rect_from_cell(cell)
            if rect is None:
                continue
            cell_rect = expand_bbox(rect, padding=0.75, page_rect=page.rect)
            font_size, overflow = fit_text_to_box(text, cell_rect, block)
            operations.append(
                OverlayOperation(
                    block=block,
                    rect=cell_rect,
                    text=text,
                    font_size=min(font_size, 9.0),
                    overflow=overflow,
                )
            )

    return operations


def prepare_plain_table_overlay_operation(
    page: fitz.Page,
    block: dict[str, Any],
) -> OverlayOperation:
    """Fallback to a readable line-based table rendering when grid is weak."""

    rect = rect_from_block(block) or page.rect
    table_rect = expand_bbox(rect, page_rect=page.rect)
    text_lines = []
    for row in block.get("rows") or []:
        values = [
            str(
                cell.get("translated_text")
                or cell.get("source_text")
                or cell.get("text")
                or ""
            )
            for cell in row.get("cells") or []
        ]
        if any(value.strip() for value in values):
            text_lines.append(" | ".join(values))

    text = "\n".join(text_lines).strip() or REVIEW_NOTE_TEXT
    font_size, overflow = fit_text_to_box(text, table_rect, block)
    add_warning(block, "weak_table_grid_detection")
    return OverlayOperation(
        block=block,
        rect=table_rect,
        text=text,
        font_size=min(font_size, 9.0),
        overflow=overflow,
        color=(0.15, 0.15, 0.15),
    )


def apply_overlay_operations(
    page: fitz.Page,
    mask_operations: list[MaskOperation] | list[OverlayOperation],
    write_operations: list[OverlayOperation] | None = None,
) -> bool:
    """Apply overlay in two independent passes: mask source, then write French."""

    if write_operations is None:
        write_operations = [
            operation
            for operation in mask_operations
            if isinstance(operation, OverlayOperation)
        ]
        mask_operations = [
            MaskOperation(block=operation.block, rect=operation.rect)
            for operation in write_operations
        ]

    if not mask_operations and not write_operations:
        return False

    settings = get_settings()
    debug_overlay = bool(
        getattr(settings, "debug_overlay", False)
        or getattr(settings, "debug_overlay_bbox", False)
    )
    debug_semantic = bool(getattr(settings, "debug_semantic", False))

    if debug_overlay:
        for operation in mask_operations:
            draw_debug_bbox(
                page,
                operation.rect,
                build_debug_label(operation.block, decision="mask"),
                color=(1, 0, 0),
            )
    else:
        mask_source_text_zones(page, [operation.rect for operation in mask_operations])

    changed = False
    write_keys = {block_key(operation.block) for operation in write_operations}
    fallback_operations: list[OverlayOperation] = []
    for operation in mask_operations:
        if block_key(operation.block) not in write_keys:
            changed = add_warning(
                operation.block,
                "source_masked_translation_rejected",
            ) or changed
            fallback_operation, fallback_changed = prepare_fallback_write_operation(
                operation,
            )
            changed = fallback_changed or changed
            fallback_operations.append(fallback_operation)

    for operation in [*write_operations, *fallback_operations]:
        if debug_overlay:
            draw_debug_bbox(
                page,
                operation.rect,
                build_debug_label(operation.block, decision="write"),
                color=(0, 0.65, 0),
            )
        changed = write_overlay_text(page, operation) or changed
        if debug_semantic:
            draw_semantic_debug(page, operation)

    return changed


def overlay_block(page: fitz.Page, block: dict[str, Any]) -> bool:
    """Overlay one block for low-level tests and compatibility."""

    mask_operation = prepare_mask_operation(page, block)
    write_operation = prepare_overlay_operation(page, block)
    if mask_operation is None and write_operation is None:
        return False

    return apply_overlay_operations(
        page,
        [mask_operation] if mask_operation is not None else [],
        [write_operation] if write_operation is not None else [],
    )


def write_overlay_text(page: fitz.Page, operation: OverlayOperation) -> bool:
    """Write the translated text and persist overlay warnings on the block."""

    result = page.insert_textbox(
        operation.rect,
        operation.text,
        fontsize=operation.font_size,
        fontname="helv",
        color=operation.color,
        align=alignment_for_block(operation.block),
        overlay=True,
    )

    changed = False
    if operation.overflow:
        changed = add_warning(operation.block, "overlay_overflow_risk") or changed
        changed = add_warning(operation.block, "overflow_risk") or changed

    if is_small_bbox(operation.rect):
        changed = add_warning(operation.block, "overlay_small_bbox") or changed

    if result < 0:
        changed = add_warning(operation.block, "overlay_text_truncated") or changed
        write_overflow_fallback_text(page, operation)

    return changed


def prepare_fallback_write_operation(
    mask_operation: MaskOperation,
) -> tuple[OverlayOperation, bool]:
    """Create visible output for a masked block rejected by strict rendering."""

    block = mask_operation.block
    translated_text = get_overlay_text(block)
    changed = False

    if translated_text:
        text = translated_text
        changed = add_warning(block, "overlay_written_with_review") or changed
        color = (0.25, 0.25, 0.25)
    else:
        text = REVIEW_NOTE_TEXT
        changed = add_warning(block, "masked_without_translation") or changed
        color = (0.45, 0.45, 0.45)

    font_size, overflow = fit_text_to_box(text, mask_operation.rect, block)
    return (
        OverlayOperation(
            block=block,
            rect=mask_operation.rect,
            text=text,
            font_size=min(font_size, 9.0),
            overflow=overflow,
            color=color,
        ),
        changed,
    )


def should_mask_source_block(block: dict[str, Any]) -> bool:
    """Return whether source text should be hidden in PASS 1."""

    block_type = str(block.get("type") or "")
    if block_type in {"image", "header", "footer", "noise"}:
        return False
    if block_type not in {*TEXT_BLOCK_TYPES, "table"}:
        return False

    warnings = block.get("warnings") or []
    if "noise_block" in warnings:
        return False

    if block_type == "table":
        return table_has_source_cells(block) and rect_from_block(block) is not None

    if not str(block.get("source_text") or "").strip():
        return False

    rect = rect_from_block(block)
    if rect is None:
        return False

    return has_reliable_bbox(rect)


def should_write_translation(block: dict[str, Any]) -> bool:
    """Return whether translated text should be written in PASS 2."""

    block_type = str(block.get("type") or "")
    if block_type in IGNORED_BLOCK_TYPES:
        return False
    if block_type == "table":
        return table_has_translated_cells(block)
    if block_type not in TEXT_BLOCK_TYPES:
        return False

    warnings = block.get("warnings") or []
    if "english_residual" in warnings:
        return False
    if "noise_block" in warnings:
        return False
    if not is_quality_acceptable(block):
        return False
    if not is_semantic_confidence_acceptable(block):
        return False

    return bool(get_overlay_text(block))


def rect_from_block(block: dict[str, Any]) -> fitz.Rect | None:
    """Build a PyMuPDF rect from a block bbox if possible."""

    bbox = block.get("bbox") or []
    if len(bbox) != 4:
        return None

    try:
        rect = fitz.Rect(
            float(bbox[0]),
            float(bbox[1]),
            float(bbox[2]),
            float(bbox[3]),
        )
    except (TypeError, ValueError):
        return None

    if rect.is_empty or rect.is_infinite:
        return None
    return rect


def rect_from_cell(cell: dict[str, Any]) -> fitz.Rect | None:
    """Build a rect from a table cell bbox."""

    bbox = cell.get("bbox") or []
    if len(bbox) != 4:
        return None
    try:
        rect = fitz.Rect(
            float(bbox[0]),
            float(bbox[1]),
            float(bbox[2]),
            float(bbox[3]),
        )
    except (TypeError, ValueError):
        return None
    if rect.is_empty or rect.is_infinite:
        return None
    return rect


def table_has_source_cells(block: dict[str, Any]) -> bool:
    """Return whether a table has source text to mask."""

    for row in block.get("rows") or []:
        for cell in row.get("cells") or []:
            if str(cell.get("source_text") or cell.get("text") or "").strip():
                return True
    return False


def table_has_translated_cells(block: dict[str, Any]) -> bool:
    """Return whether a table has translated cell content to render."""

    for row in block.get("rows") or []:
        for cell in row.get("cells") or []:
            if str(cell.get("translated_text") or "").strip():
                return True
    return False


def is_weak_table_grid(block: dict[str, Any]) -> bool:
    """Return whether table grid confidence is too low for cell overlay."""

    rows = block.get("rows") or []
    columns = block.get("columns") or []
    grid = block.get("grid") or []
    if not rows or not columns:
        return True
    if not grid and not rows_match_columns(rows, columns):
        return True
    if "weak_table_grid_detection" in (block.get("warnings") or []):
        return True
    if "weak_table_grid" in (block.get("warnings") or []):
        return True

    raw_score = block.get("table_grid_confidence")
    if raw_score is None:
        raw_score = block.get("table_structure_confidence")
    if raw_score is None:
        return False
    try:
        return float(raw_score) < 0.6
    except (TypeError, ValueError):
        return False


def rows_match_columns(
    rows: list[dict[str, Any]],
    columns: list[dict[str, Any]],
) -> bool:
    """Return whether row cells form a usable grid without explicit grid metadata."""

    expected_columns = len(columns)
    if expected_columns < 1:
        return False
    return all(
        len(row.get("cells") or []) == expected_columns
        for row in rows
        if isinstance(row, dict)
    )


def iter_table_grid_rows(block: dict[str, Any]) -> list[list[dict[str, Any]]]:
    """Return table rows as grid lists, preferring explicit grid metadata."""

    rows = [
        row.get("cells") or []
        for row in block.get("rows") or []
        if isinstance(row, dict)
    ]
    if rows:
        return rows

    grid = block.get("grid")
    if isinstance(grid, list) and grid:
        return [row for row in grid if isinstance(row, list)]
    return []


def has_reliable_bbox(rect: fitz.Rect) -> bool:
    """Avoid masking invalid or extremely tiny boxes."""

    return rect.width >= 2 and rect.height >= 2


def expand_bbox(
    rect: fitz.Rect,
    padding: float | None = None,
    page_rect: fitz.Rect | None = None,
) -> fitz.Rect:
    """Expand a bbox slightly and optionally clamp it inside the page."""

    if padding is None:
        padding = float(get_settings().overlay_bbox_padding or DEFAULT_OVERLAY_BBOX_PADDING)

    expanded = fitz.Rect(
        rect.x0 - padding,
        rect.y0 - padding,
        rect.x1 + padding,
        rect.y1 + padding,
    )

    if page_rect is None:
        return expanded

    return fitz.Rect(
        max(page_rect.x0, expanded.x0),
        max(page_rect.y0, expanded.y0),
        min(page_rect.x1, expanded.x1),
        min(page_rect.y1, expanded.y1),
    )


def make_mask_rect(rect: fitz.Rect, page_rect: fitz.Rect) -> fitz.Rect:
    """Backward-compatible wrapper for previous tests/imports."""

    return expand_bbox(rect, page_rect=page_rect)


def mask_source_text_zones(page: fitz.Page, rects: list[fitz.Rect]) -> None:
    """Mask all source text zones in one pass while preserving images/graphics."""

    for rect in rects:
        page.add_redact_annot(rect, fill=(1, 1, 1))

    page.apply_redactions(
        images=fitz.PDF_REDACT_IMAGE_NONE,
        graphics=fitz.PDF_REDACT_LINE_ART_NONE,
        text=fitz.PDF_REDACT_TEXT_REMOVE,
    )


def redact_source_text(page: fitz.Page, rect: fitz.Rect) -> None:
    """Backward-compatible single-zone masking helper."""

    mask_source_text_zones(page, [rect])


def draw_debug_bbox(
    page: fitz.Page,
    rect: fitz.Rect,
    label: str = "",
    color: tuple[float, float, float] = (1, 0, 0),
) -> None:
    """Draw a debug bbox and optional diagnostic label."""

    page.draw_rect(
        rect,
        color=color,
        width=0.8,
        overlay=True,
    )
    if label:
        page.insert_text(
            (rect.x0, max(page.rect.y0 + 7, rect.y0 - 2)),
            label,
            fontsize=6,
            fontname="helv",
            color=color,
            overlay=True,
        )


def fit_text_to_box(
    text: str,
    rect: fitz.Rect,
    block: dict[str, Any] | None = None,
) -> tuple[float, bool]:
    """Reduce font size until text fits the box or reaches the readable minimum."""

    block = block or {}
    style = block.get("style") or {}
    source_size = float(style.get("size") or 12)
    current_size = max(MIN_FONT_SIZE, min(source_size, 18))

    while current_size >= MIN_FONT_SIZE:
        if text_fits(rect, text, current_size, block):
            return current_size, False

        current_size -= 1

    return MIN_FONT_SIZE, True


def is_quality_acceptable(block: dict[str, Any]) -> bool:
    """Skip blocks that the quality service has marked as too weak."""

    quality = block.get("quality")
    if not isinstance(quality, dict):
        return True

    raw_score = quality.get("translation_quality_score")
    if raw_score is None:
        return True

    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        return True

    return score >= LOW_QUALITY_THRESHOLD


def is_semantic_confidence_acceptable(block: dict[str, Any]) -> bool:
    """Return whether the block is semantically strong enough for overlay."""

    if is_protected_short_title(block):
        return True

    category = str(block.get("semantic_category") or "")
    warnings = block.get("warnings") or []
    if category in {"probable_fragment", "semantic_noise"}:
        return False
    if "probable_fragment" in warnings or "semantic_noise" in warnings:
        return False

    raw_score = block.get("semantic_confidence_score")
    if raw_score is None:
        return True

    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        return True

    threshold = float(
        getattr(
            get_settings(),
            "min_semantic_confidence_overlay",
            DEFAULT_MIN_SEMANTIC_CONFIDENCE_OVERLAY,
        )
        or DEFAULT_MIN_SEMANTIC_CONFIDENCE_OVERLAY
    )
    return score >= threshold


def is_protected_short_title(block: dict[str, Any]) -> bool:
    """Keep true short headings such as Introduction and Conclusion renderable."""

    if block.get("type") != "title":
        return False

    text = str(block.get("source_text") or "").strip()
    if not text:
        return False

    words = text.split()
    if len(words) > 4:
        return False

    style = block.get("style") or {}
    font_size = float(style.get("size") or 0)
    is_title_case = all(
        word[:1].isupper() or word.isupper()
        for word in words
        if word
    )
    return font_size >= 12 or is_title_case


def is_small_bbox(rect: fitz.Rect) -> bool:
    """Return True for boxes likely to produce poor overlay rendering."""

    return rect.width < 24 or rect.height < 8


def add_warning(block: dict[str, Any], warning: str) -> bool:
    """Add a warning once and report whether the block changed."""

    warnings = block.setdefault("warnings", [])
    if warning not in warnings:
        warnings.append(warning)
        return True

    return False


def add_cell_warning(cell: dict[str, Any], warning: str) -> bool:
    """Add a warning to a table cell once."""

    warnings = cell.setdefault("warnings", [])
    if warning not in warnings:
        warnings.append(warning)
        return True
    return False


def write_overflow_fallback_text(page: fitz.Page, operation: OverlayOperation) -> None:
    """Write a compact visible fallback when textbox layout rejects the cell."""

    fallback_size = max(5.5, min(operation.font_size, 7.0))
    y = min(operation.rect.y1 - 1, operation.rect.y0 + fallback_size + 1)
    page.insert_text(
        (operation.rect.x0, y),
        operation.text,
        fontsize=fallback_size,
        fontname="helv",
        color=operation.color,
        overlay=True,
    )


def build_debug_label(block: dict[str, Any], *, decision: str) -> str:
    """Build a compact debug label for overlay inspection."""

    block_id = str(block.get("id") or "")
    score = block.get("semantic_confidence_score")
    return f"{decision}:{block_id} sem={score}"


def block_key(block: dict[str, Any]) -> str:
    """Return a stable key for matching mask and write operations."""

    block_id = str(block.get("id") or "")
    if block_id:
        return block_id
    return str(id(block))


def draw_semantic_debug(page: fitz.Page, operation: OverlayOperation) -> None:
    """Write semantic diagnostics near a rendered block in debug mode."""

    score = operation.block.get("semantic_confidence_score")
    category = operation.block.get("semantic_category") or "uncategorized"
    label = f"{score} {category}"
    page.insert_text(
        (operation.rect.x0, min(page.rect.y1 - 2, operation.rect.y1 + 7)),
        label,
        fontsize=5.5,
        fontname="helv",
        color=(0.1, 0.2, 1),
        overlay=True,
    )


def fit_text_size(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    block: dict[str, Any],
) -> tuple[float, bool]:
    """Backward-compatible wrapper for previous tests/imports."""

    return fit_text_to_box(text, rect, block)


def text_fits(
    rect: fitz.Rect,
    text: str,
    font_size: float,
    block: dict[str, Any],
) -> bool:
    """Dry-run textbox insertion on a disposable page to estimate overflow."""

    scratch = fitz.open()

    try:
        scratch_page = scratch.new_page(
            width=max(rect.x1 + 10, rect.width + 20),
            height=max(rect.y1 + 10, rect.height + 20),
        )
        result = scratch_page.insert_textbox(
            rect,
            text,
            fontsize=font_size,
            fontname="helv",
            align=alignment_for_block(block),
        )

        return result >= 0
    finally:
        scratch.close()


def get_overlay_text(block: dict[str, Any]) -> str:
    """Return translated text only.

    Do not fallback to source_text, otherwise untranslated English may be written
    back into the translated PDF.
    """

    return str(block.get("translated_text") or "").strip()


def alignment_for_block(block: dict[str, Any]) -> int:
    """Map block alignment to PyMuPDF textbox alignment constants."""

    alignment = (block.get("style") or {}).get("alignment")

    if alignment == "center":
        return fitz.TEXT_ALIGN_CENTER

    if alignment == "right":
        return fitz.TEXT_ALIGN_RIGHT

    if alignment == "justify":
        return fitz.TEXT_ALIGN_JUSTIFY

    return fitz.TEXT_ALIGN_LEFT
