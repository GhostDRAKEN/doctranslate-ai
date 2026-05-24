from typing import Any

from app.services.translation_service import (
    TranslationService,
    clean_translation_artifacts,
    detect_english_residual,
)


class ResidualProvider:
    provider_name = "llm"

    def __init__(self, translated_text: str) -> None:
        self.translated_text = translated_text

    def translate_block(self, block: dict[str, Any]) -> bool:
        block["translated_text"] = self.translated_text
        block["status"] = "translated"
        return True


def test_detect_english_residual_flags_suspicious_words() -> None:
    assert detect_english_residual("Le texte est traduit. Who")
    assert detect_english_residual("Le texte est traduit. What")
    assert detect_english_residual("Le texte est traduit. When")
    assert detect_english_residual("Le texte est traduit. If")
    assert detect_english_residual("Le texte est traduit. AI-powered")
    assert detect_english_residual("Le texte est traduit. Technology Startups")
    assert detect_english_residual("Le texte est traduit. Artificial Intelligence Technology")


def test_detect_english_residual_preserves_names_and_acronyms() -> None:
    assert not detect_english_residual("Emma marche avec Shadow.")
    assert not detect_english_residual("David Grey arrive demain.")
    assert not detect_english_residual("Le modele AI lit un PDF CEFR.")


def test_clean_translation_artifacts_removes_trailing_residue_only() -> None:
    assert clean_translation_artifacts("Le contenu est traduit. From") == (
        "Le contenu est traduit."
    )
    assert clean_translation_artifacts("Le contenu est traduit. However Issues") == (
        "Le contenu est traduit."
    )
    assert clean_translation_artifacts(
        "Le contenu est traduit. Artificial Intelligence Technology"
    ) == "Le contenu est traduit."
    assert clean_translation_artifacts("However, le sujet continue.") == (
        "However, le sujet continue."
    )


def test_translation_marks_block_with_english_residual_warning() -> None:
    payload = {
        "pages": [
            {
                "blocks": [
                    {
                        "id": "block_001",
                        "type": "paragraph",
                        "source_text": "The content is translated.",
                        "translated_text": "",
                        "status": "pending",
                        "warnings": [],
                    }
                ]
            }
        ]
    }
    service = TranslationService(provider=ResidualProvider("Le texte Who reste suspect."))

    translated_count = service.translate_payload(payload)
    block = payload["pages"][0]["blocks"][0]

    assert translated_count == 0
    assert block["status"] == "needs_review"
    assert "english_residual" in block["warnings"]


def test_mock_marker_remains_allowed_in_mock_mode(monkeypatch) -> None:
    from app.services import translation_service

    payload = {
        "pages": [
            {
                "blocks": [
                    {
                        "id": "block_001",
                        "type": "paragraph",
                        "source_text": "Original text.",
                        "translated_text": "",
                        "status": "pending",
                        "warnings": [],
                    }
                ]
            }
        ]
    }
    settings = translation_service.get_settings()
    monkeypatch.setattr(settings, "mock_translation_enabled", True)
    monkeypatch.setattr(translation_service, "get_settings", lambda: settings)
    service = TranslationService(provider=ResidualProvider("[FR MOCK] Original text."))

    translated_count = service.translate_payload(payload)
    block = payload["pages"][0]["blocks"][0]

    assert translated_count == 1
    assert block["status"] == "translated"
    assert block["translated_text"].startswith("[FR MOCK]")
