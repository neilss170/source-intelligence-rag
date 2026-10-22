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
    # Postgres with pgvector; docker compose publishes it on 5433.
    database_url: str = (
        "postgresql+psycopg://si:si_dev_password@127.0.0.1:5433/source_intelligence"
    )
    redis_url: str = "redis://127.0.0.1:6380/0"
    # Session cookies are Secure (HTTPS only) everywhere but development.
    cookie_secure: bool | None = None
    session_days: int = Field(default=30, ge=1, le=365)
    min_password_length: int = Field(default=10, ge=8, le=128)
    max_file_size_mb: int = Field(default=10, ge=1, le=100)
    max_upload_files: int = Field(default=10, ge=1, le=50)
    chat_api_key: str | None = None
    chat_api_base_url: str = "https://api.openai.com/v1"
    chat_model: str = "gpt-4.1-mini"
    local_chat_model: str = "Qwen/Qwen2.5-1.5B-Instruct"
    llm_answers_enabled: bool = True
    # Comma-separated models to switch to when CHAT_MODEL's quota runs out.
    chat_fallback_models: str = ""
    # Passage characters sent whole before search takes over (~4k tokens).
    workspace_context_chars: int = Field(default=16_000, ge=0)
    # Passages handed to the model when the workspace is searched.
    retrieval_top_k: int = Field(default=8, ge=1, le=20)
    # Candidates each of BM25 and dense search pass to the reranker.
    retrieval_candidates: int = Field(default=20, ge=5, le=100)
    dense_model: str = "BAAI/bge-small-en-v1.5"
    dense_min_score: float = Field(default=0.2, ge=0, le=1)
    # Reranker relevance (0-1) below which passages are dropped...
    rerank_min_probability: float = Field(default=0.02, ge=0, le=1)
    # ...except this many of the best, which are always kept.
    rerank_min_keep: int = Field(default=3, ge=0)
    # Check each cited sentence against its passages with an NLI model.
    verify_citations: bool = True
    nli_model: str = "cross-encoder/nli-deberta-v3-xsmall"
    support_threshold: float = Field(default=0.5, ge=0, le=1)
    # Let the model run read-only SQL over uploaded CSV and XLSX files.
    table_queries_enabled: bool = True
    # Remove emails, phone numbers and LinkedIn URLs at ingestion.
    redact_contact_details: bool = True
    # OCR scanned PDFs. Needs Tesseract OCR installed and on PATH.
    ocr_enabled: bool = False
    reranker_enabled: bool = True
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    tavily_api_key: str | None = None
    web_search_enabled: bool = True
    search_country: str = "india"
    search_max_results: int = Field(default=3, ge=1, le=5)
    data_dir: Path = BACKEND_DIR / "data"

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.app_env != "development"

    @property
    def fallback_models(self) -> tuple[str, ...]:
        return tuple(
            model.strip()
            for model in self.chat_fallback_models.split(",")
            if model.strip()
        )

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
