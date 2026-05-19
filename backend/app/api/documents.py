"""Document-related API routes."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Return backend health status."""

    return {
        "status": "ok",
        "service": "doctranslate-api",
    }
