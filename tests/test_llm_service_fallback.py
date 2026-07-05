import unittest

from backend.services.llm_service import LLMService


class LLMServiceFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_api_key_returns_placeholder_content(self) -> None:
        service = LLMService()
        result = await service.generate_executive_summary(
            {"assets": []},
            {"revenue": []},
            {"current_ratio": 1.0},
            ["Rule 1"],
            job_id=None,
        )
        self.assertIn("placeholder", result.lower())


if __name__ == "__main__":
    unittest.main()
