"""Cross-domain validation rules: exports, suppliers, cross-domain keys, glossary.

These rules need a view across many domain directories, which the per-table
and per-directory validators in :mod:`tablespec.validator` do not have. They
are pure functions over :class:`~tablespec.domains.LoadedDomain` objects so
they can be unit-tested without touching the filesystem.

Rules (``rule_id`` prefixes appear in every message):

* ``DOM-EXPORT``   -- every export names a table in the domain, and that
  table declares a primary key (an exported table is an aggregate root: the
  only thing another domain may hold a reference to).
* ``DOM-SUPPLIER`` -- every supplier is a discovered domain, and every
  ``consumes`` entry is in that supplier's exports.
* ``DOM-XREF``     -- a foreign key that targets another domain must target an
  exported table's primary-key column, and the supplier edge must be declared
  in the consumer's ``suppliers`` map.
* ``DOM-TERM``     -- a ``term`` on a table or column must exist in the owning
  domain's glossary when one is declared.
* ``DOM-DRIFT``    -- (warning) the same term is defined with different text in
  two domains. Two domains may legitimately mean different things by one word;
  the warning exists so the difference is a decision, not an accident.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tablespec.domains import LoadedDomain
from tablespec.models.umf import UMF


@dataclass
class DomainFinding:
    """One validation finding."""

    domain: str
    rule: str
    entity: str
    message: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.domain}/{self.entity}: {self.message}"


@dataclass
class DomainValidationReport:
    """Errors block; warnings inform."""

    errors: list[DomainFinding] = field(default_factory=list)
    warnings: list[DomainFinding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def by_domain(self) -> dict[str, list[DomainFinding]]:
        out: dict[str, list[DomainFinding]] = {}
        for f in [*self.errors, *self.warnings]:
            out.setdefault(f.domain, []).append(f)
        return out


def _pk_columns(umf: UMF) -> set[str]:
    return {c.lower() for c in (umf.primary_key or [])}


def validate_exports(domain: LoadedDomain) -> list[DomainFinding]:
    """DOM-EXPORT: exports name real tables that declare a primary key."""
    findings: list[DomainFinding] = []
    for export in domain.metadata.exports:
        umf = domain.table(export)
        if umf is None:
            findings.append(
                DomainFinding(
                    domain.name,
                    "DOM-EXPORT",
                    export,
                    "exported table is not a table in this domain",
                )
            )
            continue
        if not umf.primary_key:
            findings.append(
                DomainFinding(
                    domain.name,
                    "DOM-EXPORT",
                    umf.table_name,
                    "exported table must declare a primary_key "
                    "(other domains may only reference an aggregate root's identifier)",
                )
            )
    return findings


def validate_suppliers(
    domain: LoadedDomain, domains: dict[str, LoadedDomain]
) -> list[DomainFinding]:
    """DOM-SUPPLIER: suppliers exist and consumed tables are exported by them."""
    findings: list[DomainFinding] = []
    for supplier_name, rel in domain.metadata.suppliers.items():
        if supplier_name == domain.name:
            findings.append(
                DomainFinding(
                    domain.name,
                    "DOM-SUPPLIER",
                    supplier_name,
                    "a domain cannot list itself as a supplier",
                )
            )
            continue
        supplier = domains.get(supplier_name)
        if supplier is None:
            findings.append(
                DomainFinding(
                    domain.name,
                    "DOM-SUPPLIER",
                    supplier_name,
                    "supplier domain not found under the validation root",
                )
            )
            continue
        for table in rel.consumes:
            if not supplier.metadata.exports_table(table):
                findings.append(
                    DomainFinding(
                        domain.name,
                        "DOM-SUPPLIER",
                        f"{supplier_name}.{table}",
                        f"consumed table is not in domain '{supplier_name}' exports",
                    )
                )
    return findings


def validate_cross_domain_keys(
    domain: LoadedDomain, domains: dict[str, LoadedDomain]
) -> list[DomainFinding]:
    """DOM-XREF: cross-domain FKs target an exported table's primary key via a declared supplier."""
    findings: list[DomainFinding] = []
    for umf in domain.tables.values():
        if not umf.relationships or not umf.relationships.foreign_keys:
            continue
        for fk in umf.relationships.foreign_keys:
            target_domain = fk.target_domain
            if not target_domain or target_domain == domain.name:
                continue
            entity = f"{umf.table_name}.{fk.column}"
            target = f"{target_domain}.{fk.target_table}"
            supplier = domains.get(target_domain)
            if supplier is None:
                findings.append(
                    DomainFinding(
                        domain.name,
                        "DOM-XREF",
                        entity,
                        f"references {target} but domain '{target_domain}' was not found",
                    )
                )
                continue
            if target_domain not in domain.metadata.suppliers:
                findings.append(
                    DomainFinding(
                        domain.name,
                        "DOM-XREF",
                        entity,
                        f"references {target} but '{target_domain}' is not declared "
                        f"in this domain's suppliers",
                    )
                )
            if not supplier.metadata.exports_table(fk.target_table):
                findings.append(
                    DomainFinding(
                        domain.name,
                        "DOM-XREF",
                        entity,
                        f"references {target} which is not in '{target_domain}' exports",
                    )
                )
                continue
            target_umf = supplier.table(fk.target_table)
            if target_umf is None:
                findings.append(
                    DomainFinding(
                        domain.name,
                        "DOM-XREF",
                        entity,
                        f"references {target} but that table did not load in '{target_domain}'",
                    )
                )
                continue
            if fk.references_column.lower() not in _pk_columns(target_umf):
                findings.append(
                    DomainFinding(
                        domain.name,
                        "DOM-XREF",
                        entity,
                        f"references {target}.{fk.references_column}, which is not "
                        f"a primary-key column of the exported table "
                        f"(primary_key={target_umf.primary_key})",
                    )
                )
    return findings


def validate_terms(domain: LoadedDomain) -> list[DomainFinding]:
    """DOM-TERM: every declared term resolves in the domain glossary."""
    if domain.glossary is None:
        return []
    findings: list[DomainFinding] = []
    for umf in domain.tables.values():
        if umf.term and not domain.glossary.has(umf.term):
            findings.append(
                DomainFinding(
                    domain.name,
                    "DOM-TERM",
                    umf.table_name,
                    f"term '{umf.term}' is not in the domain glossary",
                )
            )
        for col in umf.columns:
            if col.term and not domain.glossary.has(col.term):
                findings.append(
                    DomainFinding(
                        domain.name,
                        "DOM-TERM",
                        f"{umf.table_name}.{col.name}",
                        f"term '{col.term}' is not in the domain glossary",
                    )
                )
    return findings


def detect_term_drift(domains: dict[str, LoadedDomain]) -> list[DomainFinding]:
    """DOM-DRIFT (warning): one term, different definitions across domains."""
    seen: dict[str, tuple[str, str]] = {}  # term -> (domain, definition)
    findings: list[DomainFinding] = []
    for name in sorted(domains):
        glossary = domains[name].glossary
        if glossary is None:
            continue
        for term, entry in glossary.terms.items():
            key = term.lower()
            prior = seen.get(key)
            if prior is None:
                seen[key] = (name, entry.definition.strip())
                continue
            prior_domain, prior_def = prior
            if prior_def != entry.definition.strip():
                findings.append(
                    DomainFinding(
                        name,
                        "DOM-DRIFT",
                        term,
                        f"defined differently in '{prior_domain}' "
                        f"({prior_def!r}) and '{name}' ({entry.definition.strip()!r})",
                    )
                )
    return findings


def validate_domains(domains: dict[str, LoadedDomain]) -> DomainValidationReport:
    """Run every rule over a set of loaded domains."""
    report = DomainValidationReport()
    for name in sorted(domains):
        domain = domains[name]
        for err in domain.load_errors:
            report.errors.append(DomainFinding(name, "DOM-LOAD", "-", err))
        report.errors.extend(validate_exports(domain))
        report.errors.extend(validate_suppliers(domain, domains))
        report.errors.extend(validate_cross_domain_keys(domain, domains))
        report.errors.extend(validate_terms(domain))
    report.warnings.extend(detect_term_drift(domains))
    return report


__all__ = [
    "DomainFinding",
    "DomainValidationReport",
    "detect_term_drift",
    "validate_cross_domain_keys",
    "validate_domains",
    "validate_exports",
    "validate_suppliers",
    "validate_terms",
]
