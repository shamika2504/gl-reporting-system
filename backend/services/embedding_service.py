from __future__ import annotations

import asyncio
from typing import Any

try:
    from core.config import get_settings
except ModuleNotFoundError:  # pragma: no cover - allows repo-root imports
    from backend.core.config import get_settings


class EmbeddingService:
    """Service for storing and retrieving GAAP regulation embeddings."""

    def __init__(self) -> None:
        self.collection_name = "gaap_rules"
        self.embedding_model = "text-embedding-3-small"

    def _get_qdrant_client(self) -> Any:
        from qdrant_client import QdrantClient

        settings = get_settings()
        try:
            return QdrantClient(url=settings.qdrant_url, check_version=False)
        except TypeError:
            return QdrantClient(url=settings.qdrant_url)

    async def _embed_text(self, text: str) -> list[float]:
        from openai import OpenAI
        from openai import RateLimitError

        settings = get_settings()
        if not settings.openai_api_key:
            raise RuntimeError("OpenAI API key not configured")

        client = OpenAI(api_key=settings.openai_api_key)
        try:
            response = await asyncio.to_thread(
                client.embeddings.create,
                model=self.embedding_model,
                input=text,
            )
            return response.data[0].embedding
        except RateLimitError as exc:
            raise RuntimeError("OpenAI quota exceeded or rate limited") from exc

    async def embed_regulations(self, rules: list[dict[str, str]]) -> int:
        from qdrant_client.http.models import PointStruct

        client = self._get_qdrant_client()
        client.recreate_collection(
            collection_name=self.collection_name,
            vectors_config={"size": 1536, "distance": "Cosine"},
        )

        points: list[PointStruct] = []
        for index, rule in enumerate(rules, start=1):
            embedding = await self._embed_text(rule["text"])
            points.append(
                PointStruct(
                    id=index,
                    vector=embedding,
                    payload={
                        "rule_id": rule["rule_id"],
                        "source": rule.get("source", "GAAP"),
                        "text": rule["text"],
                    },
                )
            )

        client.upsert(collection_name=self.collection_name, points=points)
        return len(points)

    async def retrieve_relevant_rules(self, query: str, top_k: int = 5) -> list[str]:
        client = self._get_qdrant_client()
        try:
            client.get_collection(collection_name=self.collection_name)
        except Exception:
            return []

        embedding = await self._embed_text(query)
        results = client.search(
            collection_name=self.collection_name,
            query_vector=embedding,
            limit=top_k,
            with_payload=["text", "rule_id", "source"],
        )
        return [result.payload["text"] for result in results if result.payload]
