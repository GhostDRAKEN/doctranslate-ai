"""LLM translation provider with no hard-coded credentials."""

import json
import logging
import re
import time
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from app.core.config import Settings
from app.core.errors import AppError
from app.services.mock_translation_provider import (
    TEXT_BLOCK_TYPES,
    MockTranslationProvider,
)

logger = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class LLMTranslationProvider:
    """Translate document text blocks through an external LLM provider."""

    provider_name = "llm"

    def __init__(
        self,
        settings: Settings,
        client: Any | None = None,
        fallback_provider: MockTranslationProvider | None = None,
    ) -> None:
        self.settings = settings
        self.client = client or self.build_client()
        self.fallback_provider = fallback_provider
        self.document_context: dict[str, Any] = {}

    def set_document_context(self, context: dict[str, Any]) -> None:
        """Set lightweight document context for subsequent translations."""

        self.document_context = context

    def translate_block(self, block: dict) -> bool:
        """Translate one supported block in place without mutating structure."""

        block_type = block.get("type")
        if block_type in TEXT_BLOCK_TYPES:
            return self.translate_text_block(block)

        if block_type == "table":
            return self.translate_table_block(block)

        if block_type == "image":
            warnings = block.setdefault("warnings", [])
            if "image_translation_not_supported" not in warnings:
                warnings.append("image_translation_not_supported")
            block["translated_text"] = ""
            if block.get("has_possible_text"):
                block["status"] = "needs_review"
            return False

        return False

    def translate_text_block(self, block: dict) -> bool:
        """Translate the source_text field of a text block."""

        source_text = str(block.get("source_text", ""))
        if not source_text:
            return False

        try:
            block["translated_text"] = self.translate_text(source_text)
            block["status"] = "translated"
            return True
        except AppError as exc:
            if exc.code == "LLM_RATE_LIMIT_EXCEEDED":
                raise
            return self.handle_translation_failure(block, exc)
        except Exception as exc:
            return self.handle_translation_failure(block, exc)

    def translate_table_block(self, block: dict) -> bool:
        """Translate simple table cells without altering table structure."""

        translated_any = False
        for row in block.get("rows") or []:
            for cell in row.get("cells") or []:
                source_text = str(cell.get("source_text", ""))
                if not source_text:
                    continue
                try:
                    cell["translated_text"] = self.translate_text(source_text)
                    translated_any = True
                except Exception as exc:
                    if not self.fallback_provider:
                        cell["translated_text"] = ""
                        block["status"] = "failed"
                        warnings = block.setdefault("warnings", [])
                        if "translation_failed" not in warnings:
                            warnings.append("translation_failed")
                        logger.warning("LLM table cell translation failed")
                        continue
                    cell["translated_text"] = self.fallback_provider.translate_text(
                        source_text
                    )
                    translated_any = True
                    logger.warning("LLM table cell fallback to mock used")

        if translated_any:
            block["status"] = "translated"

        return translated_any

    def translate_text(self, source_text: str) -> str:
        """Translate a single source text into French."""

        if not self.settings.llm_api_key:
            raise AppError(
                code="TRANSLATION_FAILED",
                message="La cle API LLM est absente.",
            )

        return self.translate_with_openai_compatible(source_text)

    def build_client(self) -> OpenAI:
        """Build an OpenAI-compatible client for OpenAI or Groq."""

        provider = self.settings.llm_provider.lower()
        if provider == "groq":
            return OpenAI(
                api_key=self.settings.llm_api_key or "missing",
                base_url=GROQ_BASE_URL,
                timeout=self.settings.llm_timeout_seconds,
            )
        if provider == "openai":
            return OpenAI(
                api_key=self.settings.llm_api_key or "missing",
                timeout=self.settings.llm_timeout_seconds,
            )

        raise AppError(
            code="TRANSLATION_FAILED",
            message=f"Fournisseur LLM non supporte: {self.settings.llm_provider}.",
        )

    def translate_with_openai_compatible(self, source_text: str) -> str:
        """Call an OpenAI-compatible chat completions API."""

        last_error: Exception | None = None
        for attempt in range(self.settings.llm_max_retries + 1):
            try:
                completion = self.client.chat.completions.create(
                    model=self.settings.llm_model,
                    temperature=0.2,
                    messages=[
                        {
                            "role": "system",
                            "content": build_system_prompt(self.document_context),
                        },
                        {
                            "role": "user",
                            "content": build_user_prompt(
                                source_text,
                                self.document_context,
                            ),
                        },
                    ],
                )
                content = completion.choices[0].message.content
                translated = parse_translated_text(content)
                return preserve_required_tokens(
                    source_text,
                    translated,
                    self.document_context,
                )
            except (
                APIStatusError,
                APITimeoutError,
                APIConnectionError,
                ValueError,
                json.JSONDecodeError,
                Exception,
            ) as exc:
                if is_rate_limit_error(exc):
                    raise AppError(
                        code="LLM_RATE_LIMIT_EXCEEDED",
                        message="La limite Groq a été atteinte. Réessayez plus tard.",
                        status_code=429,
                        details={
                            "provider": self.settings.llm_provider,
                            "model": self.settings.llm_model,
                        },
                    ) from exc
                last_error = exc
                if attempt >= self.settings.llm_max_retries:
                    raise
                logger.warning(
                    "LLM translation retry provider=%s model=%s attempt=%s error=%s",
                    self.settings.llm_provider,
                    self.settings.llm_model,
                    attempt + 1,
                    sanitize_error_message(exc),
                )
                time.sleep(min(0.5 * (attempt + 1), 2.0))

        if last_error:
            raise last_error

        raise ValueError("LLM response is empty")

    def handle_translation_failure(self, block: dict, exc: Exception) -> bool:
        """Fallback to mock or mark block failed after a LLM error."""

        logger.warning(
            "LLM translation failed provider=%s model=%s block_id=%s error=%s %s",
            self.settings.llm_provider,
            self.settings.llm_model,
            block.get("id"),
            type(exc).__name__,
            sanitize_error_message(exc),
        )
        if self.fallback_provider:
            return self.fallback_provider.translate_block(block)

        block["status"] = "failed"
        warnings = block.setdefault("warnings", [])
        if "translation_failed" not in warnings:
            warnings.append("translation_failed")
        return False


def parse_translated_text(content: str | dict[str, Any]) -> str:
    """Parse a provider response and return translated text."""

    if isinstance(content, dict):
        translated_text = content.get("translated_text")
        if not isinstance(translated_text, str) or not translated_text.strip():
            raise ValueError("LLM response missing translated_text")
        return translated_text.strip()

    if not isinstance(content, str) or not content.strip():
        raise ValueError("LLM response is empty")

    stripped = content.strip()
    if stripped.startswith("{"):
        payload = json.loads(stripped)
        translated_text = payload.get("translated_text")
        if not isinstance(translated_text, str) or not translated_text.strip():
            raise ValueError("LLM response missing translated_text")
        return translated_text.strip()

    return stripped


def sanitize_error_message(exc: Exception) -> str:
    """Return an error message that does not expose credentials."""

    message = str(exc)
    if not message:
        return "no error message"

    return message.replace("\n", " ")[:500]


def is_rate_limit_error(exc: Exception) -> bool:
    """Return whether an OpenAI-compatible error is a rate limit failure."""

    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return True

    message = str(exc).lower()
    return "rate_limit_exceeded" in message or "429" in message


def build_system_prompt(context: dict[str, Any]) -> str:
    """Build a context-aware professional translation prompt."""

    return "\n".join(
        [
            "Tu es un traducteur professionnel anglais-francais specialise dans les documents.",
            "Traduis le texte anglais en francais naturel, clair et fidele.",
            "Respecte le ton, le niveau de langue et le contexte.",
            "Ne traduis pas les noms propres.",
            "Conserve les nombres, URLs, acronymes, references et notes.",
            "Ne retourne que la traduction francaise.",
            "Ne garde aucun mot anglais inutile.",
            "Ne commente pas la traduction.",
        ]
    )


def build_user_prompt(source_text: str, context: dict[str, Any]) -> str:
    """Build the user prompt for one logical text block."""

    return "\n".join(
        [
            "Contexte du document :",
            "- langue source : anglais",
            "- langue cible : francais",
            f"- domaine : {context.get('domain', 'general')}",
            f"- public : {context.get('target_audience', 'lecteurs francophones')}",
            f"- ton : {context.get('tone', 'professionnel, naturel et clair')}",
            "",
            f"Resume court : {context.get('summary', '')}",
            f"Noms propres a conserver : {format_list(context.get('proper_nouns', []))}",
            f"Glossaire : {format_glossary(context.get('important_terms', []))}",
            "",
            "Texte a traduire :",
            source_text,
            "",
            "Reponds uniquement avec la traduction francaise.",
        ]
    )


def format_list(values: list[Any]) -> str:
    """Format a list for prompt context."""

    clean_values = [str(value) for value in values if str(value).strip()]
    return ", ".join(clean_values) if clean_values else "aucun"


def format_glossary(terms: list[dict[str, Any]]) -> str:
    """Format glossary source -> target entries."""

    if not terms:
        return "aucun"
    formatted_terms = []
    for term in terms:
        required = "obligatoire" if term.get("required") else "recommande"
        formatted_terms.append(
            f"{term.get('source')} -> {term.get('target')} ({required})"
        )
    return "; ".join(formatted_terms)


def preserve_required_tokens(
    source_text: str,
    translated_text: str,
    context: dict[str, Any] | None = None,
) -> str:
    """Append protected URLs and note numbers if the LLM omitted them."""

    result = translated_text
    protected_tokens = extract_protected_tokens(source_text)
    for proper_noun in (context or {}).get("proper_nouns", []):
        if proper_noun in source_text and proper_noun not in protected_tokens:
            protected_tokens.append(str(proper_noun))

    for token in protected_tokens:
        if token not in result:
            result = f"{result} {token}".strip()
    return result


def extract_protected_tokens(source_text: str) -> list[str]:
    """Extract URLs, note markers, acronyms and numeric references to preserve."""

    patterns = [
        r"https?://[^\s)]+",
        r"\[[0-9A-Za-z]+\]",
        r"\([0-9]+\)",
        r"\b[A-Z]{2,}\b",
    ]
    tokens: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, source_text):
            if match not in tokens:
                tokens.append(match)
    return tokens
