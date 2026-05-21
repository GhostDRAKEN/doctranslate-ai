"""MVP translated PDF generation by overlaying text on the source PDF."""

import json
import logging
from pathlib import Path
from typing import Any

import fitz
from fastapi import status

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
    "unknown",
}

IGNORED_BLOCK_TYPES = {
    "image",
    "header",
    "footer",
}

MIN_FONT_SIZE = 6.5
MAX_EMPTY_TRANSLATION_RATIO = 0.2


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

                for block in sorted(
                    page_payload.get("blocks", []),
                    key=lambda item: int(item.get("reading_order", 0)),
                ):
                    changed = overlay_block(page, block) or changed

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

    if not translated_blocks:
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


def overlay_block(page: fitz.Page, block: dict[str, Any]) -> bool:
    """Overlay one translated text block. Return True when warnings changed."""

    block_type = str(block.get("type") or "")

    if block_type in IGNORED_BLOCK_TYPES:
        return False

    if block_type not in TEXT_BLOCK_TYPES:
        return False

    text = get_overlay_text(block)
    if not text:
        return False

    bbox = block.get("bbox") or []
    if len(bbox) != 4:
        return False

    rect = fitz.Rect(
        float(bbox[0]),
        float(bbox[1]),
        float(bbox[2]),
        float(bbox[3]),
    )

    if rect.is_empty or rect.is_infinite:
        return False

    safe_rect = make_safe_text_rect(rect)
    if safe_rect.is_empty or safe_rect.is_infinite:
        return False

    font_size, overflow = fit_text_size(page, safe_rect, text, block)

    page.draw_rect(
        safe_rect,
        color=(1, 1, 1),
        fill=(1, 1, 1),
        overlay=True,
    )

    page.insert_textbox(
        safe_rect,
        text,
        fontsize=font_size,
        fontname="helv",
        color=(0, 0, 0),
        align=alignment_for_block(block),
        overlay=True,
    )

    if overflow:
        warnings = block.setdefault("warnings", [])
        if "overflow_risk" not in warnings:
            warnings.append("overflow_risk")
            return True

    return False


def make_safe_text_rect(rect: fitz.Rect) -> fitz.Rect:
    """Shrink the white mask slightly to avoid covering nearby images/graphics."""

    vertical_margin = 1.0
    horizontal_margin = 0.5

    x0 = rect.x0 + horizontal_margin
    y0 = rect.y0 + vertical_margin
    x1 = rect.x1 - horizontal_margin
    y1 = rect.y1 - vertical_margin

    if x1 <= x0:
        x0, x1 = rect.x0, rect.x1

    if y1 <= y0:
        y0, y1 = rect.y0, rect.y1

    return fitz.Rect(x0, y0, x1, y1)


def fit_text_size(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    block: dict[str, Any],
) -> tuple[float, bool]:
    """Find a readable font size that fits the translated text approximately."""

    style = block.get("style") or {}
    source_size = float(style.get("size") or 10)
    max_size = max(MIN_FONT_SIZE, min(source_size, 18))

    current_size = max_size

    while current_size >= MIN_FONT_SIZE:
        if text_fits(page, rect, text, current_size, block):
            return current_size, False

        current_size -= 0.75

    return MIN_FONT_SIZE, True


def text_fits(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    font_size: float,
    block: dict[str, Any],
) -> bool:
    """Dry-run textbox insertion on a disposable page to estimate overflow."""

    scratch = fitz.open()

    try:
        scratch_page = scratch.new_page(width=page.rect.width, height=page.rect.height)

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
