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
    mock_translation_enabled: bool = Field(
        default=True,
        alias="MOCK_TRANSLATION_ENABLED",
    )
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
