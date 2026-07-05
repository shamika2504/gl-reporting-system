from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from workers.celery_app import celery_app
from workers.db import get_worker_connection

from services.embedding_service import EmbeddingService
from services.gl_service import detect_anomalies, get_balance_sheet, get_income_statement, get_key_ratios
from services.llm_service import LLMService
from services.pdf_service import PDFService
from services.s3_service import S3Service


async def _log_progress(job_id: str, event: str, details: dict[str, Any] | None = None) -> None:
    llm_service = LLMService()
    await llm_service._log_audit_event(
        job_id,
        event,
        "",
        details or {},
    )


async def _set_job_status(job_id: str, status: str, *, s3_url: str | None = None, error_message: str | None = None) -> None:
    connection = await get_worker_connection()
    try:
        if status == "complete":
            await connection.execute(
                "UPDATE report_jobs SET status = $1, s3_url = $2, completed_at = NOW(), error_message = NULL WHERE job_id = $3",
                status,
                s3_url,
                uuid.UUID(job_id),
            )
        else:
            await connection.execute(
                "UPDATE report_jobs SET status = $1, error_message = $2, completed_at = NOW() WHERE job_id = $3",
                status,
                error_message,
                uuid.UUID(job_id),
            )
    finally:
        await connection.close()


async def _fetch_audit_entries(job_id: str) -> list[dict[str, Any]]:
    connection = await get_worker_connection()
    try:
        rows = await connection.fetch(
            "SELECT event, model_version, timestamp FROM audit_log WHERE job_id = $1 ORDER BY timestamp ASC",
            uuid.UUID(job_id),
        )
    finally:
        await connection.close()
    return [
        {
            "event": row["event"],
            "model": row["model_version"],
            "timestamp": row["timestamp"],
        }
        for row in rows
    ]


async def _run_report_pipeline(job_id: str, period_id: int) -> dict[str, Any]:
    await _set_job_status(job_id, "processing")
    await _log_progress(job_id, "report_started", {"period_id": period_id})

    connection = await get_worker_connection()
    try:
        period_row = await connection.fetchrow(
            "SELECT period_name FROM reporting_periods WHERE period_id = $1",
            period_id,
        )
        if period_row is None:
            raise LookupError(f"Period {period_id} not found")
        period_name = str(period_row["period_name"])
    finally:
        await connection.close()

    await _log_progress(job_id, "period_loaded", {"period_name": period_name})

    balance_sheet = await get_balance_sheet(period_id)
    await _log_progress(job_id, "balance_sheet_ready", {"period_id": period_id})

    income_statement = await get_income_statement(period_id)
    await _log_progress(job_id, "income_statement_ready", {"period_id": period_id})

    ratios = await get_key_ratios(period_id)
    await _log_progress(job_id, "ratios_ready", {"period_id": period_id})

    anomalies = await detect_anomalies(period_id)
    await _log_progress(job_id, "anomalies_ready", {"anomaly_count": len(anomalies)})

    embedding_service = EmbeddingService()
    relevant_rules_balance = await embedding_service.retrieve_relevant_rules(
        "balance sheet elements, assets liabilities equity and GAAP classification",
        top_k=5,
    )
    relevant_rules_income = await embedding_service.retrieve_relevant_rules(
        "income statement revenue expenses and GAAP matching principles",
        top_k=5,
    )
    relevant_rules_ratios = await embedding_service.retrieve_relevant_rules(
        "financial ratios and GAAP disclosure guidance",
        top_k=5,
    )
    relevant_rules_anomalies = await embedding_service.retrieve_relevant_rules(
        "financial anomalies and GAAP reporting controls",
        top_k=5,
    )
    await _log_progress(
        job_id,
        "retrieved_rules",
        {
            "balance_sheet_rules": len(relevant_rules_balance),
            "income_statement_rules": len(relevant_rules_income),
            "ratios_rules": len(relevant_rules_ratios),
            "anomaly_rules": len(relevant_rules_anomalies),
        },
    )

    llm_service = LLMService()
    executive_summary = await llm_service.generate_executive_summary(
        balance_sheet,
        income_statement,
        ratios,
        relevant_rules_balance + relevant_rules_income + relevant_rules_ratios,
        job_id,
    )
    await _log_progress(job_id, "executive_summary_generated", {"length": len(executive_summary)})

    mda_commentary: dict[str, Any] = {}
    sections = [
        ("balance_sheet", balance_sheet, relevant_rules_balance),
        ("income_statement", income_statement, relevant_rules_income),
        ("ratios", ratios, relevant_rules_ratios),
    ]
    for section_name, section_data, relevant_rules in sections:
        commentary = await llm_service.generate_mda_commentary(
            section_name,
            section_data,
            relevant_rules,
            anomalies,
            job_id,
        )
        mda_commentary[section_name] = commentary
    await _log_progress(job_id, "mda_commentary_generated", {"sections": list(mda_commentary.keys())})

    anomaly_explanations = await llm_service.generate_anomaly_explanations(
        anomalies,
        relevant_rules_anomalies,
        job_id,
    )
    await _log_progress(job_id, "anomaly_explanations_generated", {"count": len(anomaly_explanations)})

    audit_entries = await _fetch_audit_entries(job_id)
    pdf_service = PDFService()
    pdf_bytes = await pdf_service.generate_report_pdf(
        period_name,
        balance_sheet,
        income_statement,
        ratios,
        anomalies,
        executive_summary,
        mda_commentary,
        anomaly_explanations,
        audit_entries,
    )
    await _log_progress(job_id, "pdf_generated", {"size_bytes": len(pdf_bytes)})

    s3_service = S3Service()
    s3_url = await s3_service.upload_report(job_id, pdf_bytes)
    await _log_progress(job_id, "s3_uploaded", {"url": s3_url})

    await _set_job_status(job_id, "complete", s3_url=s3_url)
    return {"job_id": job_id, "status": "complete", "s3_url": s3_url}


@celery_app.task(bind=True, max_retries=3, name="generate_report_task")
def generate_report_task(self, job_id: str, period_id: int) -> dict[str, Any]:
    try:
        return asyncio.run(_run_report_pipeline(job_id, period_id))
    except Exception as exc:
        asyncio.run(_set_job_status(job_id, "failed", error_message=str(exc)))
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=2**self.request.retries)
        raise
