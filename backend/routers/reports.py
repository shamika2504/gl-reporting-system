from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.database import get_db_pool
from workers.report_tasks import generate_report as generate_report_task

router = APIRouter(prefix="/reports", tags=["reports"])


class GenerateReportRequest(BaseModel):
    period_id: int


@router.post("/generate")
async def generate_report(request: GenerateReportRequest) -> dict[str, Any]:
    job_id = uuid.uuid4()
    pool = await get_db_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            "INSERT INTO report_jobs (job_id, period_id, status) VALUES ($1, $2, 'pending')",
            job_id,
            request.period_id,
        )

    generate_report_task.apply_async(args=[request.period_id], task_id=str(job_id))
    return {"job_id": str(job_id), "status": "pending"}


@router.get("/status/{job_id}")
async def get_report_status(job_id: str) -> dict[str, Any]:
    try:
        parsed_job_id = uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid job_id") from exc

    pool = await get_db_pool()
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            "SELECT job_id, period_id, status, created_at, completed_at, s3_url, error_message FROM report_jobs WHERE job_id = $1",
            parsed_job_id,
        )

    if row is None:
        raise HTTPException(status_code=404, detail="Report job not found")

    return {
        "job_id": str(row["job_id"]),
        "status": row["status"],
        "s3_url": row["s3_url"],
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
    }


@router.get("/list")
async def list_reports() -> list[dict[str, Any]]:
    pool = await get_db_pool()
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            "SELECT job_id, period_id, status, created_at, completed_at, s3_url, error_message FROM report_jobs ORDER BY created_at DESC LIMIT 10"
        )

    return [
        {
            "job_id": str(row["job_id"]),
            "status": row["status"],
            "s3_url": row["s3_url"],
            "error_message": row["error_message"],
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
        }
        for row in rows
    ]
