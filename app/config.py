import os
from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
_IS_LAMBDA = "LAMBDA_TASK_ROOT" in os.environ


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"

    # AWS credentials (shared by DynamoDB and S3)
    DYNAMO_ACCESS_KEY_ID: str = ""
    DYNAMO_SECRET_ACCESS_KEY: str = ""
    DYNAMO_REGION: str = "us-east-2"

    # DynamoDB tables
    DYNAMO_REPORTS_TABLE: str = "epihack_reports"
    DYNAMO_SURVEYS_TABLE: str = "epihack_surveys"

    # S3
    S3_IMAGES_BUCKET: str = "epihack"

    # Cognito — comma-separated lists, one entry per frontend app client.
    # Secrets must be in the same order as IDs; use an empty entry if a client has no secret.
    # e.g. COGNITO_CLIENT_IDS=abc123,def456
    #      COGNITO_CLIENT_SECRETS=secret1,
    COGNITO_REGION: str = "us-east-2"
    COGNITO_USER_POOL_ID: str = ""
    COGNITO_CLIENT_IDS: str = ""
    COGNITO_CLIENT_SECRETS: str = ""

    # Derived — set automatically from pool ID + region if blank
    COGNITO_AUTHORITY: str = ""

    # CORS
    CORS_ORIGINS: str = "http://localhost:5173"

    @property
    def cognito_authority(self) -> str:
        if self.COGNITO_AUTHORITY:
            return self.COGNITO_AUTHORITY
        return f"https://cognito-idp.{self.COGNITO_REGION}.amazonaws.com/{self.COGNITO_USER_POOL_ID}"

    @property
    def cognito_clients(self) -> dict[str, str]:
        """Returns {client_id: client_secret} for every registered app client."""
        ids = [x.strip() for x in self.COGNITO_CLIENT_IDS.split(",") if x.strip()]
        secrets = [x.strip() for x in self.COGNITO_CLIENT_SECRETS.split(",")]
        secrets += [""] * (len(ids) - len(secrets))  # pad if fewer secrets than ids
        return dict(zip(ids, secrets))

    @property
    def allowed_client_ids(self) -> list[str]:
        return list(self.cognito_clients.keys())

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    class Config:
        env_file = None if _IS_LAMBDA else str(_ENV_FILE)
        case_sensitive = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
