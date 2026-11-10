from pathlib import Path

from pydantic_settings import BaseSettings

_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    llm_timeout_s: float = 30.0
    otel_exporter_otlp_endpoint: str = ""
    max_upload_bytes: int = 10 * 1024 * 1024  # 10 MB
    invoice_db_path: str = str(_ROOT / "data" / "invoice_store.db")

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
