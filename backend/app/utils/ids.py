"""Identifier utilities."""

from uuid import uuid4


def generate_document_id() -> str:
    """Generate a non-predictable document identifier."""

    return f"doc_{uuid4().hex}"


def generate_job_id() -> str:
    """Generate a non-predictable processing job identifier."""

    return f"job_{uuid4().hex}"
