from __future__ import annotations

import asyncio
import sys
from pathlib import Path

script_path = Path(__file__).resolve()
backend_dir = script_path.parent.parent / "backend"
if not (backend_dir / "core").exists():
    backend_dir = script_path.parent.parent
sys.path.append(str(backend_dir))

from services.embedding_service import EmbeddingService  # noqa: E402


GAAP_RULES = [
    {
        "rule_id": "GAAP-001",
        "source": "GAAP",
        "text": "Revenue should be recognized when control of goods or services transfers to the customer, and when the amount can be measured reliably and collection is probable.",
    },
    {
        "rule_id": "GAAP-002",
        "source": "GAAP",
        "text": "Contract liabilities and contract assets should be recognized when performance obligations are satisfied or when consideration is received before revenue recognition criteria are met.",
    },
    {
        "rule_id": "GAAP-003",
        "source": "GAAP",
        "text": "Expenses should be recognized in the period in which they help generate the related revenue, consistent with the matching principle.",
    },
    {
        "rule_id": "GAAP-004",
        "source": "GAAP",
        "text": "Period costs that do not directly relate to current revenue should be expensed in the period incurred unless they create future economic benefit that is capitalized.",
    },
    {
        "rule_id": "GAAP-005",
        "source": "GAAP",
        "text": "Assets, liabilities, and equity should be presented in a manner that faithfully represents the company's financial position and supports reliable classification.",
    },
    {
        "rule_id": "GAAP-006",
        "source": "GAAP",
        "text": "Current and non-current assets and liabilities should be separated in the balance sheet to provide useful information about liquidity and solvency.",
    },
    {
        "rule_id": "GAAP-007",
        "source": "GAAP",
        "text": "Financial statements should be prepared on the assumption that the entity will continue as a going concern unless management has significant doubts about that ability.",
    },
    {
        "rule_id": "GAAP-008",
        "source": "GAAP",
        "text": "Materiality requires that omissions or misstatements be considered if they could influence the decisions of users of the financial statements.",
    },
    {
        "rule_id": "GAAP-009",
        "source": "GAAP",
        "text": "Depreciation should allocate the cost of a tangible asset over its useful life in a systematic and rational manner.",
    },
    {
        "rule_id": "GAAP-010",
        "source": "GAAP",
        "text": "The useful life, salvage value, and depreciation method should be reviewed periodically and revised when warranted by changes in circumstances.",
    },
    {
        "rule_id": "GAAP-011",
        "source": "GAAP",
        "text": "Inventory should be measured at the lower of cost and net realizable value unless another measurement basis is required by applicable accounting guidance.",
    },
    {
        "rule_id": "GAAP-012",
        "source": "GAAP",
        "text": "Inventory costing methods should be applied consistently and disclosed appropriately when they materially affect reported results.",
    },
    {
        "rule_id": "GAAP-013",
        "source": "GAAP",
        "text": "Consolidation requires the reporting entity to present the financial position and results of subsidiaries as part of the parent reporting entity when control exists.",
    },
    {
        "rule_id": "GAAP-014",
        "source": "GAAP",
        "text": "Intercompany balances and transactions should be eliminated in consolidated financial statements to avoid double counting.",
    },
    {
        "rule_id": "GAAP-015",
        "source": "GAAP",
        "text": "Receivables should be assessed for collectibility and appropriate allowance estimates should be recorded when expected credit losses are likely.",
    },
    {
        "rule_id": "GAAP-016",
        "source": "GAAP",
        "text": "Liabilities should be recognized when an obligation exists, regardless of whether the payment will be made in cash or another form.",
    },
    {
        "rule_id": "GAAP-017",
        "source": "GAAP",
        "text": "Equity transactions should be distinguished from income statement transactions so that realized and unrealized changes are not misclassified.",
    },
    {
        "rule_id": "GAAP-018",
        "source": "GAAP",
        "text": "Accrual accounting requires the recognition of revenues and expenses when earned or incurred rather than only when cash changes hands.",
    },
    {
        "rule_id": "GAAP-019",
        "source": "GAAP",
        "text": "Estimates and judgments should be based on the best available information and updated when new evidence becomes available.",
    },
    {
        "rule_id": "GAAP-020",
        "source": "GAAP",
        "text": "Disclosure should be sufficient to enable users of the financial statements to understand significant accounting policies, judgments, and estimates.",
    },
    {
        "rule_id": "GAAP-021",
        "source": "GAAP",
        "text": "Revenue from subscriptions, licenses, and service contracts should be allocated to performance obligations when those obligations are distinct.",
    },
    {
        "rule_id": "GAAP-022",
        "source": "GAAP",
        "text": "The carrying amount of long-lived assets should be reviewed for impairment whenever events or changes in circumstances indicate the carrying amount may not be recoverable.",
    },
    {
        "rule_id": "GAAP-023",
        "source": "GAAP",
        "text": "Fair value measurements should be used when required by accounting standards and should be supported by observable inputs when available.",
    },
    {
        "rule_id": "GAAP-024",
        "source": "GAAP",
        "text": "Leases should be classified and measured based on whether the lessee obtains substantially all of the economic benefits and control of the underlying asset.",
    },
    {
        "rule_id": "GAAP-025",
        "source": "GAAP",
        "text": "Contingent liabilities should be recognized when it is probable that a loss has occurred and the amount can be reasonably estimated.",
    },
    {
        "rule_id": "GAAP-026",
        "source": "GAAP",
        "text": "Cash and cash equivalents should be presented separately from restricted cash and other non-cash balances to improve liquidity analysis.",
    },
    {
        "rule_id": "GAAP-027",
        "source": "GAAP",
        "text": "Compensation expense for employee services should be recognized as the services are rendered and matched to the periods benefited.",
    },
    {
        "rule_id": "GAAP-028",
        "source": "GAAP",
        "text": "Share-based compensation should be measured at fair value at grant date and recognized over the requisite service period.",
    },
    {
        "rule_id": "GAAP-029",
        "source": "GAAP",
        "text": "Non-current assets should be presented at carrying amount less accumulated depreciation, amortization, or impairment losses where appropriate.",
    },
    {
        "rule_id": "GAAP-030",
        "source": "GAAP",
        "text": "Accounting policies should be applied consistently across periods unless a change is required by a new accounting standard or better reflects the underlying economics.",
    },
]


async def main() -> None:
    service = EmbeddingService()
    try:
        count = await service.embed_regulations(GAAP_RULES)
    except RuntimeError as exc:
        print(f"Embedding failed: {exc}")
        print("Check your OpenAI API key, billing status, and quota before retrying.")
        raise SystemExit(1) from exc
    print(f"Embedded {count} GAAP rules into Qdrant collection gaap_rules")


if __name__ == "__main__":
    asyncio.run(main())
