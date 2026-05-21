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
from app.services.storage_service import (
    get_images_directory,
    get_intermediate_path,
    get_source_pdf_path,
)


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
        page_candidates = remove_noise_candidates(page_candidates)
        page_candidates = deduplicate_candidates(page_candidates)
        page_candidates = merge_text_candidates(page_candidates)

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
