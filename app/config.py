"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # PaddleOCR Settings
    PADDLEOCR_VERSION: str = "3.5.0"
    PADDLE_DEVICE: str = "cpu"
    MODEL_LANG: str = "en"
    MODEL_DOWNLOAD_URL: Optional[str] = None

    # Image Limits
    MAX_IMAGE_SIZE_MB: int = 20
    MAX_IMAGE_PIXELS: int = 16777216
    MAX_BATCH_SIZE: int = 20

    # OCR Engine Tuning
    DET_DB_THRESH: float = 0.3
    DET_DB_BOX_THRESH: float = 0.5
    REC_BATCH_NUM: int = 6
    USE_ANGLE_CLS: bool = True
    LAYOUT_ANALYSIS: bool = False
    TABLE_DETECTION: bool = False
    MIN_CONFIDENCE: float = 0.0
    INCLUDE_POLYGON: bool = True

    # Server / Deployment
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 4
    LOG_LEVEL: str = "INFO"
    JOB_BACKEND: str = "filesystem"
    JOB_TTL_HOURS: int = 24
    JOB_DIR: str = "/tmp/ocr_jobs"
    REDIS_URL: str = "redis://localhost:6379/0"
    RATE_LIMIT: str = "100/minute"
    API_KEY: Optional[str] = None

    # Structured standardization
    STANDARDIZER_PROVIDER: str = "heuristic"
    STANDARDIZER_MODEL: str = "openrouter/owl-alpha"
    STANDARDIZER_API_KEY: Optional[str] = None
    STANDARDIZER_BASE_URL: str = "https://openrouter.ai/api/v1"
    STANDARDIZER_SITE_URL: Optional[str] = None
    STANDARDIZER_APP_NAME: str = "pocr"
    POSTGRES_DSN: str = "postgresql://pocr:pocr@localhost:5432/pocr"
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    STRUCTURED_STANDARDIZE_TOPIC: str = "ocr.standardize"
    STRUCTURED_STANDARDIZE_RETRY_TOPIC: str = "ocr.standardize.retry"
    STRUCTURED_STANDARDIZE_DLQ_TOPIC: str = "ocr.standardize.dlq"
    STANDARDIZER_RATE_LIMIT_KEY: str = "standardizer:openrouter:minute"
    STANDARDIZER_RATE_LIMIT: int = 20
    STANDARDIZER_RATE_LIMIT_TTL_SECONDS: int = 60
    STANDARDIZER_RETRYABLE_STATUS_CODES: str = "429,502,503,504"

    # Async Processing
    ASYNC_WORKERS: int = 4

    @property
    def max_image_size_bytes(self) -> int:
        """Get max image size in bytes."""
        return self.MAX_IMAGE_SIZE_MB * 1024 * 1024

    @property
    def paddle_device(self) -> str:
        """Get normalized device string."""
        return self.PADDLE_DEVICE.lower().split(":")[0]

    @property
    def paddle_device_id(self) -> Optional[int]:
        """Get GPU device ID if specified."""
        device = self.PADDLE_DEVICE.lower()
        if ":" in device:
            parts = device.split(":")
            if len(parts) == 2 and parts[0] == "gpu":
                return int(parts[1])
        return None


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
