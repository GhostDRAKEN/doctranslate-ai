"""Inspect a DocTranslate AI intermediate.json file."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


TEXT_BLOCK_TYPES = {"title", "paragraph", "list_item", "caption", "footnote"}


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python skills/doctranslate-ai/scripts/inspect_intermediate.py <document_id>")
        return 1

    document_id = sys.argv[1]
    root = Path(__file__).resolve().parents[3]
    intermediate_path = root / "backend" / "storage" / "tmp" / document_id / "intermediate.json"

    if not intermediate_path.is_file():
        print(f"intermediate.json introuvable: {intermediate_path}")
        return 2

    payload = json.loads(intermediate_path.read_text(encoding="utf-8"))
    pages = payload.get("pages", [])
    blocks = [
        block
        for page in pages
        for block in page.get("blocks", [])
    ]
    text_blocks = [
        block
        for block in blocks
        if block.get("type") in TEXT_BLOCK_TYPES
    ]
    translated_blocks = [
        block
        for block in text_blocks
        if str(block.get("translated_text") or "").strip()
    ]
    empty_translations = [
        block
        for block in text_blocks
        if not str(block.get("translated_text") or "").strip()
    ]
    warnings = collect_warnings(blocks)
    suspicious_blocks = [
        block
        for block in blocks
        if block.get("status") in {"failed", "needs_review"}
        or block.get("warnings")
    ]

    print(f"Document: {payload.get('document_id', document_id)}")
    print(f"Pages: {len(pages)}")
    print(f"Blocs: {len(blocks)}")
    print(f"Blocs textuels traduisibles: {len(text_blocks)}")
    print(f"Blocs traduits: {len(translated_blocks)}")
    print(f"translated_text vides: {len(empty_translations)}")
    print("")

    print("Warnings:")
    if warnings:
        for warning, count in sorted(warnings.items()):
            print(f"- {warning}: {count}")
    else:
        print("- aucun")

    print("")
    print("Blocs suspects:")
    if suspicious_blocks:
        for block in suspicious_blocks[:20]:
            print(format_block(block))
        if len(suspicious_blocks) > 20:
            print(f"... {len(suspicious_blocks) - 20} blocs suspects supplementaires")
    else:
        print("- aucun")

    return 0


def collect_warnings(blocks: list[dict[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for block in blocks:
        for warning in block.get("warnings") or []:
            warning_key = str(warning)
            result[warning_key] = result.get(warning_key, 0) + 1
    return result


def format_block(block: dict[str, Any]) -> str:
    block_id = block.get("id", "unknown")
    block_type = block.get("type", "unknown")
    status = block.get("status", "unknown")
    warnings = ", ".join(str(item) for item in block.get("warnings") or []) or "none"
    text = str(block.get("source_text") or block.get("translated_text") or "")
    text = " ".join(text.split())
    if len(text) > 90:
        text = text[:87] + "..."
    return f"- {block_id} type={block_type} status={status} warnings={warnings} text={text!r}"


if __name__ == "__main__":
    raise SystemExit(main())
