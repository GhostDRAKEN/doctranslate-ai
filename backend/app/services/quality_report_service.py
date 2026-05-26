"""Automatic quality report generation for processed documents."""

import json
from datetime import UTC, datetime
from statistics import mean
from typing import Any

from fastapi import status

from app.core.errors import AppError
from app.services.storage_service import (
    get_intermediate_path,
    get_quality_report_path,
)

TEXT_BLOCK_TYPES = {"title", "paragraph", "list_item", "caption", "footnote", "unknown"}
CRITICAL_WARNINGS = {
    "english_residual_detected",
    "paragraph_english_residual_needs_review",
    "table_cell_needs_review",
    "translation_failed",
    "masked_without_translation",
    "source_masked_translation_rejected",
    "overlay_text_truncated",
    "weak_table_grid",
}
NON_CRITICAL_REVIEW_WARNINGS = {
    "paragraph_english_residual_cleaned",
    "table_cell_english_residual_cleaned",
    "overlay_written_with_review",
    "high_overlay_risk",
    "low_semantic_consistency",
    "low_semantic_confidence",
    "probable_fragment",
    "table_detection_uncertain",
}
NEUTRAL_SCORE = 0.75


def generate_quality_report(intermediate_data: dict[str, Any]) -> dict[str, Any]:
    """Build a non-blocking document quality report from intermediate data."""

    blocks = collect_blocks(intermediate_data)
    document_quality = intermediate_data.get("document_quality") or {}
    batch_summary = intermediate_data.get("batch_summary") or {}
    warning_codes = collect_warning_codes(intermediate_data, blocks)
    english_residual_count = count_english_residuals(blocks, warning_codes)
    warnings_count = len(warning_codes)
    text_blocks = [block for block in blocks if block.get("type") in TEXT_BLOCK_TYPES]
    translatable_blocks = [
        block
        for block in text_blocks
        if block.get("type") not in {"header", "footer", "noise"}
    ]
    untranslated_blocks = [
        block
        for block in translatable_blocks
        if not has_block_translation(block)
    ]
    failed_blocks = [block for block in blocks if block.get("status") == "failed"]
    translated_blocks_count = sum(1 for block in blocks if has_block_translation(block))
    tables = [block for block in blocks if block.get("type") == "table"]
    table_cells_requiring_translation = count_table_cells_requiring_translation(tables)
    untranslated_table_cells = count_untranslated_table_cells(tables)
    quality_data_missing = not has_document_quality_data(document_quality)
    translatable_units = len(translatable_blocks) + table_cells_requiring_translation
    untranslated_units = len(untranslated_blocks) + untranslated_table_cells

    translation_score = resolve_translation_score(
        document_quality,
        translatable_units,
        untranslated_units,
    )
    overlay_score = resolve_overlay_score(document_quality, blocks)
    semantic_score = resolve_semantic_score(document_quality, blocks)
    table_score = resolve_table_score(tables)

    major_issues: list[str] = []
    minor_issues: list[str] = []
    critical_warning_count = sum(
        1 for warning in warning_codes if warning in CRITICAL_WARNINGS
    )
    failed_batches = int(batch_summary.get("failed_batches") or 0)
    total_batches = int(batch_summary.get("total_batches") or 0)
    completed_batches = int(batch_summary.get("completed_batches") or 0)

    if quality_data_missing:
        minor_issues.append("quality_data_missing")
    if untranslated_blocks:
        major_issues.append("translation_incomplete")
    if untranslated_table_cells:
        major_issues.append("table_translation_incomplete")
    if failed_blocks:
        major_issues.append("failed_blocks_present")
    if failed_batches > 0:
        major_issues.append("batch_failed")
    if english_residual_count > 2:
        major_issues.append("english_residuals_detected")
    elif english_residual_count > 0:
        minor_issues.append("limited_english_residuals_detected")
    if critical_warning_count:
        major_issues.append("critical_warnings_present")
    if warnings_count and not critical_warning_count:
        minor_issues.append("non_critical_warnings_present")
    if any(warning in NON_CRITICAL_REVIEW_WARNINGS for warning in warning_codes):
        add_unique(minor_issues, "manual_review_recommended")
    if tables and table_score < 0.7:
        major_issues.append("table_structure_needs_review")
    elif tables and table_score < 0.9:
        minor_issues.append("table_structure_minor_review")

    overall_score = compute_overall_score(
        translation_score=translation_score,
        overlay_score=overlay_score,
        semantic_score=semantic_score,
        table_score=table_score,
        english_residual_count=english_residual_count,
        critical_warning_count=critical_warning_count,
        failed_batches=failed_batches,
        untranslated_blocks=untranslated_units,
        translatable_blocks=translatable_units,
    )
    recommendation = choose_recommendation(
        overall_score=overall_score,
        english_residual_count=english_residual_count,
        critical_warning_count=critical_warning_count,
        warnings_count=warnings_count,
        major_issues=major_issues,
        minor_issues=minor_issues,
    )

    report = {
        "document_id": str(intermediate_data.get("document_id") or ""),
        "overall_score": overall_score,
        "translation_score": translation_score,
        "overlay_score": overlay_score,
        "semantic_score": semantic_score,
        "table_score": table_score,
        "english_residual_count": english_residual_count,
        "warnings_count": warnings_count,
        "blocks_count": len(blocks),
        "translated_blocks_count": translated_blocks_count,
        "tables_count": len(tables),
        "pages_count": len(intermediate_data.get("pages") or []),
        "recommendation": recommendation,
        "major_issues": sorted(set(major_issues)),
        "minor_issues": sorted(set(minor_issues)),
        "created_at": now_utc(),
    }
    if batch_summary:
        report.update(
            {
                "total_batches": total_batches,
                "completed_batches": completed_batches,
                "failed_batches": failed_batches,
            }
        )
    return report


def generate_and_save_quality_report(document_id: str) -> dict[str, Any]:
    """Generate quality_report.json and attach a summary to intermediate.json."""

    intermediate_path = get_intermediate_path(document_id)
    if not intermediate_path.is_file():
        raise AppError(
            code="RESULT_NOT_READY",
            message="La representation intermediaire n'est pas encore disponible.",
            status_code=status.HTTP_409_CONFLICT,
            details={"document_id": document_id},
        )

    payload = json.loads(intermediate_path.read_text(encoding="utf-8"))
    report = generate_quality_report(payload)
    payload["quality_report_summary"] = {
        "overall_score": report["overall_score"],
        "recommendation": report["recommendation"],
        "warnings_count": report["warnings_count"],
        "created_at": report["created_at"],
    }
    intermediate_path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    get_quality_report_path(document_id).write_text(
        json.dumps(report, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    return report


def collect_blocks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect blocks from all pages in the intermediate payload."""

    return [
        block
        for page in payload.get("pages", [])
        for block in page.get("blocks", [])
    ]


def collect_warning_codes(
    payload: dict[str, Any],
    blocks: list[dict[str, Any]],
) -> list[str]:
    """Collect warning codes from payload, blocks and table cells."""

    warnings = [str(warning) for warning in payload.get("warnings") or []]
    for block in blocks:
        warnings.extend(str(warning) for warning in block.get("warnings") or [])
        if block.get("type") == "table":
            for cell in iter_table_cells(block):
                warnings.extend(str(warning) for warning in cell.get("warnings") or [])
    return [warning for warning in warnings if warning]


def count_english_residuals(
    blocks: list[dict[str, Any]],
    warning_codes: list[str],
) -> int:
    """Count likely English residual findings across blocks and cells."""

    warning_count = sum(1 for warning in warning_codes if "english_residual" in warning)
    quality_count = 0
    for block in blocks:
        quality = block.get("quality") or {}
        if float(quality.get("english_residual_score") or 0.0) > 0.25:
            quality_count += 1
        if block.get("type") == "table":
            for cell in iter_table_cells(block):
                if any(
                    "english_residual" in str(warning)
                    for warning in cell.get("warnings") or []
                ):
                    quality_count += 1
    return max(warning_count, quality_count)


def resolve_translation_score(
    document_quality: dict[str, Any],
    translatable_units: int,
    untranslated_units: int,
) -> float:
    """Return a translation score from document_quality or a neutral fallback."""

    score = parse_score(document_quality.get("average_translation_quality"))
    if score is not None and score > 0:
        return score
    if translatable_units:
        return clamp_score(1.0 - (untranslated_units / translatable_units))
    return NEUTRAL_SCORE


def resolve_overlay_score(
    document_quality: dict[str, Any],
    blocks: list[dict[str, Any]],
) -> float:
    """Return an overlay readiness score where 1 is low risk."""

    average_risk = parse_score(document_quality.get("average_overlay_risk"))
    if average_risk is not None:
        return clamp_score(1.0 - average_risk)

    risks = [
        float((block.get("quality") or {}).get("overlay_risk_score") or 0.0)
        for block in blocks
        if "quality" in block
    ]
    if risks:
        return clamp_score(1.0 - mean(risks))
    return NEUTRAL_SCORE


def resolve_semantic_score(
    document_quality: dict[str, Any],
    blocks: list[dict[str, Any]],
) -> float:
    """Return semantic score from aggregate quality or block confidence."""

    score = parse_score(document_quality.get("average_semantic_consistency"))
    if score is not None and score > 0:
        return score

    block_scores = [
        float(block.get("semantic_confidence_score"))
        for block in blocks
        if block.get("semantic_confidence_score") is not None
    ]
    if block_scores:
        return clamp_score(mean(block_scores))
    return NEUTRAL_SCORE


def resolve_table_score(tables: list[dict[str, Any]]) -> float:
    """Return average table confidence, or a perfect score when no tables exist."""

    if not tables:
        return 1.0

    scores: list[float] = []
    for table in tables:
        score = parse_score(table.get("table_grid_confidence"))
        if score is None:
            score = parse_score(table.get("table_structure_confidence"))
        scores.append(NEUTRAL_SCORE if score is None else score)
    return clamp_score(mean(scores))


def compute_overall_score(
    *,
    translation_score: float,
    overlay_score: float,
    semantic_score: float,
    table_score: float,
    english_residual_count: int,
    critical_warning_count: int,
    failed_batches: int,
    untranslated_blocks: int,
    translatable_blocks: int,
) -> float:
    """Compute the final bounded report score."""

    score = (
        (translation_score * 0.35)
        + (semantic_score * 0.25)
        + (overlay_score * 0.25)
        + (table_score * 0.15)
    )
    untranslated_ratio = (
        untranslated_blocks / translatable_blocks if translatable_blocks else 0.0
    )
    score -= min(0.25, english_residual_count * 0.03)
    score -= min(0.2, critical_warning_count * 0.04)
    score -= min(0.3, failed_batches * 0.15)
    score -= min(0.35, untranslated_ratio * 0.35)
    return clamp_score(score)


def choose_recommendation(
    *,
    overall_score: float,
    english_residual_count: int,
    critical_warning_count: int,
    warnings_count: int,
    major_issues: list[str],
    minor_issues: list[str],
) -> str:
    """Choose a simple product-facing quality recommendation."""

    if overall_score < 0.55 or is_not_ready_issue_present(major_issues):
        return "document_not_ready"
    if (
        overall_score >= 0.9
        and english_residual_count <= 2
        and critical_warning_count == 0
        and not major_issues
        and warnings_count == 0
    ):
        return "document_ready"
    if overall_score >= 0.75 and critical_warning_count == 0 and not major_issues:
        return "document_ready_with_minor_review"
    if overall_score >= 0.55:
        return "document_needs_review"
    return "document_not_ready"


def is_not_ready_issue_present(major_issues: list[str]) -> bool:
    """Return True for issues that make the document unsuitable for delivery."""

    blocking_issues = {
        "translation_incomplete",
        "table_translation_incomplete",
        "failed_blocks_present",
        "batch_failed",
    }
    return bool(blocking_issues.intersection(major_issues))


def has_document_quality_data(document_quality: dict[str, Any]) -> bool:
    """Return whether aggregate quality contains usable scoring data."""

    return any(
        parse_score(document_quality.get(field)) is not None
        for field in (
            "average_translation_quality",
            "average_english_residual_score",
            "average_semantic_consistency",
            "average_overlay_risk",
        )
    )


def has_block_translation(block: dict[str, Any]) -> bool:
    """Return True when a block or table contains translated output."""

    if str(block.get("translated_text") or "").strip():
        return True
    if block.get("type") == "table":
        return any(
            str(cell.get("translated_text") or "").strip()
            for cell in iter_table_cells(block)
        )
    return False


def count_table_cells_requiring_translation(tables: list[dict[str, Any]]) -> int:
    """Count table cells that contain source text."""

    return sum(
        1
        for table in tables
        for cell in iter_table_cells(table)
        if str(cell.get("source_text") or cell.get("text") or "").strip()
    )


def count_untranslated_table_cells(tables: list[dict[str, Any]]) -> int:
    """Count source table cells that do not have translated text."""

    return sum(
        1
        for table in tables
        for cell in iter_table_cells(table)
        if str(cell.get("source_text") or cell.get("text") or "").strip()
        and not str(cell.get("translated_text") or "").strip()
    )


def iter_table_cells(block: dict[str, Any]) -> list[dict[str, Any]]:
    """Return table cells from rows and grid without duplicating object identities."""

    cells: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in block.get("rows") or []:
        for cell in row.get("cells") or []:
            if id(cell) not in seen:
                cells.append(cell)
                seen.add(id(cell))
    for row in block.get("grid") or []:
        for cell in row:
            if id(cell) not in seen:
                cells.append(cell)
                seen.add(id(cell))
    return cells


def parse_score(value: Any) -> float | None:
    """Parse a numeric score safely."""

    if value is None:
        return None
    try:
        return clamp_score(float(value))
    except (TypeError, ValueError):
        return None


def add_unique(items: list[str], value: str) -> None:
    """Append a value only once."""

    if value not in items:
        items.append(value)


def clamp_score(value: float) -> float:
    """Clamp a score to 0..1 and round for stable JSON."""

    return round(max(0.0, min(1.0, value)), 3)


def now_utc() -> str:
    """Return an ISO UTC timestamp for the report."""

    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
