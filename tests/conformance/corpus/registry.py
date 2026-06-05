"""Declarative conformance-corpus registry.

Loads ``tests/conformance/corpus/cases.yaml`` into typed ``Case`` records and
resolves every referenced path against the repo root. This is the single source
of truth for the cross-engine conformance harness: each engine leg iterates the
same cases, canonicalizes at the case's pinned ``ts_precision``, and compares to
the same committed golden (the SparkDirect oracle output).

The registry deliberately keeps the corpus declarative + engine-agnostic: it
knows nothing about Spark / DuckDB / dbt. Engine-specific runners (the parity
tests) import ``load_cases`` / ``ingest_cases`` / ``gold_cases`` and drive them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

# repo root = tests/conformance/corpus/registry.py -> up 3.
REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = Path(__file__).resolve().parent / "cases.yaml"


@dataclass(frozen=True)
class Case:
    """One conformance corpus case.

    Attributes:
        id: stable case id (used as the pytest parametrization id).
        kind: ``"ingest"`` or ``"gold"``.
        tags: tag taxonomy labels (see cases.yaml header).
        ts_precision: fractional-second digits the golden is rendered at; every
            engine leg MUST canonicalize this case at exactly this precision.
        umf: resolved path to the UMF spec (ingest cases) or ``None``.
        batches: resolved ordered raw CSV batch paths (ingest cases).
        golden: resolved committed golden path (the SparkDirect oracle output).
        gold_dir: resolved directory holding the gold case's UMFs/CSVs (gold cases).
        generator: the ``generate_sql_plan`` path / mechanism a gold case exercises.
        pending: True when the case is declared but its golden is not yet produced
            (the executed-gold phase materializes it). The corpus-validation test
            still requires a pending case's source fixtures to be present.
        divergence: when set, a human-readable reason the case is a KNOWN
            cross-engine divergence that cannot currently be executed to a
            byte-stable golden (a genuine generator/corpus issue surfaced by the
            harness). The matrix gates such a case with this reason so it is
            SKIPPED VISIBLY -- never silently passed -- pending a generator/corpus
            fix. Distinct from ``pending`` (which is merely "golden not yet
            written"): a divergence case fails to EXECUTE, not just to compare.
    """

    id: str
    kind: str
    tags: tuple[str, ...]
    ts_precision: int
    umf: Path | None = None
    batches: tuple[Path, ...] = ()
    golden: Path | None = None
    gold_dir: Path | None = None
    generator: str | None = None
    pending: bool = False
    divergence: str | None = None

    def has_tag(self, tag: str) -> bool:
        return tag in self.tags

    @property
    def is_multibatch(self) -> bool:
        return len(self.batches) > 1


@dataclass(frozen=True)
class Corpus:
    cases: tuple[Case, ...] = field(default_factory=tuple)

    def by_id(self, case_id: str) -> Case:
        for c in self.cases:
            if c.id == case_id:
                return c
        raise KeyError(f"no conformance case with id {case_id!r}")

    def with_tag(self, tag: str) -> tuple[Case, ...]:
        return tuple(c for c in self.cases if c.has_tag(tag))

    def with_kind(self, kind: str) -> tuple[Case, ...]:
        return tuple(c for c in self.cases if c.kind == kind)


def _resolve(rel: str) -> Path:
    p = (REPO_ROOT / rel).resolve()
    return p


@lru_cache(maxsize=1)
def load_corpus() -> Corpus:
    """Parse the manifest into a frozen ``Corpus`` (cached)."""
    data = yaml.safe_load(MANIFEST.read_text())
    default_precision = int(data.get("defaults", {}).get("ts_precision", 6))
    cases: list[Case] = []
    seen: set[str] = set()
    for raw in data["cases"]:
        cid = raw["id"]
        if cid in seen:
            raise ValueError(f"duplicate conformance case id: {cid!r}")
        seen.add(cid)
        kind = raw["kind"]
        ts_precision = int(raw.get("ts_precision", default_precision))
        tags = tuple(raw.get("tags", []))
        if kind == "ingest":
            cases.append(
                Case(
                    id=cid,
                    kind=kind,
                    tags=tags,
                    ts_precision=ts_precision,
                    umf=_resolve(raw["umf"]),
                    batches=tuple(_resolve(b) for b in raw["batches"]),
                    golden=_resolve(raw["golden"]),
                    generator=raw.get("generator"),
                )
            )
        elif kind == "gold":
            cases.append(
                Case(
                    id=cid,
                    kind=kind,
                    tags=tags,
                    ts_precision=ts_precision,
                    gold_dir=_resolve(raw["dir"]),
                    generator=raw.get("generator"),
                    golden=(_resolve(raw["golden"]) if raw.get("golden") else None),
                    pending=bool(raw.get("pending", False)),
                    divergence=raw.get("divergence"),
                )
            )
        else:  # pragma: no cover - manifest guard
            raise ValueError(f"unknown case kind {kind!r} for {cid!r}")
    return Corpus(cases=tuple(cases))


def load_cases() -> tuple[Case, ...]:
    return load_corpus().cases


def ingest_cases() -> tuple[Case, ...]:
    return load_corpus().with_kind("ingest")


def gold_cases() -> tuple[Case, ...]:
    return load_corpus().with_kind("gold")
