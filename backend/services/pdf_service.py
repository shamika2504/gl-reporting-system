from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from html import escape
from io import BytesIO
from typing import Any

from weasyprint import HTML


class PDFService:
    """Service for rendering report payloads into PDF bytes with WeasyPrint."""

    def __init__(self) -> None:
        self.name = "pdf-service"

    def _build_html(
        self,
        period_name: str,
        balance_sheet: dict[str, Any],
        income_statement: dict[str, Any],
        ratios: dict[str, Any],
        anomalies: list[dict[str, Any]],
        executive_summary: str,
        mda_commentary: dict[str, Any],
        anomaly_explanations: list[dict[str, Any]],
        audit_entries: list[dict[str, Any]],
    ) -> str:
        def render_table(rows: list[tuple[str, str]]) -> str:
            body = "".join(f"<tr><th>{escape(label)}</th><td>{escape(value)}</td></tr>" for label, value in rows)
            return f"<table><tbody>{body}</tbody></table>"

        def render_list(items: list[dict[str, Any]]) -> str:
            if not items:
                return "<p>No items.</p>"
            rows = "".join(
                f"<tr><td>{escape(str(item.get('account', item.get('event', ''))))}</td><td>{escape(str(item.get('type', item.get('model', ''))))}</td><td>{escape(str(item.get('detail', item.get('timestamp', ''))))}</td></tr>"
                for item in items
            )
            return f"<table><thead><tr><th>Item</th><th>Type</th><th>Detail</th></tr></thead><tbody>{rows}</tbody></table>"

        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        balance_rows = [
            ("Total Assets", str(balance_sheet.get("assets", {}).get("total_assets", ""))),
            ("Total Liabilities", str(balance_sheet.get("liabilities", {}).get("total_liabilities", ""))),
            ("Total Equity", str(balance_sheet.get("equity", {}).get("total_equity", ""))),
            ("Balanced", "Yes" if balance_sheet.get("balanced") else "No"),
        ]
        income_rows = [
            ("Total Revenue", str(income_statement.get("total_revenue", ""))),
            ("Total Expenses", str(income_statement.get("total_expenses", ""))),
            ("Net Income", str(income_statement.get("net_income", ""))),
            ("Net Margin %", str(income_statement.get("net_margin_pct", ""))),
        ]
        ratio_rows = [(name, str(value)) for name, value in ratios.items()]

        return f"""
        <html>
          <head>
            <style>
              body {{ font-family: Arial, sans-serif; color: #1f2937; margin: 24px; }}
              h1 {{ color: #0f172a; font-size: 24px; margin-bottom: 8px; }}
              h2 {{ color: #2563eb; font-size: 18px; margin-bottom: 8px; }}
              .page {{ page-break-after: always; margin-bottom: 24px; }}
              table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
              th, td {{ border: 1px solid #cbd5e1; padding: 8px; text-align: left; }}
              th {{ background: #f8fafc; }}
              .muted {{ color: #64748b; }}
            </style>
          </head>
          <body>
            <div class='page'>
              <h1>ACME Corp</h1>
              <h2>Financial Statement Report</h2>
              <p><strong>Period:</strong> {escape(period_name)}</p>
              <p><strong>Generated:</strong> {escape(generated_at)}</p>
              <p class='muted'>AI-Generated — For Review Purposes</p>
            </div>
            <div class='page'>
              <h1>Executive Summary</h1>
              <p>{escape(executive_summary)}</p>
            </div>
            <div class='page'>
              <h1>Balance Sheet</h1>
              {render_table(balance_rows)}
            </div>
            <div class='page'>
              <h1>Income Statement</h1>
              {render_table(income_rows)}
              <h2>Key Ratios</h2>
              {render_table(ratio_rows)}
            </div>
            <div class='page'>
              <h1>MD&A Commentary</h1>
              <pre>{escape(json.dumps(mda_commentary, default=str, indent=2))}</pre>
            </div>
            <div class='page'>
              <h1>Anomaly Flags</h1>
              {render_list(anomalies)}
              <h2>Explanations</h2>
              {render_list(anomaly_explanations)}
            </div>
            <div class='page'>
              <h1>Audit Trail Appendix</h1>
              {render_list(audit_entries)}
            </div>
          </body>
        </html>
        """

    def _render_pdf_sync(self, html_content: str) -> bytes:
        buffer = BytesIO()
        HTML(string=html_content).write_pdf(buffer)
        return buffer.getvalue()

    async def generate_report_pdf(
        self,
        period_name: str,
        balance_sheet: dict[str, Any],
        income_statement: dict[str, Any],
        ratios: dict[str, Any],
        anomalies: list[dict[str, Any]],
        executive_summary: str,
        mda_commentary: dict[str, Any],
        anomaly_explanations: list[dict[str, Any]],
        audit_entries: list[dict[str, Any]],
    ) -> bytes:
        html_content = self._build_html(
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
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._render_pdf_sync, html_content)
