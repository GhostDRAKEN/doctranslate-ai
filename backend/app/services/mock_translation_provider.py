"""Deterministic mock translation provider for the MVP pipeline."""

TEXT_BLOCK_TYPES = {"paragraph", "title", "list_item", "caption", "footnote"}


class MockTranslationProvider:
    """Translate content without any external AI dependency."""

    provider_name = "mock"

    def translate_text(self, source_text: str) -> str:
        """Return a deterministic fake French translation."""

        return f"[FR MOCK] {source_text}"

    def translate_block(self, block: dict) -> bool:
        """Translate one intermediate block in place.

        Returns True when a text unit was translated.
        """

        block_type = block.get("type")

        if block_type in TEXT_BLOCK_TYPES:
            source_text = str(block.get("source_text", ""))
            if not source_text:
                return False
            block["translated_text"] = self.translate_text(source_text)
            block["status"] = "translated"
            return True

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

    def translate_table_block(self, block: dict) -> bool:
        """Translate table cells in place for simple MVP table blocks."""

        translated_any = False
        for row in block.get("rows") or []:
            for cell in row.get("cells") or []:
                source_text = str(cell.get("source_text", ""))
                if not source_text:
                    continue
                cell["translated_text"] = self.translate_text(source_text)
                translated_any = True

        if translated_any:
            block["status"] = "translated"

        return translated_any
