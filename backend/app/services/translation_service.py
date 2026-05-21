"""Translation service abstraction for document intermediates."""

import json
import logging
import re
from dataclasses import asdict, dataclass
from typing import Any

from fastapi import status

from app.core.config import get_settings
from app.core.errors import AppError
from app.schemas.document import DocumentIntermediate
from app.services.llm_translation_provider import LLMTranslationProvider
from app.services.mock_translation_provider import MockTranslationProvider
from app.services.storage_service import (
    document_exists,
    get_intermediate_path,
)

logger = logging.getLogger(__name__)

TEXT_BLOCK_TYPES = {"title", "paragraph", "list_item", "caption", "footnote"}
SKIPPED_BLOCK_TYPES = {"header", "footer", "image", "unknown", "table"}
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

        translated_count = 0
        settings = get_settings()
        mock_output_allowed = (
            self.provider.provider_name == "mock"
            or settings.mock_translation_enabled
        )
        for page in payload.get("pages", []):
            for block in page.get("blocks", []):
                if not should_translate_block(block):
                    mark_skipped_block(block)
                    continue

                if is_suspicious_fragment(
                    str(block.get("source_text", "")),
                    str(block.get("type") or ""),
                ):
                    mark_needs_review(block, "suspicious_fragment")
                    continue

                translated = self.provider.translate_block(block)
                validate_translated_block(
                    block,
                    mock_translation_enabled=mock_output_allowed,
                )
                if translated and block.get("status") == "translated":
                    translated_count += 1
        return translated_count


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
    return texts


def should_translate_block(block: dict) -> bool:
    """Return whether a block is eligible for LLM/mock translation."""

    return block.get("type") in TEXT_BLOCK_TYPES


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

    if not mock_translation_enabled and has_too_many_residual_english_words(
        translated_text
    ):
        mark_needs_review(block, "suspicious_translation")


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
