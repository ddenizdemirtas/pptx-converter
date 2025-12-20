"""Configuration management for the converter service."""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Service configuration
    service_name: str = "pptx-converter"
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "INFO"

    # Concurrency control
    concurrency: int = Field(
        default=1, description="Max concurrent conversions per container")

    # Conversion settings
    conversion_timeout_seconds: int = Field(
        default=180, description="Max time for LibreOffice conversion"
    )
    max_input_size_mb: int = Field(
        default=100, description="Max PPTX file size in MB")

    # Temp directory for processing
    temp_dir: str = "/tmp/converter"

    # LibreOffice settings
    libreoffice_bin: str = "soffice"

    # AWS S3 settings (for local dev, can use MinIO)
    # Note: On Lambda, leave these unset - Lambda provides credentials automatically
    aws_region: str = "us-east-2"
    # Use S3_ prefix to avoid conflict with Lambda's reserved AWS_* env vars
    s3_access_key_id: str | None = Field(
        default=None, alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: str | None = Field(
        default=None, alias="S3_SECRET_ACCESS_KEY")
    s3_endpoint_url: str | None = Field(
        default=None, description="Custom S3 endpoint (for MinIO/LocalStack)"
    )

    model_config = {
        "env_prefix": "",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        "populate_by_name": True,
    }


# Global settings instance
settings = Settings()
