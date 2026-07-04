from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "GL Regulatory Reporting System"
    environment: str = "development"
    debug: bool = True

    database_host: str = "localhost"
    database_port: int = 5432
    database_name: str = "gl_reporting"
    database_user: str = "gl_user"
    database_password: str = "gl_password"
    database_url: str | None = None

    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"
    aws_s3_bucket: str = "gl-reporting-dev"
    aws_secrets_manager_secret_id: str = "gl-reporting/dev"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def database_dsn(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgres://{self.database_user}:{self.database_password}"
            f"@{self.database_host}:{self.database_port}/{self.database_name}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
