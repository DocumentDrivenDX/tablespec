"""Seeded fabricated legal values and explicit row/parent correlations.

Names are labeled synthetic. Codes are a small litigation UTBMS subset,
not a claim of full UTBMS coverage. No source records are consumed.
"""

from datetime import date, timedelta
import random
from typing import Any

from .config import GenerationConfig
from .generators import HealthcareDataGenerators
from .registry import KeyRegistry

LEVEL_RATES = {"partner": 650, "counsel": 500, "associate": 325, "paralegal": 150}
TASKS = {
    "L110": "Analyze facts",
    "L120": "Analyze case strategy",
    "L210": "Review pleadings",
    "L310": "Review written discovery",
}
CHOICES = {
    "practice_area": ("Litigation", "Corporate", "Employment", "Intellectual Property"),
    "timekeeper_level": tuple(LEVEL_RATES),
    "utbms_task_code": tuple(TASKS),
    "utbms_activity_code": ("A101", "A102", "A103", "A104"),
    "invoice_status": ("draft", "issued", "paid", "overdue", "void"),
    "jurisdiction": ("New York", "Illinois", "California"),
    "document_type": ("NDA", "Engagement letter", "Pleading", "Memorandum"),
}
LEGAL_NAMES = (
    "client_name",
    "matter_number",
    "matter_title",
    "practice_area",
    "timekeeper_name",
    "timekeeper_level",
    "billing_rate",
    "utbms_task_code",
    "utbms_activity_code",
    "billing_narrative",
    "invoice_number",
    "invoice_status",
    "court",
    "jurisdiction",
    "document_type",
    "document_title",
    "document_body",
)
LEGAL_TYPES = {
    name: {
        "description": f"Fabricated legal sample {name.replace('_', ' ')}",
        "sample_generation": {"method": f"generate_{name}"},
        "detection": {"column_name_patterns": [f"^{name}$"]},
    }
    for name in LEGAL_NAMES
}


class LegalDataGenerators(HealthcareDataGenerators):
    """Legal pack using the existing generic generator API for compatibility."""

    def __init__(
        self, config: GenerationConfig, key_registry: KeyRegistry | None = None
    ) -> None:
        super().__init__(config, key_registry)
        self.rng = random.Random(config.random_seed)
        self.sequence = 0

    def value(
        self, kind: str, index: int = 0, context: dict[str, Any] | None = None
    ) -> Any:
        """Generate a domain value with correlated row and referenced-parent context."""
        ctx = context or {}
        if kind in CHOICES:
            return self.rng.choice(CHOICES[kind])
        if kind == "client_name":
            return f"Synthetic {self.rng.choice(('Amber', 'Cobalt', 'Willow'))} Ventures {index + 1}"
        if kind == "timekeeper_name":
            return f"Synthetic Fee Earner {index + 1}"
        if kind in ("matter_number", "invoice_number"):
            return f"{'MAT' if kind == 'matter_number' else 'INV'}-{index + 1:08d}"
        if kind == "matter_title":
            return f"Fabricated commercial matter {index + 1}"
        if kind == "billing_rate":
            return LEVEL_RATES[ctx.get("timekeeper_level", "associate")]
        if kind == "billing_narrative":
            text = TASKS[ctx.get("utbms_task_code", "L110")]
            return text + (
                "; draft memorandum; confer with team (block billed)."
                if ctx.get("block_billed")
                else " for fabricated matter (single task)."
            )
        if kind == "court":
            return f"Synthetic trial court of {ctx.get('jurisdiction', 'New York')}"
        if kind == "document_title":
            return f"Fabricated {ctx.get('document_type', 'NDA')} {index + 1}"
        if kind == "document_body":
            return "FABRICATED SAMPLE. The parties shall keep designated information confidential for two years. This agreement is governed by the fictional laws of Sample Territory."
        raise ValueError(f"Unknown legal domain type: {kind}")

    def correlate(
        self,
        row: dict[str, Any],
        columns: list[dict[str, Any]],
        parents: dict[str, Any] | None = None,
        index: int = 0,
    ) -> dict[str, Any]:
        """Apply correlations independently of UMF column ordering."""
        context = {**(parents or {}), **row}
        # Prerequisites first; dependent fields last.
        ordered = sorted(
            columns,
            key=lambda c: c.get("domain_type")
            in ("billing_rate", "billing_narrative", "court", "document_title"),
        )
        for col in ordered:
            kind = col.get("domain_type")
            if kind in LEGAL_TYPES:
                row[col["name"]] = self.value(kind, index, context)
                context[kind] = row[col["name"]]
        if "open_date" in row and "close_date" in row:
            row["close_date"] = max(row["open_date"], row["close_date"])
        if "entry_date" in row:
            opened = date.fromisoformat(
                str(context.get("open_date", "2024-01-01"))[:10]
            )
            closed = date.fromisoformat(
                str(context.get("close_date") or "2025-01-15")[:10]
            )
            if closed < opened:
                raise ValueError("Matter close_date precedes open_date")
            row["entry_date"] = (
                opened + timedelta(days=self.rng.randint(0, (closed - opened).days))
            ).isoformat()
        return row


def _method(kind: str) -> Any:
    def generate(self: LegalDataGenerators) -> Any:
        self.sequence += 1
        return self.value(kind, self.sequence)

    return generate


for _kind in LEGAL_NAMES:
    setattr(LegalDataGenerators, f"generate_{_kind}", _method(_kind))
