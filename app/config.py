from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"

    # AWS credentials (shared by DynamoDB and S3)
    DYNAMO_ACCESS_KEY_ID: str = ""
    DYNAMO_SECRET_ACCESS_KEY: str = ""
    DYNAMO_REGION: str = "us-east-2"

    # DynamoDB tables
    DYNAMO_REPORTS_TABLE: str = "epihack_reports"

    # S3
    S3_IMAGES_BUCKET: str = "epihack"

    # CORS
    CORS_ORIGINS: str = "http://localhost:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    class Config:
        env_file = str(_ENV_FILE)
        case_sensitive = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
