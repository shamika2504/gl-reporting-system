from fastapi import APIRouter, HTTPException

from services.gl_service import (
    detect_anomalies,
    get_balance_sheet,
    get_income_statement,
    get_key_ratios,
    get_trial_balance,
)

router = APIRouter(prefix="/ledger", tags=["ledger"])


@router.get("/")
async def list_ledger_entries() -> dict[str, str]:
    return {"message": "Ledger router ready"}


@router.get("/trial-balance/{period_id}")
async def trial_balance(period_id: int) -> dict[str, object]:
    try:
        return await get_trial_balance(period_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/balance-sheet/{period_id}")
async def balance_sheet(period_id: int) -> dict[str, object]:
    try:
        return await get_balance_sheet(period_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/income-statement/{period_id}")
async def income_statement(period_id: int) -> dict[str, object]:
    try:
        return await get_income_statement(period_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/ratios/{period_id}")
async def ratios(period_id: int) -> dict[str, float]:
    try:
        return await get_key_ratios(period_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/anomalies/{period_id}")
async def anomalies(period_id: int) -> list[dict[str, object]]:
    try:
        return await detect_anomalies(period_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
