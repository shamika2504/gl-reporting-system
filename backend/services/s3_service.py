from __future__ import annotations

import asyncio
from typing import Any

import boto3

try:
    from core.config import get_settings
except ModuleNotFoundError:  # pragma: no cover - allows repo-root imports
    from backend.core.config import get_settings


class S3Service:
    """Service for uploading generated reports to S3 and returning presigned URLs."""

    def __init__(self) -> None:
        self.name = "s3-service"

    def _upload_report_sync(self, job_id: str, pdf_bytes: bytes) -> str:
        settings = get_settings()
        bucket_name = settings.aws_s3_bucket
        key = f"reports/{job_id}.pdf"
        client = boto3.client(
            "s3",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id or None,
            aws_secret_access_key=settings.aws_secret_access_key or None,
        )
        client.put_object(
            Bucket=bucket_name,
            Key=key,
            Body=pdf_bytes,
            ContentType="application/pdf",
        )
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": key},
            ExpiresIn=86400,
        )

    async def upload_report(self, job_id: str, pdf_bytes: bytes) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._upload_report_sync, job_id, pdf_bytes)
