import unittest
from unittest.mock import patch

from backend.services.s3_service import S3Service


class S3ServiceFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_report_without_credentials_returns_local_file_url(self) -> None:
        service = S3Service()

        with patch("backend.services.s3_service.get_settings") as mock_get_settings, patch(
            "backend.services.s3_service.boto3.client",
            side_effect=RuntimeError("missing credentials"),
        ):
            mock_get_settings.return_value.aws_s3_bucket = "bucket"
            mock_get_settings.return_value.aws_region = "us-east-1"
            mock_get_settings.return_value.aws_access_key_id = ""
            mock_get_settings.return_value.aws_secret_access_key = ""

            result = await service.upload_report("job-123", b"pdf")

        self.assertTrue(result.startswith("file:///"))
        self.assertIn("job-123", result)


if __name__ == "__main__":
    unittest.main()
