from app.services.section_service import build_document_sections


def _block(
    block_id: str,
    block_type: str,
    source_text: str,
    page_number: int,
    reading_order: int,
) -> dict:
    return {
        "id": block_id,
        "type": block_type,
        "source_text": source_text,
        "page_number": page_number,
        "reading_order": reading_order,
    }


def test_build_sections_groups_one_title_and_three_paragraphs() -> None:
    sections = build_document_sections(
        [
            _block("block_001", "title", "Main Title", 1, 1),
            _block("block_002", "paragraph", "First paragraph.", 1, 2),
            _block("block_003", "paragraph", "Second paragraph.", 1, 3),
            _block("block_004", "paragraph", "Third paragraph.", 1, 4),
        ]
    )

    assert sections == [
        {
            "section_id": "section_001",
            "title": "Main Title",
            "page_start": 1,
            "page_end": 1,
            "block_ids": ["block_001", "block_002", "block_003", "block_004"],
            "blocks_count": 4,
        }
    ]


def test_build_sections_starts_new_section_on_title() -> None:
    sections = build_document_sections(
        [
            _block("block_001", "title", "First Section", 1, 1),
            _block("block_002", "paragraph", "First body.", 1, 2),
            _block("block_003", "title", "Second Section", 1, 3),
            _block("block_004", "paragraph", "Second body.", 1, 4),
        ]
    )

    assert len(sections) == 2
    assert sections[0]["title"] == "First Section"
    assert sections[0]["block_ids"] == ["block_001", "block_002"]
    assert sections[1]["title"] == "Second Section"
    assert sections[1]["block_ids"] == ["block_003", "block_004"]


def test_build_sections_ignores_noise_and_preserves_reading_order() -> None:
    sections = build_document_sections(
        [
            _block("block_003", "paragraph", "Second paragraph.", 1, 3),
            _block("block_001", "title", "Ordered Section", 1, 1),
            _block("block_002", "noise", "Who", 1, 2),
            _block("block_004", "list_item", "- List item", 1, 4),
        ]
    )

    assert len(sections) == 1
    assert sections[0]["block_ids"] == ["block_001", "block_003", "block_004"]
    assert sections[0]["blocks_count"] == 3


def test_build_sections_tracks_page_range() -> None:
    sections = build_document_sections(
        [
            _block("block_001", "title", "Cross Page", 1, 1),
            _block("block_002", "paragraph", "Page one.", 1, 2),
            _block("block_003", "paragraph", "Page two.", 2, 1),
        ]
    )

    assert sections[0]["page_start"] == 1
    assert sections[0]["page_end"] == 2
