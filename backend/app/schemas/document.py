"""Document API and intermediate representation schemas."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class DocumentUploadResponse(BaseModel):
    """Response returned after a successful PDF upload."""

    document_id: str
    filename: str
    status: str


class DocumentDocxGenerationResponse(BaseModel):
    """Response returned after DOCX generation."""

    document_id: str
    status: str
    download_url: str


class DocumentPdfGenerationResponse(BaseModel):
    """Response returned after PDF overlay generation."""

    document_id: str
    status: str
    download_url: str


class DocumentMetadata(BaseModel):
    """Metadata extracted or inferred for a document."""

    filename: str
    page_count: int
    file_size_mb: float
    created_at: str


class MvpLimits(BaseModel):
    """MVP limits applied to the document."""

    max_pages: int
    max_file_size_mb: int
    digital_pdf_only: bool = True
    requires_selectable_text: bool = True


class BlockStyle(BaseModel):
    """Approximate visual style for an extracted block."""

    font: str | None = None
    size: float | None = None
    bold: bool = False
    italic: bool = False
    color: str | None = "#000000"
    alignment: str = "left"


class BlockQuality(BaseModel):
    """Non-blocking quality scores for one translated block."""

    translation_quality_score: float = 0.0
    english_residual_score: float = 0.0
    semantic_consistency_score: float = 0.0
    overlay_risk_score: float = 0.0


class DocumentBlock(BaseModel):
    """A simple MVP document block."""

    id: str
    page_number: int
    type: Literal[
        "title",
        "paragraph",
        "list_item",
        "footnote",
        "caption",
        "table",
        "image",
        "header",
        "footer",
        "noise",
        "unknown",
    ]
    source_page: int | None = None
    role: str | None = None
    confidence_score: float | None = None
    table_id: str | None = None
    table_structure_confidence: float | None = None
    table_grid_confidence: float | None = None
    table_diagnostics: dict[str, Any] | None = None
    semantic_confidence_score: float = 0.0
    semantic_category: str | None = None
    source_text: str
    translated_text: str = ""
    bbox: list[float]
    style: BlockStyle
    reading_order: int
    status: Literal["pending", "translated", "skipped", "failed", "needs_review"] = (
        "pending"
    )
    warnings: list[str] = Field(default_factory=list)
    quality: BlockQuality = Field(default_factory=BlockQuality)
    columns: list[dict[str, Any]] | None = None
    grid: list[list[dict[str, Any]]] | None = None
    rows: list[dict[str, Any]] | None = None
    image_path: str | None = None
    has_possible_text: bool | None = None
    merged_from: list[str] | None = None
    merge_reason: str | None = None


class DocumentPage(BaseModel):
    """One extracted PDF page."""

    page_number: int
    width: float
    height: float
    blocks: list[DocumentBlock] = Field(default_factory=list)


class DocumentSection(BaseModel):
    """Logical section grouping blocks under a title.

    This additive structure prepares future contextual translation and batch
    processing while preserving the existing page/block representation.
    """

    section_id: str
    title: str
    page_start: int
    page_end: int
    block_ids: list[str] = Field(default_factory=list)
    blocks_count: int


class DocumentQuality(BaseModel):
    """Aggregated non-blocking quality signals for the document."""

    average_translation_quality: float = 0.0
    average_english_residual_score: float = 0.0
    average_semantic_consistency: float = 0.0
    average_overlay_risk: float = 0.0
    blocks_needing_review: int = 0
    total_blocks_scored: int = 0


class BatchSummary(BaseModel):
    """Summary of experimental batch processing."""

    enabled: bool = False
    batch_size_pages: int = 0
    total_batches: int = 0
    completed_batches: int = 0
    failed_batches: int = 0


class DocumentIntermediate(BaseModel):
    """Intermediate representation produced after PDF extraction."""

    document_id: str
    source_language: str = "en"
    target_language: str = "fr"
    domain: str = "general"
    metadata: DocumentMetadata
    mvp_limits: MvpLimits
    glossary: list[dict[str, Any]] = Field(default_factory=list)
    pages: list[DocumentPage]
    sections: list[DocumentSection] = Field(default_factory=list)
    document_quality: DocumentQuality = Field(default_factory=DocumentQuality)
    batch_summary: BatchSummary | None = None
    warnings: list[str] = Field(default_factory=list)
