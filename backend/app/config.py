from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./docvault.db"
    files_dir: str = "./files"  # the documents themselves, plus preview images
    max_upload_mb: int = 50

    secret_key: str = "change-me-in-production"
    token_expire_days: int = 30
    allow_registration: bool = True

    # Claude reads documents better than rules can. Empty key = rules and local OCR only.
    anthropic_api_key: str = ""
    llm_enabled: bool = True
    llm_model: str = "claude-haiku-5-5"
    llm_min_confidence: float = 0.5
    summary_language: str = "English"

    # Text reading
    ocr_enabled: bool = True
    ocr_max_pages: int = 10      # scanned PDFs: how many pages to OCR
    text_max_pages: int = 200    # text PDFs: how many pages to read

    def llm_ready(self) -> bool:
        import os
        return self.llm_enabled and bool(
            self.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
