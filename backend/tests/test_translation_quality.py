from typing import Any

from app.services.translation_service import (
    TranslationService,
    clean_paragraph_translation_artifacts,
    clean_translation_artifacts,
    detect_english_residual,
    paragraph_english_residual_needs_review,
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


def test_clean_paragraph_translation_artifacts_removes_long_suffix() -> None:
    source_text = (
        "Scientists study human systems over time. However, while climate is "
        "changing, it affects developing regions."
    )
    translated_text = (
        "Ces facteurs creent des risques environnementaux. "
        "Scientists Human Over However While Climate It Developing"
    )

    assert clean_paragraph_translation_artifacts(source_text, translated_text) == (
        "Ces facteurs creent des risques environnementaux."
    )


def test_clean_paragraph_translation_artifacts_removes_climate_keyword_suffix() -> None:
    source_text = (
        "Climate change affects Earth systems, global temperatures, rising seas, "
        "coastal cities, extreme weather, although biodiversity, and many communities."
    )
    translated_text = (
        "Ces pressions peuvent causer des dommages ecologiques a long terme. "
        "Climate Earth Global Rising Coastal Extreme Although Biodiversity Many"
    )

    assert clean_paragraph_translation_artifacts(source_text, translated_text) == (
        "Ces pressions peuvent causer des dommages ecologiques a long terme."
    )


def test_clean_paragraph_translation_artifacts_removes_short_suffixes() -> None:
    source_text = "However climate policies require scientists although climate risks remain."

    assert clean_paragraph_translation_artifacts(
        source_text,
        "Ces mesures renforcent la protection sociale. However Climate",
    ) == "Ces mesures renforcent la protection sociale."
    assert clean_paragraph_translation_artifacts(
        source_text,
        "Ces actions sont necessaires. Scientists Although",
    ) == "Ces actions sont necessaires."
    assert clean_paragraph_translation_artifacts(
        source_text,
        "Elles concernent les organisations privees. Climate",
    ) == "Elles concernent les organisations privees."


def test_clean_paragraph_translation_artifacts_preserves_protected_terms() -> None:
    assert clean_paragraph_translation_artifacts(
        "The PDF format is required.",
        "Le document conserve le PDF",
    ) == "Le document conserve le PDF"
    assert clean_paragraph_translation_artifacts(
        "AI systems are used.",
        "Le systeme utilise IA",
    ) == "Le systeme utilise IA"
    assert clean_paragraph_translation_artifacts(
        "The Paris Agreement is referenced.",
        "Le document cite Paris Agreement.",
    ) == "Le document cite Paris Agreement."


def test_clean_paragraph_translation_artifacts_keeps_clean_french() -> None:
    assert clean_paragraph_translation_artifacts(
        "Climate policy supports local organizations.",
        "Les politiques climatiques soutiennent les organisations locales.",
    ) == "Les politiques climatiques soutiennent les organisations locales."


def test_paragraph_residual_cleanup_adds_warning(monkeypatch) -> None:
    from app.services import translation_service

    settings = translation_service.get_settings()
    monkeypatch.setattr(settings, "mock_translation_enabled", False)
    monkeypatch.setattr(translation_service, "get_settings", lambda: settings)
    payload = {
        "pages": [
            {
                "blocks": [
                    {
                        "id": "block_001",
                        "type": "paragraph",
                        "source_text": (
                            "Scientists explain how climate affects developing regions."
                        ),
                        "translated_text": "",
                        "status": "pending",
                        "warnings": [],
                    }
                ]
            }
        ]
    }
    provider = ResidualProvider(
        "Les impacts environnementaux sont importants. Scientists Climate Developing"
    )

    translated_count = TranslationService(provider=provider).translate_payload(payload)
    block = payload["pages"][0]["blocks"][0]

    assert translated_count == 1
    assert block["translated_text"] == "Les impacts environnementaux sont importants."
    assert "paragraph_english_residual_cleaned" in block["warnings"]
    assert "english_residual" not in block["warnings"]


def test_paragraph_residual_review_preserves_proper_name() -> None:
    assert not paragraph_english_residual_needs_review(
        "The Paris Agreement is referenced.",
        "Le document cite Paris Agreement.",
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
