from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    otel_exporter_otlp_endpoint: str = ""
    max_upload_bytes: int = 10 * 1024 * 1024  # 10 MB

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
