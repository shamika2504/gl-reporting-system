from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from anthropic import Anthropic

try:
    from core.config import get_settings
    from core.database import get_connection
except ModuleNotFoundError:  # pragma: no cover - allows repo-root imports
    from backend.core.config import get_settings
    from backend.core.database import get_connection

logger = logging.getLogger("gl_reporting")


class LLMService:
    """Service for generating narrative commentary with Anthropic Claude."""

    def __init__(self) -> None:
        self.model_name = "claude-sonnet-4-6"

    def _is_placeholder_key(self, api_key: str | None) -> bool:
        return not api_key or not api_key.strip() or api_key.strip().lower() in {"replace-me", "changeme", "your-api-key"}

    def _build_fallback_content(self, event: str, computed_values: dict[str, Any]) -> str:
        if event == "executive_summary":
            return (
                "Placeholder executive summary: the report was generated locally without an Anthropic API key. "
                "This narrative highlights the available financial metrics and indicates that production-quality wording "
                "should be supplied by the configured LLM provider."
            )
        if event == "mda_commentary":
            section = computed_values.get("section", "financial section")
            return (
                f"Placeholder MD&A commentary for {section}: the underlying figures are presented as-is and should be reviewed "
                "against the supporting schedules once the LLM service is configured."
            )
        if event == "anomaly_explanation":
            anomaly = computed_values.get("anomaly", {})
            account = anomaly.get("account", "the affected account")
            return (
                f"Placeholder anomaly explanation for {account}: the variance should be reviewed against the source transactions "
                "and supporting documentation once the LLM integration is enabled."
            )
        return "Placeholder content generated locally because the LLM provider is not configured."

    async def _call_claude(self, prompt: str, event: str, computed_values: dict[str, Any], job_id: str | None = None) -> str:
        settings = get_settings()
        if self._is_placeholder_key(settings.anthropic_api_key):
            logger.warning("Anthropic API key not configured; using placeholder narrative for event=%s", event)
            await self._log_audit_event(job_id, event, prompt, computed_values)
            return self._build_fallback_content(event, computed_values)

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
                    logger.warning("Anthropic call failed; using placeholder narrative for event=%s error=%s", event, exc)
                    await self._log_audit_event(job_id, event, prompt, computed_values)
                    return self._build_fallback_content(event, computed_values)
                await asyncio.sleep(2**attempt)

        if last_error is not None:
            await self._log_audit_event(job_id, event, prompt, computed_values)
            return self._build_fallback_content(event, computed_values)
        return self._build_fallback_content(event, computed_values)

    async def _log_audit_event(
        self,
        job_id: str | None,
        event: str,
        prompt: str,
        computed_values: dict[str, Any],
    ) -> None:
        connection = await get_connection()
        try:
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
        finally:
            await connection.close()

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
