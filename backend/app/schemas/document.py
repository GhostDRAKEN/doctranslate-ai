"""Document API schemas."""

from pydantic import BaseModel


class DocumentUploadResponse(BaseModel):
    """Response returned after a successful PDF upload."""

    document_id: str
    filename: str
    status: str
