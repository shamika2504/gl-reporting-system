from __future__ import annotations

import asyncio
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
        def render_section(title: str, body: str) -> str:
            return f"<div class='page'><h1>{escape(title)}</h1><div class='content'>{body}</div></div>"

        sections = [
            render_section("Cover", f"<h2>GL Regulatory Reporting</h2><p>Period: {escape(period_name)}</p>"),
            render_section("Executive Summary", f"<p>{escape(executive_summary)}</p>"),
            render_section("Balance Sheet", f"<pre>{escape(str(balance_sheet))}</pre>"),
            render_section("Income Statement", f"<pre>{escape(str(income_statement))}</pre>"),
            render_section("Ratios", f"<pre>{escape(str(ratios))}</pre>"),
            render_section("MD&A", f"<pre>{escape(str(mda_commentary))}</pre>"),
            render_section("Anomaly Flags", f"<pre>{escape(str(anomalies))}</pre>"),
            render_section("Audit Trail", f"<pre>{escape(str(audit_entries))}</pre>"),
        ]
        if anomaly_explanations:
            sections.append(render_section("Anomaly Explanations", f"<pre>{escape(str(anomaly_explanations))}</pre>"))

        return f"""
        <html>
          <head>
            <style>
              body {{ font-family: Arial, sans-serif; color: #1f2937; margin: 24px; }}
              h1 {{ color: #0f172a; font-size: 24px; margin-bottom: 8px; }}
              h2 {{ color: #2563eb; font-size: 18px; margin-bottom: 8px; }}
              .page {{ page-break-after: always; margin-bottom: 24px; }}
              .content {{ white-space: pre-wrap; line-height: 1.5; }}
              pre {{ background: #f8fafc; padding: 12px; border-radius: 6px; overflow: hidden; }}
            </style>
          </head>
          <body>
            <div class='cover'>
              <h1>GL Regulatory Reporting</h1>
              <p><strong>Period:</strong> {escape(period_name)}</p>
            </div>
            {''.join(sections)}
          </body>
        </html>
        """

    def _render_pdf_sync(self, html_content: str) -> bytes:
        return HTML(string=html_content).write_pdf()

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
