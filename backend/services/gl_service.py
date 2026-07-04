from __future__ import annotations

from typing import Any

from core.database import get_db_pool


def _round_money(value: float | int) -> float:
    return round(float(value), 2)


def _normalize_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else " " for ch in name.lower())
    return "_".join(cleaned.split())


async def _get_period(connection: Any, period_id: int) -> dict[str, Any] | None:
    return await connection.fetchrow(
        "SELECT period_id, period_name, start_date, end_date, status FROM reporting_periods WHERE period_id = $1",
        period_id,
    )


async def _get_account_metadata(connection: Any) -> dict[str, dict[str, Any]]:
    rows = await connection.fetch(
        "SELECT account_code, account_name, category, sub_category, normal_balance FROM chart_of_accounts"
    )
    return {
        row["account_code"]: {
            "account_name": row["account_name"],
            "category": row["category"],
            "sub_category": row["sub_category"],
            "normal_balance": row["normal_balance"],
        }
        for row in rows
    }


async def _get_period_entries(connection: Any, period_id: int) -> list[dict[str, Any]]:
    rows = await connection.fetch(
        "SELECT entry_date, account_code, description, debit, credit FROM journal_entries WHERE period_id = $1",
        period_id,
    )
    return [dict(row) for row in rows]


async def _get_previous_period_entries(connection: Any, period_id: int) -> list[dict[str, Any]]:
    period_row = await connection.fetchrow(
        "SELECT start_date FROM reporting_periods WHERE period_id = $1",
        period_id,
    )
    if period_row is None:
        return []

    previous_period = await connection.fetchrow(
        "SELECT period_id FROM reporting_periods WHERE start_date < $1 ORDER BY start_date DESC LIMIT 1",
        period_row["start_date"],
    )
    if previous_period is None:
        return []

    rows = await connection.fetch(
        "SELECT account_code, debit, credit FROM journal_entries WHERE period_id = $1",
        previous_period["period_id"],
    )
    return [dict(row) for row in rows]


async def get_trial_balance(period_id: int) -> dict[str, Any]:
    pool = await get_db_pool()
    async with pool.acquire() as connection:
        period = await _get_period(connection, period_id)
        if period is None:
            raise LookupError(f"Period {period_id} not found")

        accounts = await _get_account_metadata(connection)
        entries = await _get_period_entries(connection, period_id)

    balances: dict[str, dict[str, Any]] = {}
    for entry in entries:
        account_code = entry["account_code"]
        if account_code is None:
            continue
        metadata = accounts.get(account_code, {})
        if account_code not in balances:
            balances[account_code] = {
                "account_code": account_code,
                "account_name": metadata.get("account_name", account_code),
                "category": metadata.get("category", "unknown"),
                "normal_balance": metadata.get("normal_balance", "debit"),
                "debit": 0.0,
                "credit": 0.0,
            }
        balances[account_code]["debit"] += float(entry.get("debit") or 0.0)
        balances[account_code]["credit"] += float(entry.get("credit") or 0.0)

    trial_balance = []
    for account_code, values in sorted(balances.items()):
        debit = _round_money(values["debit"])
        credit = _round_money(values["credit"])
        net_balance = _round_money(debit - credit) if values["normal_balance"] == "debit" else _round_money(credit - debit)
        trial_balance.append(
            {
                "account_code": account_code,
                "account_name": values["account_name"],
                "category": values["category"],
                "normal_balance": values["normal_balance"],
                "debit": debit,
                "credit": credit,
                "net_balance": net_balance,
            }
        )

    return {"period_id": period_id, "period_name": period["period_name"], "accounts": trial_balance}


async def get_balance_sheet(period_id: int) -> dict[str, Any]:
    pool = await get_db_pool()
    async with pool.acquire() as connection:
        period = await _get_period(connection, period_id)
        if period is None:
            raise LookupError(f"Period {period_id} not found")

        accounts = await _get_account_metadata(connection)
        entries = await _get_period_entries(connection, period_id)

    account_balances: dict[str, float] = {}
    for entry in entries:
        account_code = entry.get("account_code")
        if not account_code:
            continue
        metadata = accounts.get(account_code, {})
        normal_balance = metadata.get("normal_balance", "debit")
        current_balance = account_balances.get(account_code, 0.0)
        debit = float(entry.get("debit") or 0.0)
        credit = float(entry.get("credit") or 0.0)
        signed_balance = debit - credit if normal_balance == "debit" else credit - debit
        account_balances[account_code] = current_balance + signed_balance

    def add_account(mapping: dict[str, float], account_name: str, balance: float) -> None:
        key = _normalize_name(account_name)
        mapping[key] = _round_money(balance)

    current_assets: dict[str, float] = {}
    non_current_assets: dict[str, float] = {}
    current_liabilities: dict[str, float] = {}
    equity_accounts: dict[str, float] = {}

    for account_code, balance in sorted(account_balances.items()):
        metadata = accounts.get(account_code, {})
        name = metadata.get("account_name", "")
        normalized_name = _normalize_name(name)
        category = metadata.get("category")
        if category == "asset":
            if any(token in normalized_name for token in ["cash", "receivable", "inventory", "prepaid", "short", "investment", "current"]):
                add_account(current_assets, name, balance)
            else:
                add_account(non_current_assets, name, balance)
        elif category == "liability":
            if any(token in normalized_name for token in ["payable", "accrued", "debt", "tax", "deferred", "deposit", "lease", "short"]):
                add_account(current_liabilities, name, balance)
        elif category == "equity":
            add_account(equity_accounts, name, balance)

    total_current_assets = _round_money(sum(current_assets.values()))
    total_non_current_assets = _round_money(sum(non_current_assets.values()))
    total_assets = _round_money(total_current_assets + total_non_current_assets)
    total_liabilities = _round_money(sum(current_liabilities.values()))
    total_equity = _round_money(sum(equity_accounts.values()))
    total_liabilities_and_equity = _round_money(total_liabilities + total_equity)

    return {
        "assets": {
            "current_assets": current_assets,
            "total_current_assets": total_current_assets,
            "non_current_assets": non_current_assets,
            "total_assets": total_assets,
        },
        "liabilities": {
            "current_liabilities": current_liabilities,
            "total_liabilities": total_liabilities,
        },
        "equity": {
            "retained_earnings": equity_accounts.get("retained_earnings", 0.0),
            "total_equity": total_equity,
        },
        "total_liabilities_and_equity": total_liabilities_and_equity,
        "balanced": abs(total_assets - total_liabilities_and_equity) <= 0.01,
    }


async def get_income_statement(period_id: int) -> dict[str, Any]:
    pool = await get_db_pool()
    async with pool.acquire() as connection:
        period = await _get_period(connection, period_id)
        if period is None:
            raise LookupError(f"Period {period_id} not found")

        accounts = await _get_account_metadata(connection)
        entries = await _get_period_entries(connection, period_id)

    account_balances: dict[str, float] = {}
    for entry in entries:
        account_code = entry.get("account_code")
        if not account_code:
            continue
        metadata = accounts.get(account_code, {})
        normal_balance = metadata.get("normal_balance", "debit")
        current_balance = account_balances.get(account_code, 0.0)
        debit = float(entry.get("debit") or 0.0)
        credit = float(entry.get("credit") or 0.0)
        signed_balance = debit - credit if normal_balance == "debit" else credit - debit
        account_balances[account_code] = current_balance + signed_balance

    revenue_accounts: dict[str, float] = {}
    expense_accounts: dict[str, float] = {}
    for account_code, balance in sorted(account_balances.items()):
        metadata = accounts.get(account_code, {})
        name = metadata.get("account_name", "")
        normalized_name = _normalize_name(name)
        if metadata.get("category") == "revenue":
            revenue_accounts[normalized_name] = _round_money(balance)
        elif metadata.get("category") == "expense":
            expense_accounts[normalized_name] = _round_money(balance)

    total_revenue = _round_money(sum(revenue_accounts.values()))
    total_expenses = _round_money(sum(expense_accounts.values()))
    net_income = _round_money(total_revenue - total_expenses)
    net_margin_pct = _round_money((net_income / total_revenue * 100) if total_revenue else 0.0)

    return {
        "revenue": revenue_accounts,
        "total_revenue": total_revenue,
        "expenses": expense_accounts,
        "total_expenses": total_expenses,
        "net_income": net_income,
        "net_margin_pct": net_margin_pct,
    }


async def get_key_ratios(period_id: int) -> dict[str, float]:
    balance_sheet = await get_balance_sheet(period_id)
    income_statement = await get_income_statement(period_id)

    current_assets = float(balance_sheet["assets"]["total_current_assets"])
    current_liabilities = float(balance_sheet["liabilities"]["total_liabilities"])
    total_equity = float(balance_sheet["equity"]["total_equity"])
    total_assets = float(balance_sheet["assets"]["total_assets"])
    net_income = float(income_statement["net_income"])
    total_revenue = float(income_statement["total_revenue"])

    current_ratio = _round_money(current_assets / current_liabilities) if current_liabilities else 0.0
    debt_to_equity = _round_money(current_liabilities / total_equity) if total_equity else 0.0
    net_margin = _round_money(net_income / total_revenue) if total_revenue else 0.0
    return_on_assets = _round_money(net_income / total_assets) if total_assets else 0.0

    return {
        "current_ratio": current_ratio,
        "debt_to_equity": debt_to_equity,
        "net_margin": net_margin,
        "return_on_assets": return_on_assets,
    }


async def detect_anomalies(period_id: int) -> list[dict[str, Any]]:
    pool = await get_db_pool()
    async with pool.acquire() as connection:
        period = await _get_period(connection, period_id)
        if period is None:
            raise LookupError(f"Period {period_id} not found")

        accounts = await _get_account_metadata(connection)
        entries = await _get_period_entries(connection, period_id)
        previous_entries = await _get_previous_period_entries(connection, period_id)

    account_balances: dict[str, float] = {}
    previous_balances: dict[str, float] = {}
    for entry in entries:
        account_code = entry.get("account_code")
        if not account_code:
            continue
        metadata = accounts.get(account_code, {})
        normal_balance = metadata.get("normal_balance", "debit")
        debit = float(entry.get("debit") or 0.0)
        credit = float(entry.get("credit") or 0.0)
        signed_balance = debit - credit if normal_balance == "debit" else credit - debit
        account_balances[account_code] = account_balances.get(account_code, 0.0) + signed_balance

    for entry in previous_entries:
        account_code = entry.get("account_code")
        if not account_code:
            continue
        metadata = accounts.get(account_code, {})
        normal_balance = metadata.get("normal_balance", "debit")
        debit = float(entry.get("debit") or 0.0)
        credit = float(entry.get("credit") or 0.0)
        signed_balance = debit - credit if normal_balance == "debit" else credit - debit
        previous_balances[account_code] = previous_balances.get(account_code, 0.0) + signed_balance

    anomalies: list[dict[str, Any]] = []

    for account_code, current_balance in sorted(account_balances.items()):
        metadata = accounts.get(account_code, {})
        previous_balance = previous_balances.get(account_code, 0.0)
        if previous_balance != 0 and abs(current_balance - previous_balance) / abs(previous_balance) > 0.2:
            anomalies.append(
                {
                    "account": metadata.get("account_name", account_code),
                    "type": "period_change",
                    "severity": "high",
                    "detail": f"Balance changed by {round(((current_balance - previous_balance) / abs(previous_balance)) * 100, 2)}% versus prior period",
                }
            )

        if metadata.get("normal_balance") == "debit" and current_balance < 0:
            anomalies.append(
                {
                    "account": metadata.get("account_name", account_code),
                    "type": "normal_balance_violation",
                    "severity": "medium",
                    "detail": "Account has a negative balance inconsistent with a debit-normal account",
                }
            )
        elif metadata.get("normal_balance") == "credit" and current_balance > 0:
            anomalies.append(
                {
                    "account": metadata.get("account_name", account_code),
                    "type": "normal_balance_violation",
                    "severity": "medium",
                    "detail": "Account has a positive balance inconsistent with a credit-normal account",
                }
            )

        if metadata.get("category") == "revenue" and current_balance > 0:
            anomalies.append(
                {
                    "account": metadata.get("account_name", account_code),
                    "type": "revenue_debit_balance",
                    "severity": "high",
                    "detail": "Revenue account has a net debit balance",
                }
            )
        if metadata.get("category") == "expense" and current_balance < 0:
            anomalies.append(
                {
                    "account": metadata.get("account_name", account_code),
                    "type": "expense_credit_balance",
                    "severity": "high",
                    "detail": "Expense account has a net credit balance",
                }
            )

    for entry in entries:
        if float(entry.get("debit") or 0.0) != float(entry.get("credit") or 0.0):
            account_code = entry.get("account_code")
            metadata = accounts.get(account_code, {})
            anomalies.append(
                {
                    "account": metadata.get("account_name", account_code or "unknown"),
                    "type": "entry_mismatch",
                    "severity": "high",
                    "detail": f"Entry-level imbalance detected: debit {entry.get('debit')} vs credit {entry.get('credit')}",
                }
            )

    return anomalies
