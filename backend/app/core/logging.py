"""Logging configuration for the backend."""

import logging


def configure_logging() -> None:
    """Configure simple technical logging without document content."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
