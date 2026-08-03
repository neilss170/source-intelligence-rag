from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "RAG Workspace API"
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    frontend_origin: str = "http://localhost:5173"
    max_file_size_mb: int = Field(default=10, ge=1, le=100)
    max_upload_files: int = Field(default=10, ge=1, le=50)
    chat_api_key: str | None = None
    chat_api_base_url: str = "https://api.openai.com/v1"
    chat_model: str = "gpt-4.1-mini"
    tavily_api_key: str | None = None
    web_search_enabled: bool = True
    search_country: str = "india"
    search_max_results: int = Field(default=3, ge=1, le=5)
    data_dir: Path = BACKEND_DIR / "data"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "index"

    @property
    def metadata_dir(self) -> Path:
        return self.data_dir / "metadata"


@lru_cache
def get_settings() -> Settings:
    return Settings()
