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

sys.path.append(str(Path(__file__).resolve().parents[1] / "backend"))

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
    accounts = await connection.fetch("SELECT account_code, category, normal_balance FROM chart_of_accounts")
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


async def seed_journal_entries(connection: asyncpg.Connection, accounts: list[dict[str, Any]]) -> None:
    total_rows = 50_000
    batch_size = 2_000
    start_date = date(2025, 1, 1)
    end_date = date(2025, 6, 30)

    for batch_index in range(0, total_rows, batch_size):
        rows: list[tuple[date, str, str, float, float, str, int]] = []
        for _ in range(min(batch_size, total_rows - batch_index)):
            account = random.choice(accounts)
            category = account["category"]
            amount = round(random.uniform(100.0, 15_000.0), 2)
            if category == "revenue":
                debit = 0.0
                credit = amount
            elif category == "expense":
                debit = amount
                credit = 0.0
            elif category == "asset":
                if random.random() < 0.8:
                    debit = amount
                    credit = 0.0
                else:
                    debit = 0.0
                    credit = amount
            elif category == "liability":
                if random.random() < 0.8:
                    debit = 0.0
                    credit = amount
                else:
                    debit = amount
                    credit = 0.0
            else:
                if random.random() < 0.8:
                    debit = 0.0
                    credit = amount
                else:
                    debit = amount
                    credit = 0.0

            entry_date = fake.date_between_dates(start_date, end_date)
            period_id = 1 if entry_date <= date(2025, 3, 31) else 2
            description = fake.sentence(nb_words=6)
            rows.append((entry_date, account["account_code"], description, debit, credit, "ACME Corp", period_id))

        await connection.executemany(
            """
            INSERT INTO journal_entries (entry_date, account_code, description, debit, credit, entity, period_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            rows,
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
        await seed_journal_entries(connection, accounts)
        print("Seed data generation completed successfully")
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
