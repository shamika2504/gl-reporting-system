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

    def _get_fallback_rules(self, query: str, top_k: int = 5) -> list[str]:
        query_lower = query.lower()
        fallback_rules = [
            "Revenue recognition should be recorded when performance obligations are satisfied and control transfers to the customer.",
            "Expenses should be matched to the periods in which the related revenues are earned or the economic benefits are consumed.",
            "Assets, liabilities, and equity should be classified and presented consistently on the balance sheet in accordance with GAAP.",
            "Material estimates, contingencies, and related disclosures should be reviewed for completeness and consistency.",
            "Unusual variances and control exceptions should be investigated and documented as part of the reporting process.",
        ]
        if "balance" in query_lower or "asset" in query_lower or "liability" in query_lower or "equity" in query_lower:
            return fallback_rules[:3]
        if "income" in query_lower or "revenue" in query_lower or "expense" in query_lower:
            return fallback_rules[:2]
        if "ratio" in query_lower or "disclosure" in query_lower:
            return fallback_rules[2:4]
        if "anomal" in query_lower or "variance" in query_lower or "control" in query_lower:
            return fallback_rules[-2:]
        return fallback_rules[:top_k]

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
        try:
            client = self._get_qdrant_client()
            client.get_collection(collection_name=self.collection_name)
        except Exception:
            return self._get_fallback_rules(query, top_k=top_k)

        try:
            embedding = await self._embed_text(query)
            results = client.search(
                collection_name=self.collection_name,
                query_vector=embedding,
                limit=top_k,
                with_payload=["text", "rule_id", "source"],
            )
            retrieved = [result.payload["text"] for result in results if result.payload]
            if retrieved:
                return retrieved
        except Exception:
            return self._get_fallback_rules(query, top_k=top_k)

        return self._get_fallback_rules(query, top_k=top_k)
