"""Domain metadata models: the bounded-context unit for a set of UMF tables.

A *domain* is a directory of UMF tables that share an owner, a glossary, and an
explicit list of tables other domains may reference (``exports``). The domain
is the DDD bounded context; ``domain_type`` on a column is a value-object type
scoped to that domain's vocabulary.

``domain.yaml`` sits at the domain directory root and is the single place a
domain declares:

* identity (``name`` must match the directory name -- the same rule
  ``pipeline.yaml`` already enforces, so the qualifier in ``domain.table``
  references, the guidebook group, and the directory are one name);
* ``exports`` -- the published language: the only tables another domain's
  foreign keys may target;
* ``suppliers`` -- the context map: which other domains this one consumes
  from, with the DDD integration pattern that governs each edge;
* ``glossary`` -- the ubiquitous language file that ``term`` fields on tables
  and columns resolve against.

This module holds only the Pydantic models plus their file loaders. Discovery
across a root of many domains lives in :mod:`tablespec.domains`; validation
rules live in :mod:`tablespec.domain_validator`. Keeping the models here (under
``tablespec.models``) lets ``tablespec.core`` and the LDP/dbt emitters import
them without violating the core-seam encapsulation tests.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
import yaml

DOMAIN_FILENAME = "domain.yaml"

DomainName = Annotated[
    str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)
]
"""Directory-safe, qualifier-safe name: what precedes the dot in ``domain.table``."""

SemVer = Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]
"""Version of a domain's published language: strict ``MAJOR.MINOR.PATCH`` core,
no pre-release or build suffix. Compared numerically per segment."""

_RANGE_CLAUSE = re.compile(r"^(>=|<=|==|!=|>|<)\s*(\d+\.\d+\.\d+)$")


def parse_semver(version: str) -> tuple[int, int, int]:
    """Parse ``MAJOR.MINOR.PATCH`` into a comparable tuple."""
    parts = version.strip().split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        msg = f"not a MAJOR.MINOR.PATCH version: {version!r}"
        raise ValueError(msg)
    return int(parts[0]), int(parts[1]), int(parts[2])


def validate_version_range(constraint: str) -> str:
    """Validate a comma-separated range such as ``>=1.0.0,<2.0.0``.

    Grammar: one or more clauses separated by commas, each an operator from
    ``>=``, ``<=``, ``==``, ``!=``, ``>``, ``<`` followed by a
    ``MAJOR.MINOR.PATCH`` version. This is deliberately not PEP 440 and not a
    full SemVer range language; it is the smallest grammar that expresses a
    pin and a ceiling.
    """
    clauses = [c.strip() for c in constraint.split(",") if c.strip()]
    if not clauses:
        msg = "version range must contain at least one clause"
        raise ValueError(msg)
    for clause in clauses:
        if not _RANGE_CLAUSE.match(clause):
            msg = f"invalid version range clause: {clause!r} (expected e.g. '>=1.0.0,<2.0.0')"
            raise ValueError(msg)
    return ",".join(clauses)


def version_satisfies(version: str, constraint: str) -> bool:
    """True when ``version`` satisfies every clause of ``constraint``."""
    have = parse_semver(version)
    ops = {
        ">=": lambda a, b: a >= b,
        "<=": lambda a, b: a <= b,
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
        ">": lambda a, b: a > b,
        "<": lambda a, b: a < b,
    }
    for clause in validate_version_range(constraint).split(","):
        match = _RANGE_CLAUSE.match(clause)
        assert match is not None  # validated above
        op, want = match.groups()
        if not ops[op](have, parse_semver(want)):
            return False
    return True


def is_major_bump(old: str, new: str) -> bool:
    """True when ``new`` raises the MAJOR segment above ``old``."""
    return parse_semver(new)[0] > parse_semver(old)[0]


class IntegrationPattern(str, Enum):
    """DDD context-map integration pattern on a supplier -> consumer edge.

    The direction is always supplier (the domain whose exports are consumed) to
    consumer (the domain declaring the edge). Only the consumer declares it.
    """

    PARTNERSHIP = "partnership"
    SHARED_KERNEL = "shared_kernel"
    CUSTOMER_SUPPLIER = "customer_supplier"
    CONFORMIST = "conformist"
    ANTI_CORRUPTION = "anti_corruption"
    OPEN_HOST = "open_host"
    SEPARATE_WAYS = "separate_ways"


class GlossaryTerm(BaseModel):
    """One entry in a domain glossary."""

    model_config = ConfigDict(extra="forbid")

    definition: str = Field(description="What the term means inside this domain")
    aliases: list[str] | None = Field(
        default=None,
        description="Other names this term goes by in source systems or prose",
    )


class Glossary(BaseModel):
    """A domain's ubiquitous language: term -> definition."""

    model_config = ConfigDict(extra="forbid")

    terms: dict[str, GlossaryTerm] = Field(
        default_factory=dict, description="Terms keyed by their canonical spelling"
    )

    def has(self, term: str) -> bool:
        """True when ``term`` matches a key or an alias (case-insensitive)."""
        needle = term.strip().lower()
        for key, entry in self.terms.items():
            if key.lower() == needle:
                return True
            if entry.aliases and needle in (a.lower() for a in entry.aliases):
                return True
        return False

    def definition_of(self, term: str) -> str | None:
        """Return the definition for ``term`` (key or alias), else ``None``."""
        needle = term.strip().lower()
        for key, entry in self.terms.items():
            if key.lower() == needle or (
                entry.aliases and needle in (a.lower() for a in entry.aliases)
            ):
                return entry.definition
        return None


class SupplierRelationship(BaseModel):
    """A context-map edge from a supplier domain into the declaring domain."""

    model_config = ConfigDict(extra="forbid")

    pattern: IntegrationPattern = Field(
        description="DDD integration pattern governing this supplier edge. "
        "Advisory: it is the consumer's assertion and is rendered, not enforced, "
        "except that separate_ways may not consume anything."
    )
    consumes: list[str] = Field(
        default_factory=list,
        description="Supplier tables this domain references; each must be in the supplier's exports",
    )
    version: str | None = Field(
        default=None,
        description="Accepted range of the supplier's published-language version, "
        "e.g. '>=1.0.0,<2.0.0'. Checked against the supplier's domain.yaml version.",
    )

    @field_validator("version")
    @classmethod
    def _check_range(cls, v: str | None) -> str | None:
        return validate_version_range(v) if v else v


class DomainMetadata(BaseModel):
    """Contents of a ``domain.yaml`` file."""

    model_config = ConfigDict(extra="forbid")

    name: DomainName = Field(description="Domain name; must match the directory name")
    description: str | None = Field(
        default=None, description="What this domain is about"
    )
    owner: str | None = Field(
        default=None,
        description="Team or person accountable for this domain's tables",
    )
    version: SemVer | None = Field(
        default=None,
        description="Version of the domain's published language (MAJOR.MINOR.PATCH). "
        "A breaking change to an exported table requires a MAJOR bump.",
    )
    exports: list[str] = Field(
        default_factory=list,
        description="Tables other domains may reference (the published language). "
        "Each exported table must declare a primary key.",
    )
    glossary: str | None = Field(
        default=None,
        description="Path to the glossary YAML, relative to the domain directory",
    )
    suppliers: dict[DomainName, SupplierRelationship] = Field(
        default_factory=dict,
        description="Domains this one consumes from, keyed by supplier domain name",
    )

    def exports_table(self, table_name: str) -> bool:
        """True when ``table_name`` is in ``exports`` (case-insensitive)."""
        needle = table_name.lower()
        return any(t.lower() == needle for t in self.exports)


class DomainLoadError(ValueError):
    """Raised when a ``domain.yaml`` or glossary cannot be loaded."""


def load_domain(domain_dir: Path) -> DomainMetadata:
    """Load ``<domain_dir>/domain.yaml`` and enforce name == directory name."""
    domain_dir = Path(domain_dir)
    path = domain_dir / DOMAIN_FILENAME
    if not path.is_file():
        msg = f"No {DOMAIN_FILENAME} in {domain_dir}"
        raise DomainLoadError(msg)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        msg = f"{path}: top level must be a mapping"
        raise DomainLoadError(msg)
    try:
        meta = DomainMetadata(**data)
    except ValueError as exc:  # pydantic ValidationError is a ValueError
        msg = f"{path}: {exc}"
        raise DomainLoadError(msg) from exc
    if meta.name != domain_dir.name:
        msg = (
            f"{path}: domain name '{meta.name}' must match its directory "
            f"'{domain_dir.name}' (the name is the qualifier in domain.table references)"
        )
        raise DomainLoadError(msg)
    return meta


def load_glossary(domain_dir: Path, meta: DomainMetadata) -> Glossary | None:
    """Load the glossary named by ``meta.glossary``; ``None`` when not declared."""
    if not meta.glossary:
        return None
    path = Path(domain_dir) / meta.glossary
    if not path.is_file():
        msg = f"Glossary not found: {path}"
        raise DomainLoadError(msg)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        msg = f"{path}: top level must be a mapping"
        raise DomainLoadError(msg)
    # Accept either {terms: {...}} or a bare {term: {definition: ...}} mapping.
    payload = data if "terms" in data else {"terms": data}
    try:
        return Glossary(**payload)
    except ValueError as exc:
        msg = f"{path}: {exc}"
        raise DomainLoadError(msg) from exc


__all__ = [
    "DOMAIN_FILENAME",
    "DomainLoadError",
    "DomainMetadata",
    "DomainName",
    "Glossary",
    "GlossaryTerm",
    "IntegrationPattern",
    "SemVer",
    "SupplierRelationship",
    "is_major_bump",
    "load_domain",
    "load_glossary",
    "parse_semver",
    "validate_version_range",
    "version_satisfies",
]
