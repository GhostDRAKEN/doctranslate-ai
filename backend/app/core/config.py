"""Application configuration."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    app_name: str = Field(default="DocTranslate AI", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    api_prefix: str = Field(default="/api", alias="API_PREFIX")
    max_file_size_mb: int = Field(default=10, alias="MAX_FILE_SIZE_MB")
    max_page_count: int = Field(default=10, alias="MAX_PAGE_COUNT")
    # Demo/MVP mode keeps uploads intentionally small. Batch mode is
    # experimental plumbing for future long-document processing.
    batch_size_pages: int = Field(default=5, alias="BATCH_SIZE_PAGES")
    enable_batch_mode: bool = Field(default=False, alias="ENABLE_BATCH_MODE")
    max_batch_experimental_pages: int = Field(
        default=100,
        alias="MAX_BATCH_EXPERIMENTAL_PAGES",
    )
    storage_tmp_dir: str = Field(default="storage/tmp", alias="STORAGE_TMP_DIR")
    mock_translation_enabled: bool = Field(
        default=True,
        alias="MOCK_TRANSLATION_ENABLED",
    )
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")
    llm_fallback_to_mock: bool = Field(default=True, alias="LLM_FALLBACK_TO_MOCK")
    llm_timeout_seconds: float = Field(default=30.0, alias="LLM_TIMEOUT_SECONDS")
    llm_max_retries: int = Field(default=1, alias="LLM_MAX_RETRIES")
    overlay_bbox_padding: float = Field(default=1.5, alias="OVERLAY_BBOX_PADDING")
    min_semantic_confidence_overlay: float = Field(
        default=0.45,
        alias="MIN_SEMANTIC_CONFIDENCE_OVERLAY",
    )
    debug_overlay: bool = Field(default=False, alias="DEBUG_OVERLAY")
    debug_semantic: bool = Field(default=False, alias="DEBUG_SEMANTIC")
    debug_overlay_bbox: bool = Field(default=False, alias="DEBUG_OVERLAY_BBOX")
    cors_origins: str = Field(
        default=(
            "http://localhost:3000,"
            "http://localhost:3001,"
            "http://127.0.0.1:3000,"
            "http://127.0.0.1:3001"
        ),
        alias="CORS_ORIGINS",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def cors_origin_list(self) -> list[str]:
        """Return configured CORS origins as a normalized list."""

        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()
