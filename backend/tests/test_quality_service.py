from app.services.quality_service import (
    compute_table_grid_confidence,
    compute_table_structure_confidence,
    compute_english_residual_score,
    compute_overlay_risk_score,
    compute_semantic_confidence,
    compute_translation_quality_score,
    score_document_quality,
)


def _clean_block() -> dict:
    return {
        "id": "block_001",
        "page_number": 1,
        "type": "paragraph",
        "source_text": "This agreement defines the responsibilities of each party.",
        "translated_text": "Ce contrat definit les responsabilites de chaque partie.",
        "bbox": [72, 100, 430, 130],
        "style": {"font": "Helvetica", "size": 11, "alignment": "left"},
        "reading_order": 1,
        "status": "translated",
        "warnings": [],
    }


def test_translation_quality_score_is_high_for_clean_translation() -> None:
    block = _clean_block()

    score = compute_translation_quality_score(block)

    assert score >= 0.8


def test_translation_quality_score_is_low_for_parasitic_text() -> None:
    block = _clean_block()
    block["translated_text"] = "??? ###"

    score = compute_translation_quality_score(block)

    assert score < 0.55


def test_translation_quality_score_is_low_when_translation_is_empty() -> None:
    block = _clean_block()
    block["translated_text"] = ""

    score = compute_translation_quality_score(block)

    assert score == 0.0


def test_translation_quality_score_penalizes_mock_when_disabled() -> None:
    block = _clean_block()
    block["translated_text"] = "[FR MOCK] This agreement defines responsibilities."

    score = compute_translation_quality_score(
        block,
        mock_translation_enabled=False,
    )

    assert score < 0.55


def test_overlay_risk_score_is_high_when_translation_is_too_long_for_bbox() -> None:
    block = _clean_block()
    block["bbox"] = [72, 100, 115, 111]
    block["translated_text"] = (
        "Ce texte francais est beaucoup trop long pour la petite zone disponible."
    )

    score = compute_overlay_risk_score(block)

    assert score > 0.55


def test_english_residual_score_is_high_with_unwanted_english_words() -> None:
    block = _clean_block()
    block["translated_text"] = "Ce contrat explique the service and customer issues."

    score = compute_english_residual_score(block)

    assert score > 0.25


def test_english_residual_score_does_not_penalize_protected_acronyms() -> None:
    block = _clean_block()
    block["translated_text"] = "Le PDF utilise AI et CEFR avec une URL."

    score = compute_english_residual_score(block)

    assert score == 0.0


def test_document_quality_is_computed_and_warnings_are_added() -> None:
    payload = {
        "document_id": "doc_quality",
        "pages": [
            {
                "page_number": 1,
                "blocks": [
                    _clean_block(),
                    {
                        "id": "block_002",
                        "page_number": 1,
                        "type": "paragraph",
                        "source_text": "Short content",
                        "translated_text": "the customer what",
                        "bbox": [72, 150, 110, 160],
                        "style": {"font": "Helvetica", "size": 11},
                        "reading_order": 2,
                        "status": "translated",
                        "warnings": [],
                    },
                ],
            }
        ],
        "sections": [],
        "warnings": [],
    }

    score_document_quality(payload)

    assert "document_quality" in payload
    assert payload["document_quality"]["average_translation_quality"] > 0
    assert payload["document_quality"]["average_overlay_risk"] > 0
    assert payload["document_quality"]["average_english_residual_score"] > 0
    assert payload["document_quality"]["average_semantic_consistency"] > 0
    assert payload["document_quality"]["blocks_needing_review"] == 1
    assert payload["document_quality"]["total_blocks_scored"] == 2
    risky_block = payload["pages"][0]["blocks"][1]
    assert "quality" in risky_block
    assert "english_residual_detected" in risky_block["warnings"]
    assert "high_overlay_risk" in risky_block["warnings"]
    assert "low_semantic_consistency" in risky_block["warnings"]


def test_semantic_confidence_is_high_for_real_paragraph() -> None:
    block = _clean_block()

    score = compute_semantic_confidence(block, {})

    assert score >= 0.75


def test_semantic_confidence_is_high_for_valid_short_title() -> None:
    block = _clean_block()
    block["type"] = "title"
    block["source_text"] = "Ethical AI Governance"
    block["translated_text"] = "Gouvernance ethique de l'IA"
    block["style"] = {"font": "Helvetica", "size": 16, "alignment": "left"}

    score = compute_semantic_confidence(block, {})

    assert score >= 0.75


def test_semantic_confidence_is_low_for_ai_alone() -> None:
    block = _clean_block()
    block["source_text"] = "AI"
    block["translated_text"] = "IA"

    score = compute_semantic_confidence(block, {})

    assert score < 0.45


def test_semantic_confidence_is_low_for_however_alone() -> None:
    block = _clean_block()
    block["source_text"] = "However"
    block["translated_text"] = "Cependant"

    score = compute_semantic_confidence(block, {})

    assert score < 0.45


def test_semantic_confidence_keeps_acronym_inside_sentence() -> None:
    block = _clean_block()
    block["source_text"] = "AI systems can improve public services when supervised."
    block["translated_text"] = (
        "Les systemes d'IA peuvent ameliorer les services publics lorsqu'ils "
        "sont supervises."
    )

    score = compute_semantic_confidence(block, {})

    assert score >= 0.75


def test_semantic_confidence_is_low_for_repeated_fragment() -> None:
    payload = {
        "document_id": "doc_semantic",
        "pages": [
            {
                "page_number": 1,
                "blocks": [
                    {
                        **_clean_block(),
                        "id": "block_001",
                        "source_text": "Governments",
                        "translated_text": "Gouvernements",
                        "reading_order": 1,
                    },
                    {
                        **_clean_block(),
                        "id": "block_002",
                        "source_text": "Governments",
                        "translated_text": "Gouvernements",
                        "reading_order": 2,
                    },
                ],
            }
        ],
        "sections": [],
        "warnings": [],
    }

    score_document_quality(payload)

    first_block = payload["pages"][0]["blocks"][0]
    assert first_block["semantic_confidence_score"] < 0.45
    assert first_block["semantic_category"] == "semantic_noise"
    assert "semantic_noise" in first_block["warnings"]


def test_score_document_quality_adds_semantic_confidence_fields() -> None:
    payload = {
        "document_id": "doc_semantic_fields",
        "pages": [{"page_number": 1, "blocks": [_clean_block()]}],
        "sections": [],
        "warnings": [],
    }

    score_document_quality(payload)

    block = payload["pages"][0]["blocks"][0]
    assert "semantic_confidence_score" in block
    assert "semantic_category" in block


def test_table_structure_confidence_scores_simple_table() -> None:
    block = {
        "type": "table",
        "rows": [
            {
                "cells": [
                    {"row": 0, "column": 0, "source_text": "Name"},
                    {"row": 0, "column": 1, "source_text": "Age"},
                ]
            },
            {
                "cells": [
                    {"row": 1, "column": 0, "source_text": "Alice"},
                    {"row": 1, "column": 1, "source_text": "30"},
                ]
            },
        ],
        "columns": [
            {"column_id": "col_001", "x0": 72, "x1": 120},
            {"column_id": "col_002", "x0": 180, "x1": 220},
        ],
        "grid": [
            [
                {"row": 0, "column": 0, "source_text": "Name"},
                {"row": 0, "column": 1, "source_text": "Age"},
            ],
            [
                {"row": 1, "column": 0, "source_text": "Alice"},
                {"row": 1, "column": 1, "source_text": "30"},
            ],
        ],
        "warnings": [],
    }

    score = compute_table_structure_confidence(block)

    assert score >= 0.9
    assert compute_table_grid_confidence(block) >= 0.9
    assert "table_detection_uncertain" not in block["warnings"]


def test_table_structure_confidence_warns_for_weak_table() -> None:
    block = {
        "type": "table",
        "rows": [
            {"cells": [{"row": 0, "column": 0, "source_text": "Name"}]},
            {"cells": [{"row": 1, "column": 0, "source_text": ""}]},
        ],
        "warnings": [],
    }

    score = compute_table_structure_confidence(block)

    assert score == 0.0


def test_table_grid_confidence_warns_for_missing_cells() -> None:
    block = {
        "type": "table",
        "rows": [
            {
                "cells": [
                    {"row": 0, "column": 0, "source_text": "Name"},
                    {"row": 0, "column": 1, "source_text": "Age"},
                ]
            },
            {
                "cells": [
                    {"row": 1, "column": 0, "source_text": "Alice"},
                    {
                        "row": 1,
                        "column": 1,
                        "source_text": "",
                        "empty_cell": True,
                        "weak_alignment": True,
                    },
                ]
            },
        ],
        "columns": [
            {"column_id": "col_001", "x0": 72, "x1": 120},
            {"column_id": "col_002", "x0": 180, "x1": 220},
        ],
        "grid": [],
        "warnings": [],
    }

    score = compute_table_grid_confidence(block)

    assert score < 0.9
