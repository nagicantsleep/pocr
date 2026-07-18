"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class OperatorTokenIdentity(BaseModel):
    """Identity claims bound to one configured operator token."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str
    user_id: str
    roles: tuple[str, ...]

    @field_validator("tenant_id", "user_id")
    @classmethod
    def require_identifier(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("roles")
    @classmethod
    def require_roles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        roles = tuple(role.strip() for role in value if role.strip())
        if not roles:
            raise ValueError("must contain at least one role")
        return roles


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
    WORKERS: int = 1  # In-memory stores require single-process; override only with durable backends
    LOG_LEVEL: str = "INFO"
    JOB_BACKEND: str = "filesystem"
    JOB_TTL_HOURS: int = 24
    JOB_DIR: str = "/tmp/ocr_jobs"
    REDIS_URL: str = "redis://localhost:6379/0"
    RATE_LIMIT: str = "100/minute"
    API_KEY: Optional[str] = None

    # Operator auth. OPERATOR_TOKEN_MAP is JSON keyed by bearer token:
    # {"token": {"tenant_id": "tenant-a", "user_id": "user-1", "roles": ["operator"]}}
    OPERATOR_ENVIRONMENT: str = "development"
    OPERATOR_TOKEN_MAP: dict[str, OperatorTokenIdentity] = Field(default_factory=dict)

    # Temporary migration path: populate OPERATOR_TOKEN_MAP first, then remove this
    # single-token fallback. Production requires OPERATOR_ALLOW_LEGACY_TOKEN=true.
    OPERATOR_BEARER_TOKEN: Optional[str] = None
    OPERATOR_ALLOW_LEGACY_TOKEN: bool = False
    OPERATOR_LEGACY_PRINCIPAL: OperatorTokenIdentity = Field(
        default_factory=lambda: OperatorTokenIdentity(
            tenant_id="legacy",
            user_id="legacy-operator",
            roles=("operator",),
        )
    )

    # Webhook allowlist (comma-separated hostnames). When empty, all HTTPS hosts allowed.
    WEBHOOK_ALLOWED_HOSTS: str = ""

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
    STRUCTURED_JOB_STALE_SECONDS: int = 300
    STANDARDIZER_RATE_LIMIT_KEY: str = "standardizer:openrouter:minute"
    STANDARDIZER_RATE_LIMIT: int = 20
    STANDARDIZER_RATE_LIMIT_TTL_SECONDS: int = 60
    STANDARDIZER_RETRYABLE_STATUS_CODES: str = "429,502,503,504"
    INVOICE_JP_DURABLE_MODE: bool = False
    INVOICE_OUTBOX_TOPIC: str = "invoice.events"
    INVOICE_OUTBOX_RETRY_TOPIC: str = "invoice.events.retry"
    INVOICE_OUTBOX_DLQ_TOPIC: str = "invoice.events.dlq"
    INVOICE_OUTBOX_MAX_RETRIES: int = 3
    INVOICE_OUTBOX_RETRY_DELAY_SECONDS: float = 1.0
    INVOICE_OUTBOX_CONSUMER_GROUP: str = "pocr-invoice-outbox"
    INVOICE_OUTBOX_BATCH_SIZE: int = 100
    INVOICE_OUTBOX_POLL_SECONDS: float = 1.0

    # Storage
    STORAGE_BACKEND: str = "local"
    STORAGE_PATH: str = "./data/storage"
    STORAGE_S3_BUCKET: str | None = None
    STORAGE_S3_ENDPOINT_URL: str | None = None
    STORAGE_S3_REGION: str = "us-east-1"
    STORAGE_S3_ACCESS_KEY_ID: str | None = None
    STORAGE_S3_SECRET_ACCESS_KEY: str | None = None
    STORAGE_S3_FORCE_PATH_STYLE: bool = False

    # Invoice extraction
    INVOICE_ENABLE_EXTRACTION: bool = True
    INVOICE_DEFAULT_LANG: str = "japan"
    INVOICE_REVIEW_THRESHOLD: float = 0.85
    INVOICE_INCLUDE_OCR: bool = False
    INVOICE_MAX_AUTO_APPROVE_AMOUNT: int = 1000000
    INVOICE_ENABLE_VENDOR_MATCHING: bool = False
    INVOICE_ENABLE_DUPLICATE_CHECK: bool = False
    INVOICE_STORAGE_BACKEND: str = "postgres"
    INVOICE_STORAGE_PATH: str = "./data/invoices"
    INVOICE_ENABLE_LLM_EXTRACTOR: bool = False
    INVOICE_LLM_PROVIDER: str = ""
    INVOICE_LLM_MODEL: str = ""

    # Visual table detection
    TABLE_VISUAL_ENABLED: bool = True
    TABLE_VISUAL_MIN_LINE_LENGTH: int = 40
    TABLE_VISUAL_KERNEL_SIZE: int = 40

    # Quality gate
    QUALITY_GATE_THRESHOLD: float = 0.40
    LANG_DETECT_LOCALE_HINT: str | None = None

    # PDF Rendering
    PDF_RENDER_DPI: int = 200
    PDF_MAX_PAGES: int = 50

    # Image Preprocessing
    PREPROCESS_DESKEW: bool = True
    PREPROCESS_DENOISE: bool = True
    PREPROCESS_BINARIZE: bool = True
    PREPROCESS_MAX_SKEW_ANGLE: float = 15.0

    # Search
    SEARCH_EMBEDDING_MODEL: str = "text-embedding-3-small"
    SEARCH_EMBEDDING_API_KEY: str | None = None
    SEARCH_DEFAULT_ALPHA: float = 0.7
    SEARCH_DEFAULT_LIMIT: int = 20

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

    @property
    def is_production(self) -> bool:
        """Whether operator authentication must fail closed."""
        return self.OPERATOR_ENVIRONMENT.strip().lower() in {"prod", "production"}

    @property
    def legacy_operator_token_enabled(self) -> bool:
        """Allow the old single-token gate only during an explicit migration."""
        return bool(self.OPERATOR_BEARER_TOKEN) and (
            self.OPERATOR_ALLOW_LEGACY_TOKEN or not self.is_production
        )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
