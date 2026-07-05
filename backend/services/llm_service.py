from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from anthropic import Anthropic

try:
    from core.config import get_settings
    from core.database import get_db_pool
except ModuleNotFoundError:  # pragma: no cover - allows repo-root imports
    from backend.core.config import get_settings
    from backend.core.database import get_db_pool

logger = logging.getLogger("gl_reporting")


class LLMService:
    """Service for generating narrative commentary with Anthropic Claude."""

    def __init__(self) -> None:
        self.model_name = "claude-sonnet-4-6"

    async def _call_claude(self, prompt: str, event: str, computed_values: dict[str, Any], job_id: str | None = None) -> str:
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise RuntimeError("Anthropic API key not configured")

        last_error: Exception | None = None
        for attempt in range(3):
            start = time.perf_counter()
            try:
                client = Anthropic(api_key=settings.anthropic_api_key)
                response = await asyncio.to_thread(
                    client.messages.create,
                    model=settings.anthropic_model,
                    max_tokens=1000,
                    messages=[{"role": "user", "content": prompt}],
                )
                content = response.content[0].text if response.content else ""
                await self._log_audit_event(job_id, event, prompt, computed_values)
                latency_ms = round((time.perf_counter() - start) * 1000, 2)
                logger.info("llm_call_complete job_id=%s latency_ms=%.2f", job_id or "none", latency_ms)
                return content
            except Exception as exc:  # pragma: no cover - runtime safety fallback
                last_error = exc
                if attempt == 2:
                    raise
                await asyncio.sleep(2**attempt)

        if last_error is not None:
            raise last_error
        raise RuntimeError("Claude request failed")

    async def _log_audit_event(
        self,
        job_id: str | None,
        event: str,
        prompt: str,
        computed_values: dict[str, Any],
    ) -> None:
        pool = await get_db_pool()
        async with pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO audit_log (job_id, event, prompt_used, model_version, computed_values, timestamp)
                VALUES ($1, $2, $3, $4, $5, NOW())
                """,
                job_id,
                event,
                prompt,
                self.model_name,
                json.dumps(computed_values, default=str),
            )

    async def generate_executive_summary(
        self,
        balance_sheet: dict[str, Any],
        income_statement: dict[str, Any],
        ratios: dict[str, Any],
        relevant_rules: list[str],
        job_id: str | None = None,
    ) -> str:
        prompt = (
            "You are preparing an executive summary for a regulatory reporting package. "
            "Use the provided financial data and explicitly reference the supplied GAAP rules in your response. "
            "Write 2-3 concise paragraphs and explain the business implications without inventing facts.\n\n"
            f"Financial data:\nBalance Sheet: {json.dumps(balance_sheet, default=str)}\n"
            f"Income Statement: {json.dumps(income_statement, default=str)}\n"
            f"Ratios: {json.dumps(ratios, default=str)}\n"
            f"Relevant GAAP rules:\n{chr(10).join(relevant_rules)}"
        )
        return await self._call_claude(prompt, "executive_summary", {"balance_sheet": balance_sheet, "income_statement": income_statement, "ratios": ratios, "relevant_rules": relevant_rules}, job_id)

    async def generate_mda_commentary(
        self,
        section: str,
        data: dict[str, Any],
        relevant_rules: list[str],
        anomalies: list[dict[str, Any]],
        job_id: str | None = None,
    ) -> str:
        prompt = (
            f"You are drafting MD&A commentary for the {section} section. "
            "Use the supplied financial data, explicitly reference the supplied GAAP rules, and mention material anomalies when relevant. "
            "Write a compact narrative suitable for a management discussion and analysis section.\n\n"
            f"Section data: {json.dumps(data, default=str)}\n"
            f"Anomalies: {json.dumps(anomalies, default=str)}\n"
            f"Relevant GAAP rules:\n{chr(10).join(relevant_rules)}"
        )
        return await self._call_claude(prompt, "mda_commentary", {"section": section, "data": data, "anomalies": anomalies, "relevant_rules": relevant_rules}, job_id)

    async def generate_anomaly_explanations(
        self,
        anomalies: list[dict[str, Any]],
        relevant_rules: list[str],
        job_id: str | None = None,
    ) -> list[dict[str, str]]:
        explanations: list[dict[str, str]] = []
        for anomaly in anomalies:
            prompt = (
                "You are explaining a financial anomaly in plain English for an audit-ready report. "
                "Explicitly reference the supplied GAAP rules in your analysis and provide a concise explanation plus a recommended action.\n\n"
                f"Anomaly: {json.dumps(anomaly, default=str)}\n"
                f"Relevant GAAP rules:\n{chr(10).join(relevant_rules)}"
            )
            explanation = await self._call_claude(
                prompt,
                "anomaly_explanation",
                {"anomaly": anomaly, "relevant_rules": relevant_rules},
                job_id,
            )
            explanations.append(
                {
                    "account": anomaly.get("account", "unknown"),
                    "type": anomaly.get("type", "unknown"),
                    "explanation": explanation,
                    "recommended_action": "Review the underlying transaction support and confirm whether the variance is due to timing, estimation, or a data issue.",
                }
            )
        return explanations
