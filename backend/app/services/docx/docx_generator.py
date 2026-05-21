"""MVP DOCX generator from DocumentIntermediate."""

import json
import logging
import re
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt, RGBColor
from fastapi import status

from app.core.errors import AppError
from app.services.storage_service import (
    document_exists,
    get_docx_result_path,
    get_intermediate_path,
)

logger = logging.getLogger(__name__)


def generate_docx(document_id: str) -> Path:
    """Generate result.docx from intermediate.json."""

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
    document = Document()
    document.core_properties.title = "DocTranslate AI - Result"
    document.add_heading("DocTranslate AI", level=1)

    pages = payload.get("pages", [])
    for page_index, page in enumerate(pages):
        if page_index > 0:
            document.add_page_break()
        append_page(document, page)

    output_path = get_docx_result_path(document_id)
    document.save(output_path)
    logger.info("DOCX generated document_id=%s", document_id)
    return output_path


def append_page(document: Document, page: dict[str, Any]) -> None:
    """Append one intermediate page to the DOCX."""

    blocks = sorted(
        page.get("blocks", []),
        key=lambda block: int(block.get("reading_order", 0)),
    )
    for block in blocks:
        append_block(document, block)


def append_block(document: Document, block: dict[str, Any]) -> None:
    """Append one supported intermediate block to the DOCX."""

    block_type = block.get("type")
    if block_type == "title":
        paragraph = document.add_heading(level=heading_level_for_block(block))
        apply_paragraph_format(paragraph, block, before=10, after=6)
        add_styled_run(paragraph, get_block_output_text(block), block)
        return

    if block_type in {"header", "footer"}:
        if str(block.get("role", "")).startswith("repeating_"):
            return
        append_discrete_text(document, block)
        return

    if block_type == "list_item":
        paragraph = document.add_paragraph(style="List Bullet")
        apply_paragraph_format(paragraph, block, before=0, after=2)
        add_styled_run(paragraph, strip_list_marker(get_block_output_text(block)), block)
        return

    if block_type == "footnote":
        append_footnote_text(document, block)
        return

    if block_type in {"paragraph", "unknown"}:
        paragraph = document.add_paragraph()
        apply_paragraph_format(paragraph, block, before=0, after=6)
        add_styled_run(paragraph, get_block_output_text(block), block)
        return

    if block_type == "table":
        append_table_as_plain_text(document, block)
        return

    if block_type == "image":
        append_image(document, block)


def append_table_as_plain_text(document: Document, block: dict[str, Any]) -> None:
    """Render simple table cells as readable lines for the MVP."""

    for row in block.get("rows") or []:
        cell_texts = [
            str(cell.get("translated_text") or cell.get("source_text") or "")
            for cell in row.get("cells") or []
        ]
        if cell_texts:
            paragraph = document.add_paragraph(" | ".join(cell_texts))
            apply_paragraph_format(paragraph, block, before=0, after=3)


def append_discrete_text(document: Document, block: dict[str, Any]) -> None:
    """Render headers and footers without mixing them with main content."""

    text = get_block_output_text(block)
    if not text:
        return

    paragraph = document.add_paragraph()
    apply_paragraph_format(paragraph, block, before=0, after=2)
    run = paragraph.add_run(text)
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(100, 116, 139)
    run.italic = True


def append_footnote_text(document: Document, block: dict[str, Any]) -> None:
    """Render a footnote-like block as small discreet text."""

    text = get_block_output_text(block)
    if not text:
        return

    paragraph = document.add_paragraph()
    apply_paragraph_format(paragraph, block, before=0, after=2)
    run = paragraph.add_run(text)
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(71, 85, 105)


def append_image(document: Document, block: dict[str, Any]) -> None:
    """Insert a simple extracted image when available."""

    image_path_value = block.get("image_path")
    if not image_path_value:
        return

    image_path = Path(str(image_path_value))
    if not image_path.is_file():
        logger.warning("DOCX image skipped missing_path=%s", image_path.name)
        append_missing_image_note(document)
        return

    try:
        document.add_picture(str(image_path), width=Cm(14))
    except Exception:
        logger.warning("DOCX image insertion failed image=%s", image_path.name)
        append_missing_image_note(document)


def append_missing_image_note(document: Document) -> None:
    """Add a discreet note when an extracted image cannot be inserted."""

    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(2)
    run = paragraph.add_run("[Image non inseree]")
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(100, 116, 139)
    run.italic = True


def add_styled_run(paragraph: Any, text: str, block: dict[str, Any]) -> None:
    """Add text with approximate bold, italic and font size."""

    run = paragraph.add_run(text)
    style = block.get("style") or {}
    run.bold = bool(style.get("bold"))
    run.italic = bool(style.get("italic"))
    if style.get("size"):
        run.font.size = Pt(float(style["size"]))


def apply_paragraph_format(
    paragraph: Any,
    block: dict[str, Any],
    *,
    before: float,
    after: float,
) -> None:
    """Apply approximate alignment and spacing from the source block."""

    paragraph.paragraph_format.space_before = Pt(before)
    paragraph.paragraph_format.space_after = Pt(after)
    alignment = (block.get("style") or {}).get("alignment")
    paragraph.alignment = alignment_to_docx(alignment)


def alignment_to_docx(alignment: str | None) -> WD_ALIGN_PARAGRAPH:
    """Map extracted alignment to python-docx alignment."""

    if alignment == "center":
        return WD_ALIGN_PARAGRAPH.CENTER
    if alignment == "right":
        return WD_ALIGN_PARAGRAPH.RIGHT
    if alignment == "justify":
        return WD_ALIGN_PARAGRAPH.JUSTIFY
    return WD_ALIGN_PARAGRAPH.LEFT


def heading_level_for_block(block: dict[str, Any]) -> int:
    """Choose Heading 1 or Heading 2 from approximate font size."""

    size = (block.get("style") or {}).get("size")
    if size and float(size) >= 18:
        return 1
    return 2


def get_block_output_text(block: dict[str, Any]) -> str:
    """Prefer translated text, falling back to source text."""

    return str(block.get("translated_text") or block.get("source_text") or "")


def strip_list_marker(text: str) -> str:
    """Remove a simple leading list marker for Word list rendering."""

    return re.sub(
        r"^\s*([-*\u2022\u2023\u25aa]|\d+[\.)]|[A-Za-z][\.)]|[QAqa]\s*[:.-])\s+",
        "",
        text,
    )
