"""Translation service abstraction for document intermediates."""

import json
import logging
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any

from fastapi import status

from app.core.config import get_settings
from app.core.errors import AppError
from app.schemas.document import DocumentIntermediate
from app.services.batch_service import write_batch_manifests
from app.services.llm_translation_provider import LLMTranslationProvider
from app.services.mock_translation_provider import MockTranslationProvider
from app.services.quality_service import score_document_quality
from app.services.storage_service import (
    document_exists,
    get_intermediate_path,
)

logger = logging.getLogger(__name__)

TEXT_BLOCK_TYPES = {"title", "paragraph", "list_item", "caption", "footnote"}
TRANSLATABLE_BLOCK_TYPES = {*TEXT_BLOCK_TYPES, "table"}
SKIPPED_BLOCK_TYPES = {"header", "footer", "image", "noise", "unknown"}
ISOLATED_FRAGMENT_WORDS = {
    "who",
    "what",
    "when",
    "where",
    "why",
    "how",
    "one",
    "it",
}
ENGLISH_RESIDUAL_WORDS = {
    "who",
    "what",
    "when",
    "if",
    "one",
    "it",
    "from",
    "however",
    "learning",
    "issues",
}
ENGLISH_RESIDUAL_PHRASES = {
    "ai-powered",
    "technology startups",
    "artificial intelligence technology",
    "however issues",
}
PROTECTED_ACRONYMS = {"AI", "API", "CEFR", "HTTP", "IA", "LLM", "OCR", "PDF", "URL"}
PARAGRAPH_RESIDUAL_KEYWORDS = {
    "although",
    "biodiversity",
    "climate",
    "coastal",
    "developing",
    "earth",
    "extreme",
    "global",
    "however",
    "human",
    "it",
    "many",
    "over",
    "rising",
    "scientists",
    "while",
}
TABLE_CELL_PROTECTED_TOKENS = {"IA", "AI", "PDF", "URL", "CEFR"}
TABLE_CELL_RESIDUAL_WORDS = {
    "algorithmic",
    "benefit",
    "consumer",
    "data",
    "faster",
    "higher",
    "improved",
    "job",
    "personalized",
    "privacy",
    "reduced",
    "risk",
    "sales",
}
TABLE_CELL_COVERAGE_HINTS = {
    "algorithmic": {"algorithm", "algorith"},
    "benefit": {"avantage", "benefice", "bénéfice"},
    "consumer": {"consomm"},
    "data": {"donnee", "donnée", "donnees", "données"},
    "faster": {"rapide", "vite"},
    "higher": {"augmentation", "plus", "hausse", "vente"},
    "improved": {"ameliore", "amélior", "securite", "sécurité"},
    "job": {"emploi", "emplois", "travail"},
    "personalized": {"personnalise", "personnalisé"},
    "privacy": {"confidential", "vie privee", "vie privée"},
    "reduced": {"reduit", "réduit", "reduits", "réduits"},
    "risk": {"risque"},
    "sales": {"vente", "ventes"},
}
FRENCH_TABLE_SIGNAL_WORDS = {
    "accidents",
    "algorithme",
    "algorithmique",
    "amelioree",
    "ameliores",
    "biais",
    "confidentialite",
    "detection",
    "emplois",
    "format",
    "plus",
    "problemes",
    "propre",
    "rapide",
    "remplacement",
    "securite",
    "secteur",
    "systeme",
    "valeur",
}
COMMON_ENGLISH_WORDS = {
    "the",
    "and",
    "or",
    "of",
    "to",
    "in",
    "for",
    "with",
    "this",
    "that",
    "agreement",
    "service",
    "customer",
    "party",
    "parties",
    "shall",
    "will",
    "must",
    "may",
    "when",
    "what",
    "who",
}


@dataclass
class DocumentContext:
    """Lightweight context used to improve LLM translation quality."""

    domain: str
    summary: str
    tone: str
    target_audience: str
    important_terms: list[dict[str, Any]]
    proper_nouns: list[str]


class TranslationService:
    """Apply a translation provider to an intermediate document."""

    def __init__(
        self,
        provider: MockTranslationProvider | LLMTranslationProvider | None = None,
    ) -> None:
        self.provider = provider or build_translation_provider()

    def translate_document(self, document_id: str) -> DocumentIntermediate:
        """Translate supported blocks and persist updated intermediate.json."""

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
        context = build_document_context(payload)
        if hasattr(self.provider, "set_document_context"):
            self.provider.set_document_context(context=asdict(context))
        logger.info(
            "Translation started document_id=%s provider=%s",
            document_id,
            self.provider.provider_name,
        )
        translated_count = self.translate_payload(payload)
        settings = get_settings()
        mock_output_allowed = (
            self.provider.provider_name == "mock"
            or settings.mock_translation_enabled
        )
        write_batch_manifests(
            document_id,
            payload,
            batch_size=settings.batch_size_pages,
        )
        score_document_quality(
            payload,
            mock_translation_enabled=mock_output_allowed,
        )
        intermediate = DocumentIntermediate.model_validate(payload)

        intermediate_path.write_text(
            json.dumps(intermediate.model_dump(), ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        logger.info(
            "Translation completed document_id=%s provider=%s translated_blocks=%s",
            document_id,
            self.provider.provider_name,
            translated_count,
        )
        return intermediate

    def translate_payload(self, payload: dict) -> int:
        """Translate supported blocks in an intermediate payload."""

        settings = get_settings()
        mock_output_allowed = (
            self.provider.provider_name == "mock"
            or settings.mock_translation_enabled
        )

        sections = payload.get("sections") or []
        if sections:
            return self.translate_payload_by_sections(
                payload,
                mock_output_allowed=mock_output_allowed,
            )

        translated_count = 0
        for page in payload.get("pages", []):
            for block in page.get("blocks", []):
                if self.translate_single_block(
                    block,
                    mock_translation_enabled=mock_output_allowed,
                ):
                    translated_count += 1
        return translated_count

    def translate_payload_page_range(
        self,
        payload: dict,
        *,
        page_start: int,
        page_end: int,
    ) -> int:
        """Translate only blocks whose page is inside an inclusive page range."""

        settings = get_settings()
        mock_output_allowed = (
            self.provider.provider_name == "mock"
            or settings.mock_translation_enabled
        )
        context = build_document_context(payload)
        if hasattr(self.provider, "set_document_context"):
            self.provider.set_document_context(context=asdict(context))

        translated_count = 0
        for page in payload.get("pages", []):
            page_number = int(page.get("page_number") or 0)
            if not page_start <= page_number <= page_end:
                continue
            for block in page.get("blocks", []):
                if self.translate_single_block(
                    block,
                    mock_translation_enabled=mock_output_allowed,
                ):
                    translated_count += 1
        return translated_count

    def translate_payload_by_sections(
        self,
        payload: dict,
        *,
        mock_output_allowed: bool,
    ) -> int:
        """Translate a document section by section when sections[] is available."""

        translated_count = 0
        document_context = build_document_context(payload)
        document_context_dict = asdict(document_context)
        all_blocks = collect_blocks_in_reading_order(payload)
        block_lookup = {str(block.get("id")): block for block in all_blocks}
        translated_or_checked_ids: set[str] = set()

        for section in payload.get("sections") or []:
            section_blocks = collect_section_blocks(section, block_lookup)
            context_blocks = [
                block
                for block in section_blocks
                if should_translate_block(block)
                and str(block.get("source_text", "")).strip()
                and "noise_block" not in (block.get("warnings") or [])
            ]

            for index, block in enumerate(context_blocks):
                translated_or_checked_ids.add(str(block.get("id")))
                if not should_translate_block(block):
                    mark_skipped_block(block)
                    continue

                if block.get("type") == "table":
                    if self.provider.translate_block(block):
                        clean_table_block_translations(
                            block,
                            mock_translation_enabled=mock_output_allowed,
                        )
                        translated_count += 1
                    continue

                if is_suspicious_fragment(
                    str(block.get("source_text", "")),
                    str(block.get("type") or ""),
                ):
                    mark_needs_review(block, "suspicious_fragment")
                    continue

                previous_text = get_neighbor_text(context_blocks, index - 1)
                next_text = get_neighbor_text(context_blocks, index + 1)
                section_context = build_section_translation_context(
                    section,
                    section_blocks,
                    document_context_dict,
                    previous_text=previous_text,
                    current_text=str(block.get("source_text", "")).strip(),
                    next_text=next_text,
                )
                if hasattr(self.provider, "set_document_context"):
                    self.provider.set_document_context(context=section_context)

                translated = self.provider.translate_block(block)
                validate_translated_block(
                    block,
                    mock_translation_enabled=mock_output_allowed,
                )
                if translated and block.get("status") == "translated":
                    translated_count += 1

            for block in section_blocks:
                block_id = str(block.get("id"))
                if block_id in translated_or_checked_ids:
                    continue
                translated_or_checked_ids.add(block_id)
                if not should_translate_block(block):
                    mark_skipped_block(block)

        for block in all_blocks:
            block_id = str(block.get("id"))
            if block_id in translated_or_checked_ids:
                continue

            if hasattr(self.provider, "set_document_context"):
                self.provider.set_document_context(context=document_context_dict)
            if self.translate_single_block(
                block,
                mock_translation_enabled=mock_output_allowed,
            ):
                translated_count += 1

        return translated_count

    def translate_single_block(
        self,
        block: dict,
        *,
        mock_translation_enabled: bool,
    ) -> bool:
        """Translate one eligible block and apply existing validation rules."""

        if not should_translate_block(block):
            mark_skipped_block(block)
            return False

        if block.get("type") == "table":
            translated = self.provider.translate_block(block)
            if translated:
                clean_table_block_translations(
                    block,
                    mock_translation_enabled=mock_translation_enabled,
                )
            return bool(translated)

        if is_suspicious_fragment(
            str(block.get("source_text", "")),
            str(block.get("type") or ""),
        ):
            mark_needs_review(block, "suspicious_fragment")
            return False

        translated = self.provider.translate_block(block)
        validate_translated_block(
            block,
            mock_translation_enabled=mock_translation_enabled,
        )
        return bool(translated and block.get("status") == "translated")


def translate_document_intermediate(document_id: str) -> DocumentIntermediate:
    """Translate a document intermediate with the configured provider."""

    return TranslationService().translate_document(document_id)


def build_translation_provider() -> MockTranslationProvider | LLMTranslationProvider:
    """Select mock or LLM provider from environment settings."""

    settings = get_settings()
    mock_provider = MockTranslationProvider()
    if settings.mock_translation_enabled:
        return mock_provider

    fallback_provider = mock_provider if settings.llm_fallback_to_mock else None
    return LLMTranslationProvider(
        settings=settings,
        fallback_provider=fallback_provider,
    )


def build_document_context(payload: dict) -> DocumentContext:
    """Build a simple document context before block translation."""

    source_texts = collect_source_texts(payload)
    combined = " ".join(source_texts)
    glossary = payload.get("glossary", [])

    return DocumentContext(
        domain=str(payload.get("domain") or "general"),
        summary=summarize_text(combined),
        tone=infer_tone(combined),
        target_audience=infer_target_audience(payload),
        important_terms=normalize_glossary(glossary),
        proper_nouns=extract_proper_nouns(combined),
    )


def collect_source_texts(payload: dict) -> list[str]:
    """Collect logical text blocks for context generation."""

    texts: list[str] = []
    for page in payload.get("pages", []):
        for block in page.get("blocks", []):
            if block.get("type") in TEXT_BLOCK_TYPES:
                source_text = str(block.get("source_text", "")).strip()
                if source_text:
                    texts.append(source_text)
            elif block.get("type") == "table":
                for row in block.get("rows") or []:
                    for cell in row.get("cells") or []:
                        source_text = str(
                            cell.get("source_text") or cell.get("text") or ""
                        ).strip()
                        if source_text:
                            texts.append(source_text)
    return texts


def collect_blocks_in_reading_order(payload: dict) -> list[dict]:
    """Return every block sorted by page and reading order."""

    blocks: list[dict] = []
    for page in payload.get("pages", []):
        for block in page.get("blocks", []):
            blocks.append(block)

    return sorted(
        blocks,
        key=lambda block: (
            int(block.get("page_number") or 0),
            int(block.get("reading_order") or 0),
            str(block.get("id") or ""),
        ),
    )


def collect_section_blocks(section: dict, block_lookup: dict[str, dict]) -> list[dict]:
    """Resolve section block ids while preserving section reading order."""

    blocks: list[dict] = []
    for block_id in section.get("block_ids") or []:
        block = block_lookup.get(str(block_id))
        if block is not None:
            blocks.append(block)
    return blocks


def get_neighbor_text(blocks: list[dict], index: int) -> str:
    """Return a neighboring block source text for contextual translation."""

    if index < 0 or index >= len(blocks):
        return ""
    return str(blocks[index].get("source_text", "")).strip()


def build_section_translation_context(
    section: dict,
    section_blocks: list[dict],
    document_context: dict[str, Any],
    *,
    previous_text: str,
    current_text: str,
    next_text: str,
) -> dict[str, Any]:
    """Build short section context for translating only the current block.

    The section layer is intentionally additive: it gives the LLM local
    neighborhood context without changing the intermediate block structure.
    """

    context = dict(document_context)
    section_texts = [
        str(block.get("source_text", "")).strip()
        for block in section_blocks
        if should_translate_block(block) and str(block.get("source_text", "")).strip()
    ]
    section_title = str(section.get("title") or "").strip()
    if not section_title:
        section_title = "Untitled section"

    context.update(
        {
            "section_id": section.get("section_id"),
            "section_title": section_title,
            "section_page_start": section.get("page_start"),
            "section_page_end": section.get("page_end"),
            "section_summary": summarize_text(" ".join(section_texts), max_chars=240),
            "previous_text": previous_text,
            "current_text": current_text,
            "next_text": next_text,
        }
    )
    return context


def should_translate_block(block: dict) -> bool:
    """Return whether a block is eligible for LLM/mock translation."""

    if "noise_block" in (block.get("warnings") or []):
        return False
    if block.get("type") == "table":
        return table_has_translatable_cells(block)
    if not str(block.get("source_text", "")).strip():
        return False
    return block.get("type") in TEXT_BLOCK_TYPES


def table_has_translatable_cells(block: dict) -> bool:
    """Return whether a table contains at least one non-empty source cell."""

    for row in block.get("rows") or []:
        for cell in row.get("cells") or []:
            if str(cell.get("source_text") or cell.get("text") or "").strip():
                return True
    return False


def mark_skipped_block(block: dict) -> None:
    """Mark non-translatable blocks without sending them to the provider."""

    block_type = block.get("type")
    if block_type == "image":
        warnings = block.setdefault("warnings", [])
        if "image_translation_not_supported" not in warnings:
            warnings.append("image_translation_not_supported")
        block["translated_text"] = ""
        if block.get("has_possible_text"):
            block["status"] = "needs_review"
        return

    if block_type == "noise":
        warnings = block.setdefault("warnings", [])
        if "noise_block" not in warnings:
            warnings.append("noise_block")
        block["status"] = "needs_review"
        block["translated_text"] = ""
        return

    if "noise_block" in (block.get("warnings") or []):
        block["status"] = "needs_review"
        block["translated_text"] = ""
        return

    if block_type in SKIPPED_BLOCK_TYPES and str(block.get("source_text", "")).strip():
        if block_type == "unknown":
            mark_needs_review(block, "unsupported_text_fragment")
        return


def is_suspicious_fragment(source_text: str, block_type: str = "") -> bool:
    """Detect isolated words and tiny fragments that should not be translated."""

    text = re.sub(r"\s+", " ", source_text).strip()
    if len(text) < 3:
        return True

    words = re.findall(r"[A-Za-z]+", text.lower())
    if not words:
        return True

    if len(words) <= 3 and all(word in ISOLATED_FRAGMENT_WORDS for word in words):
        return True

    if block_type in {"title", "caption", "footnote", "list_item"}:
        return False

    has_sentence_signal = bool(re.search(r"[.!?:;]", text))
    if len(words) <= 2 and not has_sentence_signal:
        return True

    return False


def validate_translated_block(
    block: dict,
    *,
    mock_translation_enabled: bool,
) -> None:
    """Mark suspicious translated text for validation before PDF generation."""

    if block.get("type") not in TEXT_BLOCK_TYPES:
        return

    translated_text = str(block.get("translated_text", "")).strip()
    if not translated_text:
        mark_needs_review(block, "suspicious_translation")
        return

    if not mock_translation_enabled and "[FR MOCK]" in translated_text:
        mark_needs_review(block, "suspicious_translation")
        return

    cleaned_text = clean_translation_artifacts(translated_text)
    if cleaned_text != translated_text:
        block["translated_text"] = cleaned_text
        translated_text = cleaned_text

    if not mock_translation_enabled:
        paragraph_cleaned_text = clean_paragraph_translation_artifacts(
            str(block.get("source_text") or ""),
            translated_text,
        )
        if paragraph_cleaned_text != translated_text:
            block["translated_text"] = paragraph_cleaned_text
            translated_text = paragraph_cleaned_text
            warnings = block.setdefault("warnings", [])
            if "paragraph_english_residual_cleaned" not in warnings:
                warnings.append("paragraph_english_residual_cleaned")
        if paragraph_english_residual_needs_review(
            str(block.get("source_text") or ""),
            translated_text,
        ):
            warnings = block.setdefault("warnings", [])
            if "paragraph_english_residual_needs_review" not in warnings:
                warnings.append("paragraph_english_residual_needs_review")
        if has_too_many_residual_english_words(translated_text):
            mark_needs_review(block, "suspicious_translation")
        if detect_english_residual(translated_text):
            mark_needs_review(block, "english_residual")


def clean_paragraph_translation_artifacts(
    source_text: str,
    translated_text: str,
) -> str:
    """Remove trailing source-keyword residues from translated text blocks."""

    cleaned = re.sub(r"\s+", " ", translated_text).strip()
    if not cleaned or cleaned.startswith("[FR MOCK]"):
        return cleaned

    while True:
        suffix = find_trailing_source_suffix(source_text, cleaned)
        if suffix is None or not should_remove_paragraph_suffix(suffix):
            return cleaned
        cleaned = cleaned[: suffix["start"]].rstrip(" ,;:-")
        if not cleaned:
            return re.sub(r"\s+", " ", translated_text).strip()


def paragraph_english_residual_needs_review(
    source_text: str,
    translated_text: str,
) -> bool:
    """Return whether a text block still ends with a suspicious English suffix."""

    suffix = find_trailing_source_suffix(source_text, translated_text)
    if suffix is None:
        return False
    if is_protected_proper_noun_suffix(
        [str(token) for token in suffix.get("tokens") or []],
        [str(token) for token in suffix.get("normalized_tokens") or []],
    ):
        return False
    return not should_remove_paragraph_suffix(suffix)


def find_trailing_source_suffix(
    source_text: str,
    translated_text: str,
) -> dict[str, Any] | None:
    """Find contiguous trailing words copied from the source text."""

    source_tokens = {
        normalize_table_token(token)
        for token in re.findall(r"[A-Za-z][A-Za-z.-]*", source_text)
    }
    source_tokens.discard("")
    if not source_tokens:
        return None

    matches = list(re.finditer(r"\b[A-Za-z][A-Za-z.-]*\b", translated_text))
    if not matches:
        return None

    suffix_matches: list[re.Match[str]] = []
    for match in reversed(matches):
        token = match.group(0)
        normalized = normalize_table_token(token)
        if not normalized or normalized not in source_tokens:
            break
        if is_protected_paragraph_token(token):
            break
        suffix_matches.insert(0, match)

    if not suffix_matches:
        return None

    suffix_start = suffix_matches[0].start()
    prefix = translated_text[:suffix_start].rstrip()
    suffix_tokens = [match.group(0) for match in suffix_matches]
    suffix_norms = [normalize_table_token(token) for token in suffix_tokens]
    return {
        "start": suffix_start,
        "prefix": prefix,
        "tokens": suffix_tokens,
        "normalized_tokens": suffix_norms,
    }


def should_remove_paragraph_suffix(suffix: dict[str, Any]) -> bool:
    """Return whether a trailing source suffix is very likely an artifact."""

    prefix = str(suffix.get("prefix") or "")
    normalized_tokens = [
        str(token)
        for token in suffix.get("normalized_tokens") or []
        if str(token)
    ]
    tokens = [str(token) for token in suffix.get("tokens") or []]
    if not prefix or not normalized_tokens:
        return False
    if is_protected_proper_noun_suffix(tokens, normalized_tokens):
        return False

    prefix_has_sentence_boundary = prefix[-1:] in {".", "!", "?", ";", ":"}
    contains_residual_keyword = any(
        token in PARAGRAPH_RESIDUAL_KEYWORDS
        for token in normalized_tokens
    )
    if prefix_has_sentence_boundary and contains_residual_keyword:
        return True
    if prefix_has_sentence_boundary and len(normalized_tokens) >= 3:
        return True
    return len(normalized_tokens) >= 4 and contains_residual_keyword


def is_protected_paragraph_token(token: str) -> bool:
    """Return whether a trailing token may legitimately stay untranslated."""

    stripped = token.strip(".,;:!?()[]{}\"'")
    return stripped in PROTECTED_ACRONYMS


def is_protected_proper_noun_suffix(
    tokens: list[str],
    normalized_tokens: list[str],
) -> bool:
    """Keep deliberate proper nouns such as Paris Agreement."""

    if not tokens:
        return False
    if any(token in PARAGRAPH_RESIDUAL_KEYWORDS for token in normalized_tokens):
        return False
    return all(token[:1].isupper() and token[1:].islower() for token in tokens)


def clean_table_block_translations(
    block: dict,
    *,
    mock_translation_enabled: bool,
) -> None:
    """Clean translated table cells in place before quality scoring and overlay."""

    if mock_translation_enabled:
        return

    block_changed = False
    block_needs_review = False
    for row in block.get("rows") or []:
        for cell in row.get("cells") or []:
            source_text = str(cell.get("source_text") or cell.get("text") or "")
            translated_text = str(cell.get("translated_text") or "")
            cleaned_text = clean_table_cell_translation(source_text, translated_text)
            if cleaned_text != translated_text.strip():
                cell["translated_text"] = cleaned_text
                add_cell_warning(cell, "table_cell_english_residual_cleaned")
                block_changed = True
            if table_cell_needs_review(source_text, cleaned_text):
                add_cell_warning(cell, "table_cell_needs_review")
                block_needs_review = True

    warnings = block.setdefault("warnings", [])
    if block_changed and "table_cell_english_residual_cleaned" not in warnings:
        warnings.append("table_cell_english_residual_cleaned")
    if block_needs_review and "table_cell_needs_review" not in warnings:
        warnings.append("table_cell_needs_review")


def clean_table_cell_translation(source_text: str, translated_text: str) -> str:
    """Remove obvious trailing English residues from translated table cells."""

    cleaned = re.sub(r"\s+", " ", translated_text).strip()
    if not cleaned or cleaned.startswith("[FR MOCK]"):
        return cleaned

    source_tokens = {
        normalize_table_token(token)
        for token in re.findall(r"[A-Za-z][A-Za-z-]*", source_text)
    }
    source_tokens.discard("")
    words = cleaned.split()
    changed = False

    while len(words) > 1:
        last_word = words[-1]
        normalized_last = normalize_table_token(last_word)
        if not normalized_last:
            break
        if is_protected_table_cell_token(last_word):
            break
        if normalized_last not in source_tokens:
            break
        if not is_trailing_table_residual(normalized_last, " ".join(words[:-1])):
            break
        words.pop()
        changed = True

    if not changed:
        return cleaned

    return " ".join(words).rstrip(" ,;:-").strip()


def is_trailing_table_residual(normalized_token: str, prefix: str) -> bool:
    """Return whether a trailing source token is likely a table-cell residue."""

    if normalized_token in TABLE_CELL_RESIDUAL_WORDS:
        return True

    hints = TABLE_CELL_COVERAGE_HINTS.get(normalized_token, set())
    normalized_prefix = normalize_table_text(prefix)
    return any(hint in normalized_prefix for hint in hints)


def table_cell_needs_review(source_text: str, translated_text: str) -> bool:
    """Detect a cleaned table cell that still looks suspicious."""

    cleaned = re.sub(r"\s+", " ", translated_text).strip()
    if not cleaned:
        return bool(str(source_text).strip())
    if cleaned.startswith("[FR MOCK]"):
        return False

    tokens = re.findall(r"\b[A-Za-z][A-Za-z-]*\b", cleaned)
    suspicious_tokens = [
        token
        for token in tokens
        if not is_protected_table_cell_token(token)
        and normalize_table_token(token) not in {"le", "la", "les", "de", "des"}
    ]
    has_french_signal = bool(
        re.search(r"[éèêàùçîôû]", cleaned, flags=re.IGNORECASE)
        or re.search(
            r"\b(de|des|du|la|le|les|un|une|d'|l')\b",
            cleaned,
            flags=re.IGNORECASE,
        )
        or any(
            normalize_table_token(token) in FRENCH_TABLE_SIGNAL_WORDS
            for token in tokens
        )
    )
    if suspicious_tokens and not has_french_signal:
        return True
    return any(
        normalize_table_token(token) in TABLE_CELL_RESIDUAL_WORDS
        for token in suspicious_tokens
    )


def add_cell_warning(cell: dict, warning: str) -> None:
    """Attach a warning to a table cell once."""

    warnings = cell.setdefault("warnings", [])
    if warning not in warnings:
        warnings.append(warning)


def normalize_table_token(token: str) -> str:
    """Normalize a table token for source/residue comparisons."""

    stripped = token.strip(".,;:!?()[]{}\"'")
    return normalize_table_text(stripped)


def normalize_table_text(text: str) -> str:
    """Lowercase and remove accents for lightweight bilingual matching."""

    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    return ascii_text.lower()


def is_protected_table_cell_token(token: str) -> bool:
    """Return whether a token is allowed to remain in a table translation."""

    return token.strip(".,;:!?()[]{}\"'") in TABLE_CELL_PROTECTED_TOKENS


def clean_translation_artifacts(translated_text: str) -> str:
    """Remove obvious isolated English artifacts at line ends."""

    lines = translated_text.splitlines() or [translated_text]
    cleaned_lines: list[str] = []
    for line in lines:
        cleaned_line = line.strip()
        cleaned_line = remove_trailing_residual_phrases(cleaned_line)
        words = cleaned_line.split()
        if len(words) > 1 and normalize_token(words[-1]) in ENGLISH_RESIDUAL_WORDS:
            cleaned_line = " ".join(words[:-1]).rstrip(" ,;:-")
        cleaned_lines.append(cleaned_line)

    return "\n".join(line for line in cleaned_lines if line).strip()


def remove_trailing_residual_phrases(text: str) -> str:
    """Remove known English residual phrases only when they are trailing artifacts."""

    cleaned = text
    for phrase in sorted(ENGLISH_RESIDUAL_PHRASES, key=len, reverse=True):
        pattern = re.compile(
            rf"([\s,;:\-.]+){re.escape(phrase)}[\s.!,;:]*$",
            flags=re.IGNORECASE,
        )
        match = pattern.search(cleaned)
        if not match:
            continue
        separator = match.group(1)
        replacement = ". " if "." in separator else ""
        cleaned = pattern.sub(replacement, cleaned).rstrip(" ,;:-")
    return cleaned


def detect_english_residual(translated_text: str) -> bool:
    """Detect isolated English words that should not survive translation."""

    normalized_text = re.sub(r"\s+", " ", translated_text).strip().lower()
    for phrase in ENGLISH_RESIDUAL_PHRASES:
        if re.search(rf"\b{re.escape(phrase)}\b", normalized_text):
            return True

    tokens = re.findall(r"\b[A-Za-z][A-Za-z.-]*\b", translated_text)
    for index, token in enumerate(tokens):
        normalized = normalize_token(token)
        if normalized not in ENGLISH_RESIDUAL_WORDS:
            continue
        if is_protected_translation_token(token, tokens, index):
            continue
        return True
    return False


def normalize_token(token: str) -> str:
    """Normalize a token for lightweight residual detection."""

    return token.strip(".,;:!?()[]{}\"'").lower()


def is_protected_translation_token(
    token: str,
    tokens: list[str],
    index: int,
) -> bool:
    """Avoid flagging proper names and useful acronyms as English residue."""

    if token in PROTECTED_ACRONYMS:
        return True
    if token.isupper() and len(token) > 1:
        return True

    previous_token = tokens[index - 1] if index > 0 else ""
    next_token = tokens[index + 1] if index + 1 < len(tokens) else ""
    is_title_case = token[:1].isupper() and token[1:].islower()
    has_name_neighbor = (
        previous_token[:1].isupper()
        and previous_token[1:].islower()
        or next_token[:1].isupper()
        and next_token[1:].islower()
    )
    return is_title_case and has_name_neighbor


def has_too_many_residual_english_words(translated_text: str) -> bool:
    """Detect rough English residue without rejecting protected names/acronyms."""

    words = re.findall(r"[A-Za-z]+", translated_text.lower())
    if len(words) < 6:
        return False

    english_count = sum(1 for word in words if word in COMMON_ENGLISH_WORDS)
    return english_count >= 3 and english_count / len(words) >= 0.25


def mark_needs_review(block: dict, warning: str) -> None:
    """Set a block as requiring human review with one warning code."""

    block["status"] = "needs_review"
    warnings = block.setdefault("warnings", [])
    if warning not in warnings:
        warnings.append(warning)


def summarize_text(text: str, max_chars: int = 360) -> str:
    """Create a short extractive summary for prompt context."""

    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rsplit(" ", 1)[0] + "..."


def infer_tone(text: str) -> str:
    """Infer a coarse tone from document vocabulary."""

    lower_text = text.lower()
    if any(term in lower_text for term in ("agreement", "liability", "clause")):
        return "juridique, precis et professionnel"
    if any(term in lower_text for term in ("api", "system", "configuration")):
        return "technique, clair et factuel"
    if any(term in lower_text for term in ("abstract", "methodology", "results")):
        return "academique et formel"
    return "professionnel, naturel et clair"


def infer_target_audience(payload: dict) -> str:
    """Infer a simple target audience from domain."""

    domain = str(payload.get("domain") or "general")
    audiences = {
        "legal": "professionnels du droit et parties contractantes",
        "technical": "equipes techniques et chefs de projet",
        "academic": "lecteurs academiques",
        "business": "professionnels metier",
    }
    return audiences.get(domain, "lecteurs professionnels francophones")


def normalize_glossary(glossary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only simple source -> target glossary entries."""

    terms: list[dict[str, Any]] = []
    for term in glossary:
        source = str(term.get("source", "")).strip()
        target = str(term.get("target", "")).strip()
        if not source or not target:
            continue
        terms.append(
            {
                "source": source,
                "target": target,
                "required": bool(term.get("required", False)),
            }
        )
    return terms


def extract_proper_nouns(text: str) -> list[str]:
    """Extract simple proper nouns that should usually stay unchanged."""

    candidates = re.findall(
        r"\b(?:[A-Z][A-Za-z0-9&.-]+)(?:\s+[A-Z][A-Za-z0-9&.-]+)*\b",
        text,
    )
    stopwords = {
        "The",
        "This",
        "These",
        "A",
        "An",
        "In",
        "On",
        "For",
        "Section",
        "Article",
    }
    proper_nouns: list[str] = []
    for candidate in candidates:
        cleaned = candidate.strip()
        if cleaned in stopwords or len(cleaned) < 2:
            continue
        if cleaned not in proper_nouns:
            proper_nouns.append(cleaned)
    return proper_nouns[:20]
