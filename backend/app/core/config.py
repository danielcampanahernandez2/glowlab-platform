"""Application configuration using Pydantic Settings."""
from typing import Dict, List, Union
from pydantic import AnyHttpUrl, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # General App Settings
    PROJECT_NAME: str = "Glowlab API"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    PORT: int = 8000
    HOST: str = "0.0.0.0"

    # CORS
    BACKEND_CORS_ORIGINS: Union[List[str], str] = [
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
    ]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, str) and v.startswith("["):
            import json
            try:
                return json.loads(v)
            except Exception:
                return [v]
        elif isinstance(v, list):
            return v
        return []

    # Database Settings
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "glowlab_user"
    POSTGRES_PASSWORD: str = "glowlab_secure_password"
    POSTGRES_DB: str = "glowlab_db"
    DATABASE_URL: Union[str, None] = None

    @computed_field
    @property
    def ASYNC_DATABASE_URI(self) -> str:
        if self.DATABASE_URL:
            # Asegurar que use el driver asyncpg si se pasa postgresql://
            if self.DATABASE_URL.startswith("postgresql://"):
                return self.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
            return self.DATABASE_URL
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    # Redis Settings
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0
    REDIS_URL: Union[str, None] = None

    @computed_field
    @property
    def REDIS_URI(self) -> str:
        if self.REDIS_URL:
            return self.REDIS_URL
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # Security & JWT (Phase 3 base)
    SECRET_KEY: str = "temporary-glowlab-dev-secret-key-change-in-production-min-32-chars"
    ADMIN_API_KEY: str = "glowlab-admin-supersecret-key-2026"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Evolution API Settings
    EVOLUTION_API_URL: str = "https://evolution-api-production-2fb7.up.railway.app"
    EVOLUTION_API_KEY: str = "2663309dc1bc96fa057fc5630ac4de4d67061e76530f15f95c25c079e1ca188e"
    EVOLUTION_INSTANCE_NAME: str = "glowlab-bot"
    EVOLUTION_WEBHOOK_SECRET: Union[str, None] = None

    # AI Provider Settings (Configurable: "openai" | "deepseek")
    AI_PROVIDER: str = "openai"

    # OpenAI Settings
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_MONTHLY_BUDGET_USD: float = 25.0

    # DeepSeek Settings
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"

    def get_ai_endpoint(self) -> str:
        """Retorna el endpoint de completions según el proveedor activo."""
        if self.AI_PROVIDER.lower() == "deepseek":
            return f"{self.DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions"
        return "https://api.openai.com/v1/chat/completions"

    def get_ai_headers(self) -> Dict[str, str]:
        """Retorna los headers HTTP de autenticación para el proveedor activo."""
        if self.AI_PROVIDER.lower() == "deepseek":
            return {
                "Authorization": f"Bearer {self.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            }
        return {
            "Authorization": f"Bearer {self.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }

    def get_ai_model(self) -> str:
        """Retorna el nombre del modelo correspondiente al proveedor activo."""
        if self.AI_PROVIDER.lower() == "deepseek":
            return self.DEEPSEEK_MODEL
        return self.OPENAI_MODEL

    def has_active_ai_key(self) -> bool:
        """Indica si el proveedor activo tiene configurada su clave de API."""
        if self.AI_PROVIDER.lower() == "deepseek":
            return bool(self.DEEPSEEK_API_KEY)
        return bool(self.OPENAI_API_KEY)

    # Staff / Equipo de Glowlab
    STAFF_MEMBERS: Dict[str, str] = {
        "51992509246": "Lizbeth",
        "51925528059": "Anali",
    }

    # Configuración de Adelanto y Pagos
    PAYMENT_INFO: str = "Yape o Plin al número que te indicará la asesora"
    ADVANCE_AMOUNT: int = 20

    # Sentry Observability Settings
    SENTRY_DSN: Union[str, None] = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1
    SENTRY_ENVIRONMENT: Union[str, None] = None


settings = Settings()

