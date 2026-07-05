from __future__ import annotations

from pathlib import Path
from typing import Optional

import asyncpg

from .config import get_settings

_pool: Optional[asyncpg.Pool] = None


async def init_db() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool

    settings = get_settings()
    _pool = await asyncpg.create_pool(
        dsn=settings.database_dsn,
        min_size=1,
        max_size=20,
        command_timeout=60,
    )
    return _pool


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def get_db_pool() -> asyncpg.Pool:
    if _pool is None:
        await init_db()
    return _pool


async def get_connection() -> asyncpg.Connection:
    settings = get_settings()
    return await asyncpg.connect(dsn=settings.database_dsn)


async def initialize_schema() -> None:
    pool = await get_db_pool()
    sql_path = Path(__file__).resolve().parents[2] / "scripts" / "init_db.sql"
    schema_sql = sql_path.read_text(encoding="utf-8")
    async with pool.acquire() as connection:
        await connection.execute(schema_sql)
