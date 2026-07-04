import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from core.config import get_settings
from core.database import close_db, init_db, initialize_schema
from routers import ledger, monitoring, reports

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gl_reporting")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await initialize_schema()
    yield
    await close_db()


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.perf_counter()
    logger.info("request %s %s", request.method, request.url.path)
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    logger.info("response %s %s %s in %.2fms", request.method, request.url.path, response.status_code, duration_ms)
    return response


app.include_router(reports.router)
app.include_router(ledger.router)
app.include_router(monitoring.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
