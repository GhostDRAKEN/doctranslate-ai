"""PDF extraction service based on PyMuPDF."""

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import fitz
from fastapi import status

from app.core.config import get_settings
from app.core.errors import AppError
from app.schemas.document import DocumentIntermediate
from app.services.job_service import now_utc
from app.services.storage_service import get_intermediate_path, get_source_pdf_path


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
    if pdf_document.page_count > settings.max_page_count:
        raise AppError(
            code="PDF_TOO_MANY_PAGES",
            message=(
                "Le PDF depasse la limite MVP de "
                f"{settings.max_page_count} pages."
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
            details={
                "page_count": pdf_document.page_count,
                "max_page_count": settings.max_page_count,
            },
        )

    pages: list[dict[str, Any]] = []
    block_index = 1

    for page_number, page in enumerate(pdf_document, start=1):
        raw_blocks = page.get_text("dict").get("blocks", [])
        text_blocks = [block for block in raw_blocks if block.get("type") == 0]
        page_font_average = calculate_page_font_average(text_blocks)
        page_blocks: list[dict[str, Any]] = []

        sorted_blocks = sorted(
            text_blocks,
            key=lambda block: (block.get("bbox", [0, 0, 0, 0])[1], block.get("bbox", [0, 0, 0, 0])[0]),
        )

        for reading_order, block in enumerate(sorted_blocks, start=1):
            source_text = extract_block_text(block)
            if not source_text:
                continue

            style = extract_block_style(block)
            block_type = classify_text_block(source_text, style["size"], page_font_average)
            page_blocks.append(
                {
                    "id": f"block_{block_index:03d}",
                    "page_number": page_number,
                    "type": block_type,
                    "source_text": source_text,
                    "translated_text": "",
                    "bbox": normalize_bbox(block.get("bbox", [0, 0, 0, 0])),
                    "style": style,
                    "reading_order": reading_order,
                    "status": "pending",
                    "warnings": [],
                }
            )
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

    if block_index == 1:
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
) -> str:
    """Classify text blocks with lightweight MVP heuristics."""

    text_length = len(source_text)
    is_short = text_length <= 120
    has_many_words = len(source_text.split()) >= 4

    if font_size and is_short and font_size >= max(14, page_font_average + 1.5):
        return "title"

    if has_many_words:
        return "paragraph"

    return "unknown"


def normalize_bbox(raw_bbox: list[float]) -> list[float]:
    """Round PyMuPDF bbox coordinates for stable JSON output."""

    return [round(float(value), 2) for value in raw_bbox]


def normalize_text(value: str) -> str:
    """Normalize whitespace while preserving readable text."""

    return re.sub(r"\s+", " ", value).strip()
