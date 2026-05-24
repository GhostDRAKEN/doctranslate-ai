from typing import Any

from app.services.translation_service import TranslationService


class RecordingProvider:
    provider_name = "llm"

    def __init__(self, translated_text: str | None = None) -> None:
        self.translated_text = translated_text
        self.contexts: list[dict[str, Any]] = []
        self.translated_block_ids: list[str] = []

    def set_document_context(self, context: dict[str, Any]) -> None:
        self.contexts.append(dict(context))

    def translate_block(self, block: dict[str, Any]) -> bool:
        self.translated_block_ids.append(str(block.get("id")))
        block["translated_text"] = self.translated_text or (
            f"FR {block.get('source_text', '')}"
        )
        block["status"] = "translated"
        return True


def _block(
    block_id: str,
    block_type: str,
    source_text: str,
    reading_order: int,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": block_id,
        "page_number": 1,
        "type": block_type,
        "source_text": source_text,
        "translated_text": "",
        "bbox": [10, 10 * reading_order, 200, 10 * reading_order + 20],
        "style": {"font": "Arial", "size": 11},
        "reading_order": reading_order,
        "status": "pending",
        "warnings": warnings or [],
    }


def _payload(with_sections: bool = True) -> dict[str, Any]:
    blocks = [
        _block("block_001", "title", "Artificial Intelligence", 1),
        _block(
            "block_002",
            "paragraph",
            "AI systems help teams translate documents more efficiently.",
            2,
        ),
        _block(
            "block_003",
            "paragraph",
            "The translated file keeps a readable structure.",
            3,
        ),
        _block("block_004", "noise", "Who", 4, warnings=["noise_block"]),
    ]
    payload: dict[str, Any] = {
        "document_id": "doc_sections",
        "source_language": "en",
        "target_language": "fr",
        "domain": "technical",
        "glossary": [],
        "pages": [
            {
                "page_number": 1,
                "width": 595,
                "height": 842,
                "blocks": blocks,
            }
        ],
        "warnings": [],
    }
    if with_sections:
        payload["sections"] = [
            {
                "section_id": "section_001",
                "title": "Artificial Intelligence",
                "page_start": 1,
                "page_end": 1,
                "block_ids": [
                    "block_001",
                    "block_002",
                    "block_003",
                    "block_004",
                ],
                "blocks_count": 4,
            }
        ]
    return payload


def test_sections_present_uses_section_context() -> None:
    provider = RecordingProvider()
    payload = _payload(with_sections=True)

    translated_count = TranslationService(provider=provider).translate_payload(payload)

    assert translated_count == 3
    assert provider.translated_block_ids == ["block_001", "block_002", "block_003"]
    assert provider.contexts[0]["section_title"] == "Artificial Intelligence"
    assert provider.contexts[1]["previous_text"] == "Artificial Intelligence"
    assert provider.contexts[1]["current_text"].startswith("AI systems help")
    assert provider.contexts[1]["next_text"].startswith("The translated file")


def test_sections_absent_falls_back_to_block_translation() -> None:
    provider = RecordingProvider()
    payload = _payload(with_sections=False)

    translated_count = TranslationService(provider=provider).translate_payload(payload)

    assert translated_count == 3
    assert provider.translated_block_ids == ["block_001", "block_002", "block_003"]
    assert provider.contexts == []


def test_section_translation_does_not_send_noise_blocks() -> None:
    provider = RecordingProvider()
    payload = _payload(with_sections=True)

    TranslationService(provider=provider).translate_payload(payload)
    noise_block = payload["pages"][0]["blocks"][3]

    assert "block_004" not in provider.translated_block_ids
    assert noise_block["translated_text"] == ""
    assert noise_block["status"] == "needs_review"
    assert "noise_block" in noise_block["warnings"]


def test_section_translation_stores_only_current_block_translation() -> None:
    provider = RecordingProvider(translated_text="Traduction du bloc courant.")
    payload = _payload(with_sections=True)

    TranslationService(provider=provider).translate_payload(payload)
    current_block = payload["pages"][0]["blocks"][1]

    assert current_block["translated_text"] == "Traduction du bloc courant."
    assert "Artificial Intelligence" not in current_block["translated_text"]
    assert "The translated file" not in current_block["translated_text"]


def test_section_translation_keeps_english_residual_validation() -> None:
    provider = RecordingProvider(translated_text="Le texte Who reste suspect.")
    payload = _payload(with_sections=True)

    translated_count = TranslationService(provider=provider).translate_payload(payload)
    first_block = payload["pages"][0]["blocks"][0]

    assert translated_count == 0
    assert first_block["status"] == "needs_review"
    assert "english_residual" in first_block["warnings"]
