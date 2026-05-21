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
        "unknown",
    ]
    source_page: int | None = None
    role: str | None = None
    confidence_score: float | None = None
    source_text: str
    translated_text: str = ""
    bbox: list[float]
    style: BlockStyle
    reading_order: int
    status: Literal["pending", "translated", "skipped", "failed", "needs_review"] = (
        "pending"
    )
    warnings: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] | None = None
    image_path: str | None = None
    has_possible_text: bool | None = None


class DocumentPage(BaseModel):
    """One extracted PDF page."""

    page_number: int
    width: float
    height: float
    blocks: list[DocumentBlock] = Field(default_factory=list)


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
    warnings: list[str] = Field(default_factory=list)
