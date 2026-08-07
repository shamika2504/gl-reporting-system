from __future__ import annotations

import asyncio
import random
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import asyncpg
from faker import Faker
from dotenv import load_dotenv

script_path = Path(__file__).resolve()
backend_dir = script_path.parent.parent / "backend"
if not (backend_dir / "core").exists():
    backend_dir = script_path.parent.parent
sys.path.append(str(backend_dir))

from core.config import get_settings  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

fake = Faker("en_US")
random.seed(42)


def build_account_catalog() -> list[tuple[str, str, str, str, str]]:
    catalog: list[tuple[str, str, str, str, str]] = []
    category_specs = [
        ("asset", "debit", ["Cash", "Accounts Receivable", "Inventory", "Prepaid Expenses", "Property Plant and Equipment", "Accumulated Depreciation", "Short Term Investments", "Long Term Investments", "Intangible Assets", "Other Assets"]),
        ("liability", "credit", ["Accounts Payable", "Accrued Expenses", "Short Term Debt", "Long Term Debt", "Deferred Revenue", "Taxes Payable", "Customer Deposits", "Warranty Liability", "Lease Liability", "Other Liabilities"]),
        ("equity", "credit", ["Common Stock", "Additional Paid-In Capital", "Retained Earnings", "Treasury Stock", "Other Comprehensive Income", "Dividend Payable", "Preferred Stock", "Capital Reserve", "Contributed Surplus", "Equity Adjustment"]),
        ("revenue", "credit", ["Product Sales", "Subscription Revenue", "Service Revenue", "Licensing Revenue", "Maintenance Revenue", "Interest Income", "Foreign Exchange Gain", "Warranty Revenue", "Consulting Revenue", "Other Revenue"]),
        ("expense", "debit", ["Salaries and Wages", "Rent Expense", "Utilities Expense", "Marketing Expense", "Travel Expense", "Software Expense", "Insurance Expense", "Depreciation Expense", "Interest Expense", "Cost of Goods Sold"]),
    ]

    for category, normal_balance, names in category_specs:
        for index, name in enumerate(names, start=1):
            code = f"{category[:3].upper()}{index:03d}"
            catalog.append((code, name, category, "Operating", normal_balance))

    return catalog


async def seed_accounts(connection: asyncpg.Connection) -> list[dict[str, Any]]:
    account_catalog = build_account_catalog()
    rows = [
        {
            "account_code": code,
            "account_name": name,
            "category": category,
            "sub_category": sub_category,
            "normal_balance": normal_balance,
        }
        for code, name, category, sub_category, normal_balance in account_catalog
    ]
    await connection.executemany(
        """
        INSERT INTO chart_of_accounts (account_code, account_name, category, sub_category, normal_balance)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (account_code) DO NOTHING
        """,
        [(row["account_code"], row["account_name"], row["category"], row["sub_category"], row["normal_balance"]) for row in rows],
    )
    accounts = await connection.fetch("SELECT account_code, account_name, category, normal_balance FROM chart_of_accounts")
    return [dict(account) for account in accounts]


async def seed_periods(connection: asyncpg.Connection) -> None:
    periods = [
        ("Q1 2025", date(2025, 1, 1), date(2025, 3, 31), "closed"),
        ("Q2 2025", date(2025, 4, 1), date(2025, 6, 30), "open"),
    ]
    await connection.executemany(
        """
        INSERT INTO reporting_periods (period_name, start_date, end_date, status)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT DO NOTHING
        """,
        periods,
    )


def _pick(accounts: list[dict[str, Any]], category: str, exclude_name: str | None = None) -> dict[str, Any]:
    pool = [a for a in accounts if a["category"] == category and a.get("account_name") != exclude_name]
    return random.choice(pool)


async def seed_journal_entries(connection: asyncpg.Connection, accounts: list[dict[str, Any]]) -> None:
    # Retained Earnings is a derived figure (see balance_retained_earnings),
    # not randomly generated — every other account participates in ordinary
    # transaction activity below.
    postable_accounts = [a for a in accounts if a["account_name"] != "Retained Earnings"]
    cash_account = next(a for a in accounts if a["account_name"] == "Cash")
    ar_account = next(a for a in accounts if a["account_name"] == "Accounts Receivable")
    ap_account = next(a for a in accounts if a["account_name"] == "Accounts Payable")

    total_events = 25_000
    batch_size = 2_000
    start_date = date(2025, 1, 1)
    end_date = date(2025, 6, 30)

    def make_leg(entry_date: date, account_code: str, description: str, debit: float, credit: float) -> tuple[date, str, str, float, float, str, int]:
        period_id = 1 if entry_date <= date(2025, 3, 31) else 2
        return (entry_date, account_code, description, debit, credit, "ACME Corp", period_id)

    for batch_index in range(0, total_events, batch_size):
        rows: list[tuple[date, str, str, float, float, str, int]] = []
        for _ in range(min(batch_size, total_events - batch_index)):
            entry_date = fake.date_between_dates(start_date, end_date)
            description = fake.sentence(nb_words=6)
            amount = round(random.uniform(100.0, 15_000.0), 2)
            roll = random.random()

            # Each branch posts a real two-legged, self-balancing transaction
            # (same amount, opposite sides) so total debits == total credits
            # globally without needing any post-hoc correction — this is what
            # "assets balance with liabilities + equity" actually requires.
            if roll < 0.35:
                # Revenue: earn cash/receivable against a revenue account.
                revenue_account = _pick(postable_accounts, "revenue")
                cash_leg = cash_account if random.random() < 0.6 else ar_account
                rows.append(make_leg(entry_date, cash_leg["account_code"], description, amount, 0.0))
                rows.append(make_leg(entry_date, revenue_account["account_code"], description, 0.0, amount))
            elif roll < 0.70:
                # Expense: incur a cost, paid from cash or accrued as payable.
                expense_account = _pick(postable_accounts, "expense")
                cash_leg = cash_account if random.random() < 0.6 else ap_account
                rows.append(make_leg(entry_date, expense_account["account_code"], description, amount, 0.0))
                rows.append(make_leg(entry_date, cash_leg["account_code"], description, 0.0, amount))
            elif roll < 0.80:
                # Asset reallocation, e.g. cash into investments.
                asset_a = _pick(postable_accounts, "asset")
                asset_b = _pick(postable_accounts, "asset", exclude_name=asset_a["account_name"])
                rows.append(make_leg(entry_date, asset_a["account_code"], description, amount, 0.0))
                rows.append(make_leg(entry_date, asset_b["account_code"], description, 0.0, amount))
            elif roll < 0.90:
                # Financing: borrow (asset up, liability up) or repay (reverse).
                asset_account = _pick(postable_accounts, "asset")
                liability_account = _pick(postable_accounts, "liability")
                if random.random() < 0.5:
                    rows.append(make_leg(entry_date, asset_account["account_code"], description, amount, 0.0))
                    rows.append(make_leg(entry_date, liability_account["account_code"], description, 0.0, amount))
                else:
                    rows.append(make_leg(entry_date, liability_account["account_code"], description, amount, 0.0))
                    rows.append(make_leg(entry_date, asset_account["account_code"], description, 0.0, amount))
            else:
                # Equity: raise capital (cash up, equity up) or return capital.
                equity_account = _pick(postable_accounts, "equity")
                if random.random() < 0.8:
                    rows.append(make_leg(entry_date, cash_account["account_code"], description, amount, 0.0))
                    rows.append(make_leg(entry_date, equity_account["account_code"], description, 0.0, amount))
                else:
                    rows.append(make_leg(entry_date, equity_account["account_code"], description, amount, 0.0))
                    rows.append(make_leg(entry_date, cash_account["account_code"], description, 0.0, amount))

        await connection.executemany(
            """
            INSERT INTO journal_entries (entry_date, account_code, description, debit, credit, entity, period_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            rows,
        )


async def balance_retained_earnings(connection: asyncpg.Connection) -> None:
    """Set Retained Earnings to each period's net income, so the balance
    sheet identity (assets == liabilities + equity) holds exactly. This has
    to run after seed_journal_entries, since it's computed from that data
    rather than randomly generated."""
    re_account = await connection.fetchrow(
        "SELECT account_code FROM chart_of_accounts WHERE account_name = 'Retained Earnings'"
    )
    accounts = await connection.fetch("SELECT account_code, category, normal_balance FROM chart_of_accounts")
    account_meta = {row["account_code"]: row for row in accounts}

    for period_id, period_end in ((1, date(2025, 3, 31)), (2, date(2025, 6, 30))):
        entries = await connection.fetch(
            "SELECT account_code, debit, credit FROM journal_entries WHERE period_id = $1",
            period_id,
        )
        net_income = 0.0
        for entry in entries:
            meta = account_meta.get(entry["account_code"])
            if meta is None:
                continue
            if meta["category"] == "revenue":
                net_income += float(entry["credit"]) - float(entry["debit"])
            elif meta["category"] == "expense":
                net_income -= float(entry["debit"]) - float(entry["credit"])

        net_income = round(net_income, 2)
        debit = 0.0 if net_income >= 0 else abs(net_income)
        credit = net_income if net_income >= 0 else 0.0

        await connection.execute(
            """
            INSERT INTO journal_entries (entry_date, account_code, description, debit, credit, entity, period_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            period_end,
            re_account["account_code"],
            "Period-end retained earnings (net income for the period)",
            debit,
            credit,
            "ACME Corp",
            period_id,
        )


async def main() -> None:
    settings = get_settings()
    connection = await asyncpg.connect(settings.database_dsn)
    try:
        await connection.execute(
            "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pgcrypto;"
        )
        schema_sql = Path(__file__).resolve().parent / "init_db.sql"
        await connection.execute(schema_sql.read_text(encoding="utf-8"))
        await seed_periods(connection)
        accounts = await seed_accounts(connection)
        # Idempotent re-runs: journal_entries has no natural dedup key, so
        # clear it first rather than accumulating duplicate data on top of
        # whatever a previous run left behind.
        await connection.execute("TRUNCATE TABLE journal_entries RESTART IDENTITY")
        await seed_journal_entries(connection, accounts)
        await balance_retained_earnings(connection)
        print("Seed data generation completed successfully")
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
