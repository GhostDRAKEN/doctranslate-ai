from typing import Any

import pytest

from app.core.errors import AppError
from app.core.config import Settings
from app.services import llm_translation_provider
from app.services.llm_translation_provider import (
    GROQ_BASE_URL,
    LLMTranslationProvider,
    build_system_prompt,
    parse_translated_text,
)
from app.services.mock_translation_provider import MockTranslationProvider
from app.services.translation_service import build_document_context, build_translation_provider


class FakeMessage:
    def __init__(self, translated_text: str) -> None:
        self.content = translated_text


class FakeChoice:
    def __init__(self, translated_text: str) -> None:
        self.message = FakeMessage(translated_text)


class FakeCompletion:
    def __init__(self, translated_text: str) -> None:
        self.choices = [FakeChoice(translated_text)]


class FakeCompletions:
    def __init__(self, owner: "FakeClient") -> None:
        self.owner = owner

    def create(self, **kwargs: Any) -> FakeCompletion:
        self.owner.requests.append(kwargs)
        return FakeCompletion(self.owner.translated_text)


class FakeChat:
    def __init__(self, owner: "FakeClient") -> None:
        self.completions = FakeCompletions(owner)


class FakeClient:
    def __init__(self, translated_text: str = "Texte traduit") -> None:
        self.translated_text = translated_text
        self.requests: list[dict[str, Any]] = []
        self.chat = FakeChat(self)


class EmptyClient(FakeClient):
    def __init__(self) -> None:
        super().__init__("")


class FlakyCompletions:
    def __init__(self, owner: "FlakyClient") -> None:
        self.owner = owner

    def create(self, **kwargs: Any) -> FakeCompletion:
        self.owner.requests.append(kwargs)
        if len(self.owner.requests) == 1:
            raise RuntimeError("temporary provider error")
        return FakeCompletion(self.owner.translated_text)


class FlakyChat:
    def __init__(self, owner: "FlakyClient") -> None:
        self.completions = FlakyCompletions(owner)


class FlakyClient:
    def __init__(self, translated_text: str = "Bonjour apres retry") -> None:
        self.translated_text = translated_text
        self.requests: list[dict[str, Any]] = []
        self.chat = FlakyChat(self)


class FailingCompletions:
    def __init__(self, owner: "FailingClient") -> None:
        self.owner = owner

    def create(self, **_: Any) -> FakeCompletion:
        self.owner.requests += 1
        raise RuntimeError("provider unavailable")


class FailingChat:
    def __init__(self, owner: "FailingClient") -> None:
        self.completions = FailingCompletions(owner)


class FailingClient:
    def __init__(self) -> None:
        self.requests = 0
        self.chat = FailingChat(self)


class RateLimitCompletions:
    def __init__(self, owner: "RateLimitClient") -> None:
        self.owner = owner

    def create(self, **_: Any) -> FakeCompletion:
        self.owner.requests += 1
        raise RuntimeError("429 rate_limit_exceeded")


class RateLimitChat:
    def __init__(self, owner: "RateLimitClient") -> None:
        self.completions = RateLimitCompletions(owner)


class RateLimitClient:
    def __init__(self) -> None:
        self.requests = 0
        self.chat = RateLimitChat(self)


def _settings(**overrides: Any) -> Settings:
    values = {
        "MOCK_TRANSLATION_ENABLED": False,
        "LLM_PROVIDER": "openai",
        "LLM_API_KEY": "test-key",
        "LLM_MODEL": "test-model",
        "LLM_FALLBACK_TO_MOCK": True,
        "LLM_TIMEOUT_SECONDS": 30,
        "LLM_MAX_RETRIES": 1,
    }
    values.update(overrides)
    return Settings(**values)


def test_parse_translated_text_from_json_content() -> None:
    assert parse_translated_text('{"translated_text": "Bonjour"}') == "Bonjour"


def test_parse_translated_text_from_plain_content() -> None:
    assert parse_translated_text("Bonjour le monde") == "Bonjour le monde"


def test_llm_provider_translates_source_text_only_and_preserves_structure() -> None:
    fake_client = FakeClient("Bonjour le monde")
    provider = LLMTranslationProvider(settings=_settings(), client=fake_client)
    block = {
        "id": "block_001",
        "page_number": 1,
        "type": "paragraph",
        "source_text": "Hello world",
        "translated_text": "",
        "bbox": [1, 2, 3, 4],
        "style": {"font": "Arial", "size": 11},
        "status": "pending",
        "warnings": [],
    }

    translated = provider.translate_block(block)

    assert translated is True
    assert block["source_text"] == "Hello world"
    assert block["translated_text"] == "Bonjour le monde"
    assert block["status"] == "translated"
    assert block["bbox"] == [1, 2, 3, 4]
    assert block["style"] == {"font": "Arial", "size": 11}
    assert block["page_number"] == 1
    assert block["type"] == "paragraph"

    request_json = fake_client.requests[0]
    assert request_json["model"] == "test-model"
    assert "Hello world" in request_json["messages"][1]["content"]
    assert "translated_text" not in request_json["messages"][1]["content"]


def test_llm_provider_does_not_send_images() -> None:
    fake_client = FakeClient()
    provider = LLMTranslationProvider(settings=_settings(), client=fake_client)
    block = {
        "type": "image",
        "source_text": "",
        "translated_text": "",
        "warnings": [],
        "has_possible_text": False,
    }

    translated = provider.translate_block(block)

    assert translated is False
    assert fake_client.requests == []
    assert block["translated_text"] == ""
    assert "image_translation_not_supported" in block["warnings"]


def test_llm_provider_falls_back_to_mock_on_failure() -> None:
    provider = LLMTranslationProvider(
        settings=_settings(),
        client=FailingClient(),
        fallback_provider=MockTranslationProvider(),
    )
    block = {
        "id": "block_001",
        "type": "paragraph",
        "source_text": "Hello",
        "translated_text": "",
        "status": "pending",
        "warnings": [],
    }

    translated = provider.translate_block(block)

    assert translated is True
    assert block["translated_text"] == "[FR MOCK] Hello"
    assert block["status"] == "translated"


def test_llm_provider_marks_failed_without_fallback() -> None:
    provider = LLMTranslationProvider(
        settings=_settings(LLM_FALLBACK_TO_MOCK=False),
        client=FailingClient(),
        fallback_provider=None,
    )
    block = {
        "id": "block_001",
        "type": "paragraph",
        "source_text": "Hello",
        "translated_text": "",
        "status": "pending",
        "warnings": [],
    }

    translated = provider.translate_block(block)

    assert translated is False
    assert block["translated_text"] == ""
    assert block["status"] == "failed"
    assert "translation_failed" in block["warnings"]


def test_llm_provider_raises_rate_limit_without_mock_fallback() -> None:
    client = RateLimitClient()
    provider = LLMTranslationProvider(
        settings=_settings(
            LLM_PROVIDER="groq",
            LLM_FALLBACK_TO_MOCK=False,
            LLM_MAX_RETRIES=1,
        ),
        client=client,
        fallback_provider=None,
    )
    block = {
        "id": "block_001",
        "type": "paragraph",
        "source_text": "This agreement defines responsibilities.",
        "translated_text": "",
        "status": "pending",
        "warnings": [],
    }

    with pytest.raises(AppError) as exc_info:
        provider.translate_block(block)

    assert exc_info.value.code == "LLM_RATE_LIMIT_EXCEEDED"
    assert exc_info.value.message == "La limite Groq a été atteinte. Réessayez plus tard."
    assert client.requests == 1
    assert block["translated_text"] == ""


def test_llm_provider_logs_real_error_without_api_key(caplog) -> None:
    provider = LLMTranslationProvider(
        settings=_settings(
            LLM_PROVIDER="groq",
            LLM_API_KEY="secret-key",
            LLM_MODEL="llama-3.3-70b-versatile",
            LLM_FALLBACK_TO_MOCK=False,
            LLM_MAX_RETRIES=0,
        ),
        client=FailingClient(),
        fallback_provider=None,
    )
    block = {
        "id": "block_001",
        "type": "paragraph",
        "source_text": "Hello",
        "translated_text": "",
        "status": "pending",
        "warnings": [],
    }

    with caplog.at_level("WARNING"):
        translated = provider.translate_block(block)

    assert translated is False
    log_text = caplog.text
    assert "provider=groq" in log_text
    assert "model=llama-3.3-70b-versatile" in log_text
    assert "block_id=block_001" in log_text
    assert "RuntimeError" in log_text
    assert "provider unavailable" in log_text
    assert "secret-key" not in log_text


def test_llm_provider_retries_before_success() -> None:
    client = FlakyClient()
    provider = LLMTranslationProvider(
        settings=_settings(LLM_MAX_RETRIES=1),
        client=client,
        fallback_provider=None,
    )
    block = {
        "id": "block_001",
        "type": "paragraph",
        "source_text": "Hello",
        "translated_text": "",
        "status": "pending",
        "warnings": [],
    }

    translated = provider.translate_block(block)

    assert translated is True
    assert block["translated_text"] == "Bonjour apres retry"
    assert len(client.requests) == 2


def test_llm_empty_response_is_failed_without_fallback() -> None:
    provider = LLMTranslationProvider(
        settings=_settings(LLM_FALLBACK_TO_MOCK=False, LLM_MAX_RETRIES=0),
        client=EmptyClient(),
        fallback_provider=None,
    )
    block = {
        "id": "block_001",
        "type": "paragraph",
        "source_text": "Hello",
        "translated_text": "",
        "status": "pending",
        "warnings": [],
    }

    translated = provider.translate_block(block)

    assert translated is False
    assert block["status"] == "failed"
    assert "translation_failed" in block["warnings"]


def test_build_translation_provider_uses_mock_when_enabled(monkeypatch) -> None:
    from app.services import translation_service

    monkeypatch.setattr(
        translation_service,
        "get_settings",
        lambda: _settings(MOCK_TRANSLATION_ENABLED=True),
    )

    provider = build_translation_provider()

    assert isinstance(provider, MockTranslationProvider)


def test_groq_provider_uses_openai_compatible_base_url(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class CapturingOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.chat = FakeChat(FakeClient())

    monkeypatch.setattr(llm_translation_provider, "OpenAI", CapturingOpenAI)

    provider = LLMTranslationProvider(
        settings=_settings(LLM_PROVIDER="groq"),
        fallback_provider=None,
    )

    assert provider.client.chat
    assert captured["api_key"] == "test-key"
    assert str(captured["base_url"]) == GROQ_BASE_URL


def test_llm_prompt_contains_context_and_glossary() -> None:
    context = {
        "domain": "legal",
        "summary": "Contract between Apple Inc. and a supplier.",
        "tone": "juridique, precis et professionnel",
        "target_audience": "professionnels du droit",
        "proper_nouns": ["Apple Inc."],
        "important_terms": [
            {"source": "agreement", "target": "contrat", "required": True}
        ],
    }

    prompt = build_system_prompt(context)

    assert "traducteur professionnel anglais-francais specialise" in prompt
    assert "Ne retourne que la traduction francaise." in prompt
    assert "Ne garde aucun mot anglais inutile." in prompt


def test_llm_preserves_proper_nouns_urls_and_note_numbers() -> None:
    fake_client = FakeClient("Le contrat a ete signe.")
    provider = LLMTranslationProvider(settings=_settings(), client=fake_client)
    provider.set_document_context(
        {
            "proper_nouns": ["Apple Inc."],
            "important_terms": [
                {"source": "agreement", "target": "contrat", "required": True}
            ],
            "domain": "legal",
            "summary": "Agreement summary.",
            "tone": "professionnel",
            "target_audience": "juristes",
        }
    )
    block = {
        "id": "block_001",
        "type": "paragraph",
        "source_text": "Apple Inc. signed the agreement [1]. See https://example.com/API.",
        "translated_text": "",
        "status": "pending",
        "warnings": [],
    }

    translated = provider.translate_block(block)

    assert translated is True
    assert "Apple Inc." in block["translated_text"]
    assert "https://example.com/API." in block["translated_text"]
    assert "[1]" in block["translated_text"]
    assert "agreement" not in block["translated_text"].lower()


def test_document_context_extracts_domain_terms_and_proper_nouns() -> None:
    context = build_document_context(
        {
            "domain": "legal",
            "glossary": [
                {"source": "agreement", "target": "contrat", "required": True}
            ],
            "pages": [
                {
                    "blocks": [
                        {
                            "type": "paragraph",
                            "source_text": (
                                "Apple Inc. signs an agreement with OpenAI for API access."
                            ),
                        }
                    ]
                }
            ],
        }
    )

    assert context.domain == "legal"
    assert context.important_terms == [
        {"source": "agreement", "target": "contrat", "required": True}
    ]
    assert "Apple Inc" in context.proper_nouns
    assert context.summary.startswith("Apple Inc. signs")
