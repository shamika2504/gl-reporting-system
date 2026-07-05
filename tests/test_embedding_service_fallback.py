import unittest
from unittest.mock import AsyncMock, patch

from backend.services.embedding_service import EmbeddingService


class EmbeddingServiceFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_retrieve_relevant_rules_returns_fallback_when_embedding_fails(self) -> None:
        service = EmbeddingService()

        with patch.object(service, "_embed_text", new=AsyncMock(side_effect=RuntimeError("OpenAI quota exceeded or rate limited"))), patch(
            "backend.services.embedding_service.EmbeddingService._get_qdrant_client"
        ) as mock_client:
            mock_client.return_value.get_collection.side_effect = RuntimeError("collection missing")

            result = await service.retrieve_relevant_rules("balance sheet", top_k=3)

        self.assertTrue(result)
        self.assertIn("Revenue recognition", result[0])


if __name__ == "__main__":
    unittest.main()
