"""Identifier utilities."""

from uuid import uuid4


def generate_document_id() -> str:
    """Generate a non-predictable document identifier."""

    return f"doc_{uuid4().hex}"
