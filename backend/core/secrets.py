from __future__ import annotations

from typing import Any

import boto3

from .config import get_settings


class SecretsManager:
    def __init__(self) -> None:
        settings = get_settings()
        self.client = boto3.client(
            "secretsmanager",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id or None,
            aws_secret_access_key=settings.aws_secret_access_key or None,
        )
        self.secret_id = settings.aws_secrets_manager_secret_id

    def get_secret(self) -> dict[str, Any]:
        response = self.client.get_secret_value(SecretId=self.secret_id)
        return response.get("SecretString", "{}") if isinstance(response.get("SecretString"), str) else {}
