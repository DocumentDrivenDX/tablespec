"""Cross-domain validation rules: exports, suppliers, cross-domain keys, glossary.

These rules need a view across many domain directories, which the per-table
and per-directory validators in :mod:`tablespec.validator` do not have. They
are pure functions over :class:`~tablespec.domains.LoadedDomain` objects so
they can be unit-tested without touching the filesystem.

Rules (``rule_id`` prefixes appear in every message):

* ``DOM-LOAD``     -- a table inside a domain failed to load.
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
* ``DOM-WAYS``     -- a ``separate_ways`` supplier edge may not consume
  anything and may not be the target of a cross-domain foreign key.
* ``DOM-PIN``      -- a consumer's ``suppliers.<d>.version`` range must be
  satisfied by the supplier's declared ``version``.
* ``DOM-COMPAT``   -- (baseline mode) a breaking change to a domain's published
  language requires a MAJOR bump of ``domain.version``.
* ``DOM-VERSION``  -- (warning) a domain with exports declares no ``version``.
* ``DOM-DRIFT``    -- (warning) the same term is defined with different text in
  two domains. Two domains may legitimately mean different things by one word;
  the warning exists so the difference is a decision, not an accident.

Integration patterns other than ``separate_ways`` are advisory. They are the
consumer's assertion about an edge, rendered on the domain map, and are not
enforced: the metadata cannot represent bilateral agreement or supplier-side
capabilities, so any rule beyond ``separate_ways`` would be arbitrary.

Published language (baseline mode)
----------------------------------
The published language of a domain is its export list plus, for each exported
table, the column set, column types, nullability, and primary key -- exactly
what :func:`tablespec.compatibility.check_compatibility` compares. Glossary
terms, expectations, relationships, and non-exported tables are not part of
it. A change is breaking when an export or exported table is removed, or when
the table comparison is not backward compatible (old consumers could no longer
read new data). A forward-incompatible change (a new required column) is
reported as a warning because it constrains producers, not consumers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tablespec.compatibility import check_compatibility
from tablespec.domains import LoadedDomain
from tablespec.models.domain import (
    IntegrationPattern,
    is_major_bump,
    version_satisfies,
)
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
class PublishedLanguageChange:
    """One change to a domain's published language between two roots."""

    domain: str
    component: str  # "exports", "table.<name>", "column.<table>.<col>", "domain"
    change: str  # "export_removed", "export_added", "table_removed", or the compatibility change
    severity: str  # "breaking", "warning", "info"
    description: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.domain}/{self.component}: {self.description}"


@dataclass
class DomainValidationReport:
    """Errors block; warnings inform; published-language changes describe."""

    errors: list[DomainFinding] = field(default_factory=list)
    warnings: list[DomainFinding] = field(default_factory=list)
    published_language: list[PublishedLanguageChange] = field(default_factory=list)

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
    """DOM-SUPPLIER / DOM-WAYS / DOM-PIN: supplier edges are coherent."""
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
        if rel.pattern is IntegrationPattern.SEPARATE_WAYS and rel.consumes:
            findings.append(
                DomainFinding(
                    domain.name,
                    "DOM-WAYS",
                    supplier_name,
                    "separate_ways means no integration; remove the consumes list "
                    "or choose another pattern",
                )
            )
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
        if rel.version:
            have = supplier.metadata.version
            if not have:
                findings.append(
                    DomainFinding(
                        domain.name,
                        "DOM-PIN",
                        supplier_name,
                        f"pinned to '{rel.version}' but supplier '{supplier_name}' "
                        "declares no version",
                    )
                )
            elif not version_satisfies(have, rel.version):
                findings.append(
                    DomainFinding(
                        domain.name,
                        "DOM-PIN",
                        supplier_name,
                        f"supplier version {have} does not satisfy '{rel.version}'",
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
            edge = domain.metadata.suppliers.get(target_domain)
            if edge is None:
                findings.append(
                    DomainFinding(
                        domain.name,
                        "DOM-XREF",
                        entity,
                        f"references {target} but '{target_domain}' is not declared "
                        f"in this domain's suppliers",
                    )
                )
            elif edge.pattern is IntegrationPattern.SEPARATE_WAYS:
                findings.append(
                    DomainFinding(
                        domain.name,
                        "DOM-WAYS",
                        entity,
                        f"references {target} but the '{target_domain}' edge is "
                        "separate_ways",
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


def validate_version_declared(domain: LoadedDomain) -> list[DomainFinding]:
    """DOM-VERSION (warning): a domain that exports tables should declare a version."""
    if domain.metadata.exports and not domain.metadata.version:
        return [
            DomainFinding(
                domain.name,
                "DOM-VERSION",
                "-",
                "domain exports tables but declares no version; consumers cannot "
                "pin it and breaking changes cannot be signalled",
            )
        ]
    return []


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


# --------------------------------------------------------------------------
# Published language: baseline comparison
# --------------------------------------------------------------------------


def published_language_changes(
    old: LoadedDomain | None, new: LoadedDomain | None, name: str
) -> list[PublishedLanguageChange]:
    """Describe how ``name``'s published language changed from ``old`` to ``new``.

    Either side may be ``None`` (domain added or removed). The export lists
    are compared as a union so both removals and additions are seen; tables
    present in both export lists are compared column-by-column through
    :func:`tablespec.compatibility.check_compatibility`.
    """
    changes: list[PublishedLanguageChange] = []
    if old is None and new is None:
        return changes
    if new is None:
        assert old is not None
        if old.metadata.exports:
            changes.append(
                PublishedLanguageChange(
                    name,
                    "domain",
                    "domain_removed",
                    "breaking",
                    f"domain '{name}' with exports {old.metadata.exports} was removed",
                )
            )
        return changes
    if old is None:
        for export in new.metadata.exports:
            changes.append(
                PublishedLanguageChange(
                    name, "exports", "export_added", "info", f"new export '{export}'"
                )
            )
        return changes

    old_exports = {e.lower(): e for e in old.metadata.exports}
    new_exports = {e.lower(): e for e in new.metadata.exports}
    for key in sorted(set(old_exports) | set(new_exports)):
        if key in old_exports and key not in new_exports:
            changes.append(
                PublishedLanguageChange(
                    name,
                    "exports",
                    "export_removed",
                    "breaking",
                    f"'{old_exports[key]}' is no longer exported",
                )
            )
            continue
        if key in new_exports and key not in old_exports:
            changes.append(
                PublishedLanguageChange(
                    name,
                    "exports",
                    "export_added",
                    "info",
                    f"new export '{new_exports[key]}'",
                )
            )
            continue
        old_umf = old.table(key)
        new_umf = new.table(key)
        if old_umf is None:
            # Was exported but never loaded on the old side; nothing to compare.
            continue
        if new_umf is None:
            changes.append(
                PublishedLanguageChange(
                    name,
                    f"table.{old_exports[key]}",
                    "table_removed",
                    "breaking",
                    f"exported table '{old_exports[key]}' no longer exists",
                )
            )
            continue
        report = check_compatibility(old_umf, new_umf)
        for issue in report.issues:
            severity = issue.severity
            if issue.severity == "breaking" and issue.change == "added_required":
                # Forward-only break: constrains producers, not existing consumers.
                severity = "warning"
            changes.append(
                PublishedLanguageChange(
                    name,
                    f"{issue.component}@{old_exports[key]}",
                    issue.change,
                    severity,
                    issue.description,
                )
            )
    return changes


def validate_published_language(
    old_domains: dict[str, LoadedDomain], new_domains: dict[str, LoadedDomain]
) -> tuple[list[PublishedLanguageChange], list[DomainFinding]]:
    """Compare two roots; return the changes and any DOM-COMPAT findings.

    DOM-COMPAT fires when a domain's published language changed in a breaking
    way and its ``version`` did not take a MAJOR bump (or is missing on either
    side, since a breaking change that cannot be signalled is itself the
    defect).
    """
    changes: list[PublishedLanguageChange] = []
    findings: list[DomainFinding] = []
    for name in sorted(set(old_domains) | set(new_domains)):
        old = old_domains.get(name)
        new = new_domains.get(name)
        domain_changes = published_language_changes(old, new, name)
        changes.extend(domain_changes)
        if new is None:
            continue
        breaking = [c for c in domain_changes if c.severity == "breaking"]
        if not breaking:
            continue
        old_version = old.metadata.version if old else None
        new_version = new.metadata.version
        if not old_version or not new_version:
            findings.append(
                DomainFinding(
                    name,
                    "DOM-COMPAT",
                    "-",
                    f"{len(breaking)} breaking published-language change(s) but version "
                    f"is {old_version or 'unset'} -> {new_version or 'unset'}; declare "
                    "version on both sides and bump MAJOR",
                )
            )
        elif not is_major_bump(old_version, new_version):
            findings.append(
                DomainFinding(
                    name,
                    "DOM-COMPAT",
                    "-",
                    f"{len(breaking)} breaking published-language change(s) require a "
                    f"MAJOR bump; version is {old_version} -> {new_version}",
                )
            )
    return changes, findings


def validate_domains(
    domains: dict[str, LoadedDomain],
    *,
    baseline: dict[str, LoadedDomain] | None = None,
) -> DomainValidationReport:
    """Run every rule over a set of loaded domains.

    ``baseline`` is the same corpus at an earlier revision; when given, the
    published-language comparison runs and DOM-COMPAT findings are added.
    """
    report = DomainValidationReport()
    for name in sorted(domains):
        domain = domains[name]
        for err in domain.load_errors:
            report.errors.append(DomainFinding(name, "DOM-LOAD", "-", err))
        report.errors.extend(validate_exports(domain))
        report.errors.extend(validate_suppliers(domain, domains))
        report.errors.extend(validate_cross_domain_keys(domain, domains))
        report.errors.extend(validate_terms(domain))
        report.warnings.extend(validate_version_declared(domain))
    report.warnings.extend(detect_term_drift(domains))
    if baseline is not None:
        changes, compat = validate_published_language(baseline, domains)
        report.published_language.extend(changes)
        report.errors.extend(compat)
    return report


__all__ = [
    "DomainFinding",
    "DomainValidationReport",
    "PublishedLanguageChange",
    "detect_term_drift",
    "published_language_changes",
    "validate_cross_domain_keys",
    "validate_domains",
    "validate_exports",
    "validate_published_language",
    "validate_suppliers",
    "validate_terms",
    "validate_version_declared",
]
