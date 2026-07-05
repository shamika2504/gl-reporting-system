from __future__ import annotations

import asyncpg

try:
    from core.database import get_connection
except ModuleNotFoundError:  # pragma: no cover - allows repo-root imports
    from backend.core.database import get_connection


async def get_worker_connection() -> asyncpg.Connection:
    return await get_connection()
