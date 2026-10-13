"""Tabular SQL audits shared by local generation and UC read-back."""

from collections.abc import Callable
from typing import Any, Protocol


class QuerySink(Protocol):
    """Read a bounded aggregate result through the loading connection."""

    def query(self, statement: str) -> list[list[Any]]:
        """Return aggregate result rows, or raise on execution failure."""
        ...


def legal_checks(table: Callable[[str], str]) -> dict[str, str]:
    """Return zero-violation SQL for legal tabular entitlement rules."""
    teams, walls, entries, matters, people, clients = (
        table(t)
        for t in (
            "matter_teams",
            "ethical_walls",
            "time_entries",
            "matters",
            "timekeepers",
            "clients",
        )
    )
    pair = "t.matter_id=w.matter_id AND t.timekeeper_id=w.timekeeper_id"
    return {
        "duplicate_team_pairs": f"SELECT COALESCE(SUM(n-1),0) FROM (SELECT COUNT(*) n FROM {teams} GROUP BY matter_id,timekeeper_id HAVING COUNT(*)>1) d",
        "duplicate_wall_pairs": f"SELECT COALESCE(SUM(n-1),0) FROM (SELECT COUNT(*) n FROM {walls} GROUP BY matter_id,timekeeper_id HAVING COUNT(*)>1) d",
        "team_wall_overlap": f"SELECT COUNT(*) FROM {teams} t JOIN {walls} w ON {pair}",
        "off_team_entries": f"SELECT COUNT(*) FROM {entries} e WHERE NOT EXISTS (SELECT 1 FROM {teams} t WHERE t.matter_id=e.matter_id AND t.timekeeper_id=e.timekeeper_id)",
        "walled_entries": f"SELECT COUNT(*) FROM {entries} t JOIN {walls} w ON {pair}",
        "missing_partner": f"SELECT COUNT(*) FROM {matters} m WHERE NOT EXISTS (SELECT 1 FROM {teams} t JOIN {people} p ON t.timekeeper_id=p.timekeeper_id WHERE t.matter_id=m.matter_id AND p.timekeeper_level='partner')",
        "missing_other_member": f"SELECT COUNT(*) FROM {matters} m WHERE NOT EXISTS (SELECT 1 FROM {teams} t JOIN {people} p ON t.timekeeper_id=p.timekeeper_id WHERE t.matter_id=m.matter_id AND p.timekeeper_level!='partner')",
        "matters_without_entries": f"SELECT COUNT(*) FROM {matters} m WHERE NOT EXISTS (SELECT 1 FROM {entries} e WHERE e.matter_id=m.matter_id)",
        "clients_without_matters": f"SELECT COUNT(*) FROM {clients} c WHERE NOT EXISTS (SELECT 1 FROM {matters} m WHERE m.client_id=c.client_id)",
        "entry_date_outside_period": f"SELECT COUNT(*) FROM {entries} e JOIN {matters} m ON e.matter_id=m.matter_id WHERE e.entry_date<m.open_date OR (m.close_date IS NOT NULL AND e.entry_date>m.close_date)",
    }


def verification_queries(
    specs: dict[str, dict[str, Any]],
    counts: dict[str, int],
    table: Callable[[str], str],
    legal: bool = False,
) -> dict[str, tuple[str, int]]:
    """Create row-count and FK checks, plus legal cross-table invariants."""
    checks = {}
    for name, spec in specs.items():
        checks[f"{name}.row_count"] = (
            f"SELECT COUNT(*) FROM {table(name)}",
            counts[name],
        )
        for fk in spec.get("relationships", {}).get("foreign_keys", []):
            from .sink import identifier

            col, parent_col = (
                identifier(fk["column"]),
                identifier(fk["references_column"]),
            )
            checks[f"{name}.{fk['column']}.orphans"] = (
                f"SELECT COUNT(*) FROM {table(name)} c WHERE c.{col} IS NOT NULL AND NOT EXISTS (SELECT 1 FROM {table(fk['references_table'])} p WHERE c.{col}=p.{parent_col})",
                0,
            )
    if legal and {
        "clients",
        "matters",
        "timekeepers",
        "matter_teams",
        "ethical_walls",
        "time_entries",
    } <= set(specs):
        checks.update({key: (sql, 0) for key, sql in legal_checks(table).items()})
    return checks


def verify_loaded(
    specs: dict[str, dict[str, Any]],
    counts: dict[str, int],
    target: str,
    sink: QuerySink,
    legal: bool = False,
) -> dict[str, dict[str, Any]]:
    """Read back all checks and fail if any aggregate differs from its expectation."""
    from .sink import identifier, target_namespace

    namespace = target_namespace(target)
    result = {}
    for key, (sql, expected) in verification_queries(
        specs, counts, lambda name: f"{namespace}.{identifier(name)}", legal
    ).items():
        rows = sink.query(sql)
        if len(rows) != 1 or len(rows[0]) != 1:
            raise RuntimeError(f"Invalid verification result: {key}")
        actual = int(rows[0][0])
        result[key] = {
            "actual": actual,
            "expected": expected,
            "passed": actual == expected,
        }
    if not all(check["passed"] for check in result.values()):
        failed = {key: check for key, check in result.items() if not check["passed"]}
        raise RuntimeError(f"Load verification FAILED: {failed}")
    return result
