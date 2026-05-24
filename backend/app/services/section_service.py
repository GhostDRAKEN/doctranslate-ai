"""Document section reconstruction helpers.

Sections are an additive logical layer above pages and blocks. They are used to
prepare future contextual translation and batch processing without changing the
existing block-based PDF overlay pipeline.
"""

from typing import Any


SECTION_BLOCK_TYPES = {"title", "paragraph", "list_item"}


def build_document_sections(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group logical blocks into title-led sections.

    Heuristics:
    - a `title` starts a new section;
    - following paragraph/list blocks belong to the current section;
    - a new `title` closes the previous section;
    - `noise` blocks and non-content blocks are ignored;
    - input order is respected, so callers should pass blocks sorted by page and
      reading order.
    """

    sections: list[dict[str, Any]] = []
    current_section: dict[str, Any] | None = None

    for block in sorted_blocks_for_sections(blocks):
        block_type = str(block.get("type") or "")
        if block_type == "noise":
            continue
        if block_type not in SECTION_BLOCK_TYPES:
            continue

        if block_type == "title":
            current_section = create_section(
                len(sections) + 1,
                title=str(block.get("source_text") or "").strip(),
                block=block,
            )
            sections.append(current_section)
            continue

        if current_section is None:
            current_section = create_section(
                len(sections) + 1,
                title="Untitled section",
                block=block,
            )
            sections.append(current_section)
        else:
            append_block_to_section(current_section, block)

    return finalize_sections(sections)


def sorted_blocks_for_sections(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort blocks by natural document reading order."""

    return sorted(
        blocks,
        key=lambda block: (
            int(block.get("page_number") or 0),
            int(block.get("reading_order") or 0),
        ),
    )


def create_section(
    section_number: int,
    *,
    title: str,
    block: dict[str, Any],
) -> dict[str, Any]:
    """Create a new section initialized with one block."""

    page_number = int(block.get("page_number") or 0)
    return {
        "section_id": f"section_{section_number:03d}",
        "title": title or "Untitled section",
        "page_start": page_number,
        "page_end": page_number,
        "block_ids": [str(block.get("id"))],
        "blocks_count": 1,
    }


def append_block_to_section(section: dict[str, Any], block: dict[str, Any]) -> None:
    """Append one logical content block to an existing section."""

    block_id = str(block.get("id"))
    if block_id not in section["block_ids"]:
        section["block_ids"].append(block_id)

    page_number = int(block.get("page_number") or section["page_end"])
    section["page_start"] = min(int(section["page_start"]), page_number)
    section["page_end"] = max(int(section["page_end"]), page_number)
    section["blocks_count"] = len(section["block_ids"])


def finalize_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return sections with consistent block counts."""

    for section in sections:
        section["blocks_count"] = len(section.get("block_ids", []))
    return sections
