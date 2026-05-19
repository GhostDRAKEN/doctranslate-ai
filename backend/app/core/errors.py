"""Standard application errors and exception handlers."""

from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse


def error_payload(
    code: str,
    message: str,
    details: Any | None = None,
) -> dict[str, dict[str, Any]]:
    """Build the standard API error response body."""

    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
        }
    }


class AppError(Exception):
    """Base exception for controlled application errors."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Any | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    """Convert application errors to the standard response format."""

    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(exc.code, exc.message, exc.details),
    )


async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    """Convert FastAPI HTTP exceptions to the standard response format."""

    detail = exc.detail
    if isinstance(detail, dict):
        code = str(detail.get("code", "HTTP_ERROR"))
        message = str(detail.get("message", "Une erreur HTTP est survenue."))
        details = detail.get("details")
    else:
        code = "HTTP_ERROR"
        message = str(detail)
        details = None

    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(code, message, details),
        headers=getattr(exc, "headers", None),
    )


async def unhandled_exception_handler(_: Request, __: Exception) -> JSONResponse:
    """Return a safe response for unexpected exceptions."""

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_payload(
            "INTERNAL_ERROR",
            "Une erreur interne est survenue.",
            None,
        ),
    )
