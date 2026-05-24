"""Non-blocking quality scoring for translated document blocks."""

import re
from statistics import mean
from typing import Any

TEXT_BLOCK_TYPES = {"title", "paragraph", "list_item", "caption", "footnote"}
QUALITY_WARNINGS = {
    "low_translation_quality",
    "high_overlay_risk",
    "english_residual_detected",
    "low_semantic_consistency",
    "low_semantic_confidence",
}
PROTECTED_ACRONYMS = {"AI", "PDF", "URL", "CEFR", "API", "OCR", "LLM"}
SEMANTIC_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
}
ENGLISH_RESIDUAL_WORDS = {
    "the",
    "and",
    "or",
    "with",
    "from",
    "this",
    "that",
    "agreement",
    "service",
    "customer",
    "shall",
    "will",
    "must",
    "who",
    "what",
    "when",
    "where",
    "why",
    "how",
    "one",
    "it",
}
MINI_SPAN_WORDS = {"who", "what", "when", "one", "it", "fun", "if"}


def score_document_quality(
    payload: dict[str, Any],
    *,
    mock_translation_enabled: bool = True,
) -> dict[str, Any]:
    """Compute block-level and document-level quality signals in place."""

    blocks = collect_blocks(payload)
    sections = payload.get("sections") or []
    section_lookup = build_section_lookup(sections)
    block_occurrences = build_block_occurrences(blocks)

    for block in blocks:
        section = section_lookup.get(str(block.get("id")), {})
        apply_block_quality(
            block,
            section,
            block_occurrences=block_occurrences,
            mock_translation_enabled=mock_translation_enabled,
        )

    payload["document_quality"] = compute_document_quality(blocks)
    return payload


def apply_block_quality(
    block: dict[str, Any],
    section: dict[str, Any] | None,
    *,
    block_occurrences: dict[str, int] | None = None,
    mock_translation_enabled: bool = True,
) -> None:
    """Attach quality scores and warnings to one block."""

    if block.get("type") == "table":
        semantic_score, semantic_category = 0.8, "strong_document_block"
    else:
        semantic_score, semantic_category = compute_semantic_confidence_with_category(
            block,
            section or {},
            block_occurrences=block_occurrences or {},
        )
    block["semantic_confidence_score"] = semantic_score
    block["semantic_category"] = semantic_category
    quality = {
        "translation_quality_score": compute_translation_quality_score(
            block,
            mock_translation_enabled=mock_translation_enabled,
        ),
        "english_residual_score": compute_english_residual_score(block),
        "semantic_consistency_score": compute_semantic_consistency_score(
            block,
            section or {},
        ),
        "overlay_risk_score": compute_overlay_risk_score(block),
    }
    block["quality"] = quality
    if block.get("type") == "table":
        block["table_structure_confidence"] = compute_table_structure_confidence(block)
        block["table_grid_confidence"] = compute_table_grid_confidence(block)
    if block.get("type") != "table":
        apply_quality_warnings(block, quality)
        apply_semantic_warnings(block, semantic_score, semantic_category)


def compute_translation_quality_score(
    block: dict[str, Any],
    *,
    mock_translation_enabled: bool = True,
) -> float:
    """Score whether translated_text looks usable as a French translation."""

    if block.get("type") not in TEXT_BLOCK_TYPES:
        return 0.0

    source_text = normalize_space(str(block.get("source_text") or ""))
    translated_text = normalize_space(str(block.get("translated_text") or ""))
    if not source_text or not translated_text:
        return 0.0

    score = 1.0
    translated_words = word_count(translated_text)
    source_words = max(word_count(source_text), 1)
    length_ratio = translated_words / source_words

    if translated_words < 2 and block.get("type") not in {"title", "caption"}:
        score -= 0.35
    if length_ratio < 0.35 or length_ratio > 2.4:
        score -= 0.25
    if looks_like_garbled_text(translated_text):
        score -= 0.35
    if not mock_translation_enabled and "[FR MOCK]" in translated_text:
        score -= 0.5
    if needs_terminal_punctuation(block, translated_text):
        score -= 0.1
    if translated_text.count("[") != translated_text.count("]"):
        score -= 0.1

    return clamp_score(score)


def compute_english_residual_score(block: dict[str, Any]) -> float:
    """Score probable residual English, where 1 is high residual risk."""

    if block.get("type") not in TEXT_BLOCK_TYPES:
        return 0.0

    translated_text = normalize_space(str(block.get("translated_text") or ""))
    if not translated_text:
        return 0.0

    tokens = re.findall(r"\b[A-Za-z][A-Za-z.-]*\b", translated_text)
    if not tokens:
        return 0.0

    residual_count = 0
    mini_span_count = 0
    for token in tokens:
        normalized = normalize_token(token)
        if is_protected_token(token):
            continue
        if normalized in MINI_SPAN_WORDS:
            mini_span_count += 1
        if normalized in ENGLISH_RESIDUAL_WORDS:
            residual_count += 1

    residual_score = min(0.85, residual_count / max(len(tokens), 1) * 2.4)
    if mini_span_count:
        residual_score += min(0.25, mini_span_count * 0.08)

    return clamp_score(residual_score)


def compute_semantic_consistency_score(
    block: dict[str, Any],
    section: dict[str, Any],
) -> float:
    """Score rough consistency with the section and neighboring content."""

    if block.get("type") not in TEXT_BLOCK_TYPES:
        return 0.0

    source_text = normalize_space(str(block.get("source_text") or ""))
    translated_text = normalize_space(str(block.get("translated_text") or ""))
    if not source_text or not translated_text:
        return 0.0

    score = 0.82
    source_words = max(word_count(source_text), 1)
    translated_words = word_count(translated_text)
    ratio = translated_words / source_words

    if 0.55 <= ratio <= 1.9:
        score += 0.12
    else:
        score -= 0.18

    section_title = normalize_space(str(section.get("title") or ""))
    if section_title and block.get("type") == "title":
        title_overlap = token_overlap(source_text, section_title)
        if title_overlap >= 0.4:
            score += 0.06

    if block.get("type") == "list_item" and not has_list_shape(source_text):
        score -= 0.08
    if is_isolated_fragment(source_text):
        score -= 0.45

    return clamp_score(score)


def compute_semantic_confidence(
    block: dict[str, Any],
    section: dict[str, Any],
) -> float:
    """Score whether a block looks like meaningful document content."""

    score, _category = compute_semantic_confidence_with_category(block, section)
    return score


def compute_semantic_confidence_with_category(
    block: dict[str, Any],
    section: dict[str, Any],
    *,
    block_occurrences: dict[str, int] | None = None,
) -> tuple[float, str]:
    """Return semantic confidence and an internal diagnostic category."""

    block_type = str(block.get("type") or "")
    source_text = normalize_space(str(block.get("source_text") or ""))
    translated_text = normalize_space(str(block.get("translated_text") or ""))
    warnings = block.get("warnings") or []
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", source_text)
    word_total = len(words)

    if block_type not in TEXT_BLOCK_TYPES or not source_text:
        return 0.0, "semantic_noise"

    if "noise_block" in warnings or block_type == "noise":
        return 0.05, "semantic_noise"

    if is_repeated_fragment(source_text, block_occurrences or {}):
        return 0.2, "semantic_noise"

    if is_text_contained_in_section_block(block, section):
        return 0.25, "merged_fragment"

    if is_standalone_acronym(source_text):
        if has_contextual_section_signal(source_text, section):
            return 0.5, "contextual_acronym"
        return 0.2, "probable_fragment"

    if is_mini_span(source_text, block_type):
        return 0.25, "probable_fragment"

    score = 0.52
    if word_total >= 6:
        score += 0.22
    elif word_total >= 4:
        score += 0.12

    if has_sentence_shape(source_text):
        score += 0.16
    if translated_text:
        score += 0.05
    if block_type == "title":
        score += title_confidence_bonus(block, source_text)
    if block_type == "list_item" and has_list_shape(source_text):
        score += 0.08
    if source_text in translated_text and translated_text != source_text:
        score -= 0.05
    if lacks_document_signal(source_text, block_type):
        score -= 0.18
    if block_is_merged(block):
        score += 0.08
    if has_contextual_section_signal(source_text, section):
        score += 0.08

    score = clamp_score(score)
    if score >= 0.75:
        return score, "strong_document_block"
    if score < 0.35:
        return score, "semantic_noise"
    if score < 0.55:
        return score, "probable_fragment"
    if block_is_merged(block):
        return score, "merged_fragment"
    return score, "strong_document_block"


def compute_overlay_risk_score(block: dict[str, Any]) -> float:
    """Score overlay risk, where 1 is high risk and 0 is low risk."""

    if block.get("type") not in TEXT_BLOCK_TYPES:
        return 0.0

    bbox = block.get("bbox") or []
    translated_text = normalize_space(str(block.get("translated_text") or ""))
    source_text = normalize_space(str(block.get("source_text") or ""))
    if len(bbox) != 4 or not translated_text:
        return 0.0

    width = max(0.0, float(bbox[2]) - float(bbox[0]))
    height = max(0.0, float(bbox[3]) - float(bbox[1]))
    font_size = float((block.get("style") or {}).get("size") or 10)
    source_chars = max(len(source_text), 1)
    length_ratio = len(translated_text) / source_chars

    risk = 0.0
    if width < max(80.0, font_size * 8):
        risk += 0.25
    if height < max(12.0, font_size * 1.25):
        risk += 0.2
    if length_ratio > 1.45:
        risk += min(0.35, (length_ratio - 1.45) * 0.22)
    if estimated_line_count(translated_text, width, font_size) * font_size * 1.2 > height:
        risk += 0.25
    if "overflow_risk" in (block.get("warnings") or []):
        risk += 0.35

    return clamp_score(risk)


def compute_document_quality(blocks: list[dict[str, Any]]) -> dict[str, float | int]:
    """Aggregate document quality metrics from scored text blocks."""

    text_blocks = [block for block in blocks if block.get("type") in TEXT_BLOCK_TYPES]
    if not text_blocks:
        return {
            "average_translation_quality": 0.0,
            "average_english_residual_score": 0.0,
            "average_semantic_consistency": 0.0,
            "average_overlay_risk": 0.0,
            "blocks_needing_review": 0,
            "total_blocks_scored": 0,
        }

    quality_values = [block.get("quality") or {} for block in text_blocks]
    review_blocks = [
        block
        for block in text_blocks
        if block.get("status") == "needs_review" or block.get("warnings")
    ]
    return {
        "average_translation_quality": round(
            mean(
                float(quality.get("translation_quality_score") or 0.0)
                for quality in quality_values
            ),
            3,
        ),
        "average_english_residual_score": round(
            mean(
                float(quality.get("english_residual_score") or 0.0)
                for quality in quality_values
            ),
            3,
        ),
        "average_semantic_consistency": round(
            mean(
                float(quality.get("semantic_consistency_score") or 0.0)
                for quality in quality_values
            ),
            3,
        ),
        "average_overlay_risk": round(
            mean(
                float(quality.get("overlay_risk_score") or 0.0)
                for quality in quality_values
            ),
            3,
        ),
        "blocks_needing_review": len(review_blocks),
        "total_blocks_scored": len(text_blocks),
    }


def compute_table_structure_confidence(block: dict[str, Any]) -> float:
    """Score MVP table structure quality without blocking rendering."""

    return compute_table_grid_confidence(block)


def compute_table_grid_confidence(block: dict[str, Any]) -> float:
    """Score table grid quality, including columns, rows and missing cells."""

    if block.get("type") != "table":
        return 0.0

    rows = block.get("rows") or []
    columns = block.get("columns") or []
    grid = block.get("grid") or [row.get("cells") or [] for row in rows]
    if len(rows) < 2:
        return 0.0

    column_counts = [len(row.get("cells") or []) for row in rows]
    if not column_counts or min(column_counts) < 2:
        return 0.0

    expected_columns = max(set(column_counts), key=column_counts.count)
    consistent_rows = sum(1 for count in column_counts if count == expected_columns)
    total_cells = 0
    filled_cells = 0
    aligned_cells = 0
    empty_cells = 0
    weak_cells = 0
    empty_and_weak_cells = 0
    for row in rows:
        for column_index, cell in enumerate(row.get("cells") or []):
            total_cells += 1
            if str(cell.get("source_text") or cell.get("text") or "").strip():
                filled_cells += 1
            if int(cell.get("column") or 0) == column_index:
                aligned_cells += 1
            if cell.get("empty_cell"):
                empty_cells += 1
            if cell.get("weak_alignment"):
                weak_cells += 1
            if cell.get("empty_cell") and cell.get("weak_alignment"):
                empty_and_weak_cells += 1

    consistency = consistent_rows / len(rows)
    fill = filled_cells / max(total_cells, 1)
    alignment = aligned_cells / max(total_cells, 1)
    column_score = min(1.0, len(columns) / max(expected_columns, 1)) if columns else 0.0
    total_cell_count = max(total_cells, 1)
    missing_penalty = min(0.3, empty_cells / total_cell_count * 0.55)
    weak_penalty = min(0.25, weak_cells / total_cell_count * 0.45)
    combined_penalty = min(
        0.2,
        empty_and_weak_cells / total_cell_count * 0.35,
    )
    incomplete_grid_penalty = grid_incompleteness_penalty(grid, expected_columns)
    grid_score = 0.0 if not grid else max(0.0, 1.0 - missing_penalty - weak_penalty)
    score = (
        (consistency * 0.25)
        + (fill * 0.2)
        + (alignment * 0.2)
        + (column_score * 0.2)
        + (grid_score * 0.15)
    )
    score = max(0.0, score - combined_penalty - incomplete_grid_penalty)
    warnings = block.setdefault("warnings", [])
    if score < 0.65 and "table_detection_uncertain" not in warnings:
        warnings.append("table_detection_uncertain")
    if score < 0.6 and "weak_table_grid" not in warnings:
        warnings.append("weak_table_grid")
    return clamp_score(score)


def grid_incompleteness_penalty(grid: list[list[dict[str, Any]]], expected_columns: int) -> float:
    """Return an explicit penalty for rows that do not match the expected width."""

    if not grid:
        return 0.08

    inconsistent_rows = sum(1 for row in grid if len(row) != expected_columns)
    if inconsistent_rows == 0:
        return 0.0
    return min(0.18, inconsistent_rows / len(grid) * 0.18)


def apply_quality_warnings(block: dict[str, Any], quality: dict[str, float]) -> None:
    """Attach quality warnings without removing existing functional warnings."""

    warnings = block.setdefault("warnings", [])
    for warning in QUALITY_WARNINGS:
        if warning in warnings:
            warnings.remove(warning)

    if quality["translation_quality_score"] < 0.55:
        warnings.append("low_translation_quality")
    if quality["semantic_consistency_score"] < 0.55:
        warnings.append("low_semantic_consistency")
    if quality["overlay_risk_score"] > 0.55:
        warnings.append("high_overlay_risk")
    if quality["english_residual_score"] > 0.25:
        warnings.append("english_residual_detected")


def apply_semantic_warnings(
    block: dict[str, Any],
    semantic_score: float,
    semantic_category: str,
) -> None:
    """Attach semantic confidence warnings without deleting blocks."""

    warnings = block.setdefault("warnings", [])
    for warning in ("low_semantic_confidence", "semantic_noise", "probable_fragment"):
        if warning in warnings:
            warnings.remove(warning)

    if semantic_category == "semantic_noise":
        warnings.append("semantic_noise")
    elif semantic_category == "probable_fragment":
        warnings.append("probable_fragment")
    elif semantic_score < 0.45:
        warnings.append("low_semantic_confidence")


def collect_blocks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect every block from the intermediate payload."""

    return [
        block
        for page in payload.get("pages", [])
        for block in page.get("blocks", [])
    ]


def build_section_lookup(sections: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map block ids to the section that contains them."""

    lookup: dict[str, dict[str, Any]] = {}
    for section in sections:
        for block_id in section.get("block_ids") or []:
            lookup[str(block_id)] = section
    return lookup


def build_block_occurrences(blocks: list[dict[str, Any]]) -> dict[str, int]:
    """Count normalized source texts to find repeated fragments."""

    occurrences: dict[str, int] = {}
    for block in blocks:
        text = normalize_semantic_text(str(block.get("source_text") or ""))
        if not text:
            continue
        occurrences[text] = occurrences.get(text, 0) + 1
    return occurrences


def is_repeated_fragment(text: str, block_occurrences: dict[str, int]) -> bool:
    """Return True for repeated short fragments that often come from PDF spans."""

    normalized = normalize_semantic_text(text)
    if not normalized:
        return False
    return block_occurrences.get(normalized, 0) > 1 and word_count(text) <= 4


def is_text_contained_in_section_block(
    block: dict[str, Any],
    section: dict[str, Any],
) -> bool:
    """Detect mini-spans already represented by a larger block in the section."""

    text = normalize_semantic_text(str(block.get("source_text") or ""))
    if not text or word_count(text) > 3:
        return False

    section_blocks = section.get("blocks") or []
    block_id = str(block.get("id") or "")
    for neighbor in section_blocks:
        if str(neighbor.get("id") or "") == block_id:
            continue
        neighbor_text = normalize_semantic_text(str(neighbor.get("source_text") or ""))
        if word_count(neighbor_text) <= word_count(text):
            continue
        if re.search(rf"\b{re.escape(text)}\b", neighbor_text):
            return True
    return False


def is_standalone_acronym(text: str) -> bool:
    """Return True when the block is only one acronym-like token."""

    cleaned = normalize_space(text)
    return bool(re.fullmatch(r"[A-Z][A-Z0-9.-]{1,}", cleaned))


def is_mini_span(text: str, block_type: str) -> bool:
    """Detect short isolated snippets while preserving plausible real titles."""

    words = re.findall(r"[A-Za-z][A-Za-z'-]*", text)
    if len(words) == 0:
        return True
    if block_type == "title" and is_plausible_short_title(text):
        return False
    if len(words) <= 1:
        return True
    return len(words) <= 3 and not has_sentence_shape(text)


def has_sentence_shape(text: str) -> bool:
    """Return True when text has enough structure to be document prose."""

    normalized = normalize_space(text)
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", normalized)
    if len(words) >= 8:
        return True
    return bool(re.search(r"[.!?:;]$", normalized)) and len(words) >= 4


def is_plausible_short_title(text: str) -> bool:
    """Keep short titles when capitalization/style suggests real structure."""

    words = re.findall(r"[A-Za-z][A-Za-z'-]*", text)
    if not 2 <= len(words) <= 4:
        return False
    title_like_words = sum(
        1
        for word in words
        if word[:1].isupper() or word.isupper() or word.lower() in SEMANTIC_STOPWORDS
    )
    return title_like_words == len(words)


def title_confidence_bonus(block: dict[str, Any], text: str) -> float:
    """Boost real-looking short titles without letting random spans dominate."""

    style = block.get("style") or {}
    font_size = float(style.get("size") or 0)
    words = word_count(text)
    bonus = 0.08
    if font_size >= 13:
        bonus += 0.18
    if 2 <= words <= 8 and is_plausible_short_title(text):
        bonus += 0.08
    return bonus


def lacks_document_signal(text: str, block_type: str) -> bool:
    """Return True for short unpunctuated snippets with weak structure."""

    words = word_count(text)
    if block_type == "title" and is_plausible_short_title(text):
        return False
    return words <= 3 and not bool(re.search(r"[.!?:;]$", text))


def block_is_merged(block: dict[str, Any]) -> bool:
    """Return True if extraction marked this block as merged from smaller spans."""

    return bool(block.get("merged_from") or block.get("merge_reason"))


def has_contextual_section_signal(text: str, section: dict[str, Any]) -> bool:
    """Check rough lexical overlap with the section title or summary text."""

    context = " ".join(
        str(section.get(field) or "")
        for field in ("title", "summary", "section_summary")
    )
    return token_overlap(text, context) >= 0.15


def normalize_semantic_text(text: str) -> str:
    """Normalize source text for semantic duplicate/containment checks."""

    return re.sub(r"\s+", " ", text).strip().lower()


def estimated_line_count(text: str, width: float, font_size: float) -> int:
    """Estimate how many lines translated text needs in a bbox."""

    if width <= 0 or font_size <= 0:
        return 999
    average_char_width = font_size * 0.52
    chars_per_line = max(int(width / average_char_width), 1)
    return max(1, (len(text) + chars_per_line - 1) // chars_per_line)


def token_overlap(first: str, second: str) -> float:
    """Compute simple token overlap between two strings."""

    first_tokens = set(re.findall(r"[A-Za-z]+", first.lower()))
    second_tokens = set(re.findall(r"[A-Za-z]+", second.lower()))
    if not first_tokens or not second_tokens:
        return 0.0
    return len(first_tokens & second_tokens) / len(first_tokens | second_tokens)


def needs_terminal_punctuation(block: dict[str, Any], text: str) -> bool:
    """Return whether a prose block appears to miss terminal punctuation."""

    if block.get("type") not in {"paragraph", "footnote"}:
        return False
    if word_count(text) < 6:
        return False
    return not bool(re.search(r"[.!?]$", text))


def is_isolated_fragment(text: str) -> bool:
    """Return whether source text looks like an isolated mini-span."""

    words = re.findall(r"[A-Za-z]+", text.lower())
    return 0 < len(words) <= 2


def looks_like_garbled_text(text: str) -> bool:
    """Detect obvious non-linguistic output."""

    if re.search(r"(.)\1{5,}", text):
        return True
    punctuation_count = sum(1 for char in text if char in "#@$%^*_+=<>|~")
    return punctuation_count >= 3


def has_list_shape(text: str) -> bool:
    """Return whether source text still looks like a list item."""

    return bool(re.match(r"\s*([-*\u2022]|\d+[\.)]|[A-Za-z][\.)])\s+", text))


def normalize_space(text: str) -> str:
    """Normalize text whitespace."""

    return re.sub(r"\s+", " ", text).strip()


def normalize_token(token: str) -> str:
    """Normalize a token for residual detection."""

    return token.strip(".,;:!?()[]{}\"'").lower()


def is_protected_token(token: str) -> bool:
    """Avoid penalizing useful acronyms, URLs and likely proper nouns."""

    if token in PROTECTED_ACRONYMS:
        return True
    if token.startswith(("http", "www")):
        return True
    if token.isupper() and len(token) > 1:
        return True
    return token[:1].isupper() and len(token) > 2


def word_count(text: str) -> int:
    """Count words for heuristic scoring."""

    return len(re.findall(r"\b[\w'-]+\b", text))


def clamp_score(value: float) -> float:
    """Clamp a score to 0..1 and round for stable JSON."""

    return round(max(0.0, min(1.0, value)), 3)
