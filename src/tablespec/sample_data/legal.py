"""Seeded fabricated legal values and explicit row/parent correlations.

Names are labeled synthetic. Codes are a small litigation UTBMS subset,
not a claim of full UTBMS coverage. No source records are consumed.
"""

from datetime import date, timedelta
import json
from pathlib import Path
import random
from typing import Any

from .config import GenerationConfig
from .generators import HealthcareDataGenerators
from .registry import KeyRegistry
from tablespec.schemas.generators import _resolve_nullable

LEVEL_RATES = {"partner": 650, "counsel": 500, "associate": 325, "paralegal": 150}
TASKS = {
    "L110": "Analyze facts",
    "L120": "Analyze case strategy",
    "L210": "Review pleadings",
    "L310": "Review written discovery",
    "L410": "Prepare fact witnesses",
    "L510": "Analyze appeal grounds",
    "P300": "Analyze transaction structure",
    "P200": "Review transaction diligence",
    "P400": "Draft transaction documents",
    "P600": "Prepare transaction closing",
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
# Generated consumer snapshot. UMF spec/domain-packs/legal/pack.json owns pack
# metadata and schemas; this module owns only executable fabricated generators.
LEGAL_PACK = json.loads(Path(__file__).with_name("legal_pack.json").read_text())
LEGAL_TYPES = LEGAL_PACK["domain_types"]


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
            prefix = self.rng.choice(
                (
                    "Velbrin",
                    "Orvessa",
                    "Nimvoro",
                    "Talzari",
                    "Embralo",
                    "Korvimi",
                    "Zanlora",
                    "Felvani",
                    "Ulzaro",
                    "Bravelo",
                    "Senvari",
                    "Quelmira",
                    "Wenvora",
                    "Yalbrin",
                    "Dravessa",
                    "Pelmoro",
                )
            )
            return f"Synthetic {prefix} {self.rng.choice(('Ventures', 'Industries', 'Holdings', 'Technologies', 'Trading', 'Logistics'))} {index + 1}"
        if kind == "timekeeper_name":
            return f"Synthetic {self.rng.choice(('Nelviro', 'Tazmela', 'Quorlen', 'Vesmari', 'Ulbrina', 'Javreno', 'Kelmora', 'Zenvilo'))} {self.rng.choice(('Drelvani', 'Morzenko', 'Valquerri', 'Senbralo', 'Ulvessan', 'Kirzelmo', 'Tavrenni', 'Quelzaro'))} {index + 1}"
        if kind in ("matter_number", "invoice_number"):
            return f"{'MAT' if kind == 'matter_number' else 'INV'}-{index + 1:08d}"
        if kind == "matter_title":
            return f"Fabricated commercial matter {index + 1}"
        if kind == "billing_rate":
            return LEVEL_RATES[ctx.get("timekeeper_level", "associate")]
        if kind == "billing_narrative":
            text = TASKS[ctx.get("utbms_task_code", "L110")]
            activity = {
                "A101": "planning",
                "A102": "research",
                "A103": "drafting",
                "A104": "review",
            }[ctx.get("utbms_activity_code", "A101")]
            detail = self.rng.choice(
                (
                    "contract schedule",
                    "witness summary",
                    "risk register",
                    "exhibit bundle",
                    "commercial terms",
                    "procedural timetable",
                )
            )
            if ctx.get("vague_entry"):
                return (
                    f"{text}: {activity}; attention to matter and miscellaneous work ({index + 1})"
                    + (
                        "; additional tasks (block billed)."
                        if ctx.get("block_billed")
                        else "."
                    )
                )
            text += f": {activity} of synthetic {detail}, section {self.rng.randint(1, 90)}, revision {self.rng.randint(1, 12)}"
            if ctx.get("block_billed"):
                text += f"; {self.rng.choice(tuple(TASKS.values()))}; confer on next steps (block billed)."
            return text + "."
        if kind == "court":
            return f"Synthetic trial court of {ctx.get('jurisdiction', 'New York')}"
        if kind == "document_title":
            return f"Fabricated {ctx.get('document_type', 'NDA')} {index + 1}"
        if kind == "document_body":
            return self.document_body(index, ctx)
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
        if "block_billed" in row:
            row["block_billed"] = self.rng.random() < 0.15
        if "vague_entry" in row:
            row["vague_entry"] = self.rng.random() < 0.03
        if "nda_issues" in row:
            row["nda_issues"] = ""
        context.update(row)
        # Prerequisites first; dependent fields last.
        ordered = sorted(
            columns,
            key=lambda c: c.get("domain_type")
            in (
                "billing_rate",
                "billing_narrative",
                "court",
                "document_title",
                "document_body",
            ),
        )
        for col in ordered:
            kind = col.get("domain_type")
            if isinstance(kind, str) and kind in LEGAL_TYPES:
                row[col["name"]] = self.value(kind, index, context)
                context[kind] = row[col["name"]]
                if kind == "document_body" and "nda_issues" in row:
                    row["nda_issues"] = context["nda_issues"]
        if "open_date" in row and "close_date" in row:
            reference = self.config.get_reference_date().date()
            duration = round(
                self.rng.triangular(
                    self.config.matter_duration_min_days,
                    self.config.matter_duration_max_days,
                    min(
                        self.config.matter_duration_max_days,
                        max(self.config.matter_duration_min_days, 180),
                    ),
                )
            )
            opened = reference - timedelta(
                days=self.rng.randint(30, self.config.matter_duration_max_days)
            )
            row["open_date"] = opened.isoformat()
            nullable = next(
                (c.get("nullable") for c in columns if c["name"] == "close_date"), False
            )
            row["close_date"] = (
                None
                if _resolve_nullable(nullable)
                and self.rng.random() < self.config.open_matter_fraction
                else (opened + timedelta(days=duration)).isoformat()
            )
        if "entry_date" in row:
            opened = date.fromisoformat(
                str(context.get("open_date", "2024-01-01"))[:10]
            )
            closed = date.fromisoformat(
                str(
                    context.get("close_date")
                    or self.config.get_reference_date().date().isoformat()
                )[:10]
            )
            if closed < opened:
                raise ValueError("Matter close_date precedes open_date")
            row["entry_date"] = (
                opened + timedelta(days=self.rng.randint(0, (closed - opened).days))
            ).isoformat()
        if "hours" in row:
            row["hours"] = self.rng.randint(1, 80) / 10
        if "amount" in row:
            row["amount"] = round(row["hours"] * row["billing_rate"], 2)
        return row

    def table_planner(self, dataset: Any) -> Any:
        """Provide the optional relational planner to the domain-neutral engine."""
        from .legal_tables import LegalTablePlanner

        return LegalTablePlanner(dataset)

    def document_body(self, index: int, context: dict[str, Any]) -> str:
        """Generate short typed clauses and optional seeded NDA issue labels."""
        kind = context.get("document_type", "NDA")
        party = f"Synthetic Velzari Holdings {index + 1}"
        region = self.rng.choice(
            ("Sample North", "Sample Coast", "Sample Vale", "Sample Ridge")
        )
        term = self.rng.randint(1, 5)
        variant = self.rng.choice(
            ("designated", "marked", "nonpublic", "specifically identified")
        )
        issue = (
            self.rng.choice(("long_term", "residuals", "missing_governing_law"))
            if kind == "NDA" and self.rng.random() < 0.08
            else ""
        )
        if "nda_issues" in context:
            context["nda_issues"] = issue
        if kind == "NDA":
            term = 25 if issue == "long_term" else term
            paragraphs = [
                f"{party} and Synthetic Quorvessa Trading shall protect {variant} confidential information for {term} years.",
                self.rng.choice(
                    (
                        "Disclosure is limited to advisers bound by equivalent duties.",
                        "Recipients shall return copies upon written request.",
                        "Independent development and public information are excluded.",
                    ),
                ),
            ]
            if issue == "residuals":
                paragraphs.append(
                    "Recipients may use residual information retained in unaided memory without restriction."
                )
            if issue != "missing_governing_law":
                paragraphs.append(
                    f"Fictional laws of {region} govern. Exclusive jurisdiction lies in the Synthetic Court of {region}."
                )
        elif kind == "Pleading":
            paragraphs = [
                f"{party} alleges failure to deliver {variant} goods under synthetic order {index + 1}.",
                self._template(
                    index,
                    (
                        f"The claimant seeks fabricated damages and costs. Jurisdiction is pleaded in the Synthetic Court of {region}.",
                        f"The respondent disputes causation and requests dismissal under the fictional rules of {region}.",
                        f"Relief requested includes a synthetic declaration of rights and reimbursement. Venue lies in fictional {region}.",
                    ),
                ),
            ]
        elif kind == "Memorandum":
            paragraphs = [
                f"Issue: whether {party}'s {variant} obligation survived termination after {term} years.",
                self._template(
                    index,
                    (
                        f"Analysis: the fictional {region} rule requires express survival language. Recommendation: clarify scope and record the commercial assumptions.",
                        f"Analysis: the fictional {region} exception turns on notice. Recommendation: preserve the synthetic correspondence and narrow the disputed obligation.",
                        f"Analysis: conflicting clauses create ambiguity under fictional {region} law. Recommendation: add an express precedence clause.",
                    ),
                ),
            ]
        else:
            paragraphs = [
                f"Synthetic advisers are engaged by {party} for {variant} commercial drafting services for {term} months.",
                self._template(
                    index,
                    (
                        f"Fees follow agreed rates; indemnity excludes intentional misconduct. Fictional {region} law governs disputes.",
                        f"Monthly fees require approval; liability is limited to synthetic fees paid. Disputes go to the Synthetic Court of {region}.",
                        f"The parties may terminate on thirty days notice; confidentiality survives. Fictional {region} law governs the limited indemnity.",
                    ),
                ),
            ]
        return "FABRICATED SAMPLE.\n\n" + "\n\n".join(paragraphs)

    @staticmethod
    def _template(index: int, templates: tuple[str, ...]) -> str:
        """Rotate fabricated clause templates without shifting other table RNGs."""
        return templates[index % len(templates)]

    def validate_correlations(
        self, row: dict[str, Any], parents: dict[str, Any]
    ) -> None:
        """Reject constraint adjustments that invalidate matter date relationships."""
        context = {**parents, **row}
        opened = context.get("open_date")
        closed = context.get("close_date")
        if opened and closed and closed < opened:
            raise ValueError("Matter close_date precedes open_date")
        entry = row.get("entry_date")
        if entry and ((opened and entry < opened) or (closed and entry > closed)):
            raise ValueError("Entry date outside matter open period")
        if "amount" in row:
            from decimal import Decimal

            if Decimal(str(row["amount"])) != Decimal(str(row["hours"])) * Decimal(
                str(row["billing_rate"])
            ):
                raise ValueError("Entry amount differs from hours times rate")
        if (
            "billing_rate" in row
            and "timekeeper_level" in context
            and row["billing_rate"] != LEVEL_RATES[context["timekeeper_level"]]
        ):
            raise ValueError("Billing rate differs from timekeeper level")


def _method(kind: str) -> Any:
    def generate(self: LegalDataGenerators) -> Any:
        self.sequence += 1
        return self.value(kind, self.sequence)

    return generate


for _kind in LEGAL_NAMES:
    setattr(LegalDataGenerators, f"generate_{_kind}", _method(_kind))
