"""Processing job API schemas."""

from typing import Literal

from pydantic import BaseModel, Field

DocumentStatus = Literal[
    "uploaded",
    "queued",
    "processing",
    "completed",
    "failed",
    "expired",
]

JobStep = Literal[
    "upload",
    "analysis",
    "extraction",
    "domain_detection",
    "translation",
    "terminology_check",
    "reconstruction",
    "validation_report",
    "done",
]


class ProcessGlossaryTerm(BaseModel):
    """Minimal glossary term accepted when launching a job."""

    source: str
    target: str
    required: bool = False


class ProcessDocumentRequest(BaseModel):
    """Request body for launching document processing."""

    target_language: str = "fr"
    glossary: list[ProcessGlossaryTerm] = Field(default_factory=list)


class ProcessDocumentResponse(BaseModel):
    """Response returned when a processing job is accepted."""

    job_id: str
    document_id: str
    status: Literal["queued"]
    translation_provider: str


class JobError(BaseModel):
    """Controlled error stored in job status."""

    code: str
    message: str


class DocumentStatusResponse(BaseModel):
    """Current processing status for a document."""

    document_id: str
    job_id: str | None
    status: DocumentStatus
    current_step: JobStep
    progress: int
    updated_at: str
    error: JobError | None = None
