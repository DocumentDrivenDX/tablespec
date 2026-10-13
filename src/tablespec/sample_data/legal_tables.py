"""Relational legal fixtures: disk-backed staffing and invoice aggregates.

This module generates tabular records only; it defines no ontology.
"""

from typing import Any


class LegalTablePlanner:
    """Coordinate the eight example tables using the dataset's SQLite spool."""

    def __init__(self, dataset: Any) -> None:
        self.data = dataset
        self.active = {
            "clients",
            "matters",
            "timekeepers",
            "matter_teams",
            "ethical_walls",
            "time_entries",
        } <= set(dataset.specs)
        if self.active:
            dataset.db.execute(
                "CREATE TABLE staffing (matter INTEGER, person INTEGER, wall INTEGER, PRIMARY KEY(matter,person))"
            )
            dataset.db.execute(
                "CREATE TABLE people (idx INTEGER PRIMARY KEY, id INTEGER UNIQUE, level TEXT)"
            )
            dataset.db.execute(
                "CREATE TABLE daily_amounts (matter INTEGER, day TEXT, cents INTEGER, PRIMARY KEY(matter,day))"
            )

    def dependencies(self, table: str) -> set[str]:
        """Add relational dependencies beyond individual FK edges."""
        if not self.active:
            return set()
        return {
            "ethical_walls": {"matter_teams"},
            "time_entries": {"matter_teams", "ethical_walls"},
            "invoices": {"time_entries"},
        }.get(table, set())

    def parent_index(
        self,
        table: str,
        fk: dict[str, Any],
        index: int,
        parents: dict[str, dict[str, Any]],
    ) -> int | None:
        """Cover required parents, then use the configured power-law distribution."""
        if not self.active:
            return None
        parent = fk["references_table"]
        size = self.data.counts[parent]
        if table == "invoices" and parent == "clients":
            return self.data.db.execute(
                "SELECT idx FROM rows WHERE tbl='clients' AND json_extract(body, '$.client_id')=?",
                (parents["matters"]["client_id"],),
            ).fetchone()[0]
        if (table, parent) in (("matters", "clients"), ("time_entries", "matters")):
            if self.data.counts[table] < size:
                raise ValueError(f"{table} needs at least one row per {parent}")
            return index if index < size else self.data.power_index(size, table)
        if table in ("matter_teams", "ethical_walls") and parent == "matters":
            return index % size
        return None

    def select_person(
        self, table: str, index: int, parents: dict[str, dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Choose a distinct available staff member, or a member of the entry's team."""
        if not self.active or table not in (
            "matter_teams",
            "ethical_walls",
            "time_entries",
        ):
            return None
        matter = parents["matters"]["matter_id"]
        db = self.data.db
        if table == "time_entries":
            role = (
                "AND p.level='partner'" if index % 4 == 0 else "AND p.level!='partner'"
            )
            candidates = [
                r[0]
                for r in db.execute(
                    f"SELECT p.idx FROM staffing s JOIN people p ON p.id=s.person WHERE s.matter=? AND s.wall=0 {role} ORDER BY p.idx",
                    (matter,),
                )
            ]
        else:
            if (
                table == "matter_teams"
                and self.data.counts[table] < 2 * self.data.counts["matters"]
            ):
                raise ValueError("Every matter requires at least two team members")
            slot = index // self.data.counts["matters"]
            level = (
                "AND p.level='partner'"
                if table == "matter_teams" and slot == 0
                else "AND p.level!='partner'"
                if table == "matter_teams" and slot == 1
                else ""
            )
            candidates = [
                r[0]
                for r in db.execute(
                    f"SELECT p.idx FROM people p WHERE NOT EXISTS (SELECT 1 FROM staffing s WHERE s.matter=? AND s.person=p.id) {level} ORDER BY p.idx",
                    (matter,),
                )
            ]
        if not candidates:
            raise ValueError(f"No eligible timekeeper for {table}, matter {matter}")
        if table == "matter_teams" and slot == 1:
            selected = candidates[
                (index % self.data.counts["matters"]) % len(candidates)
            ]
            return self.data._parent("timekeepers", table, selected)
        # Global rank weights create hot timekeepers while respecting staffing.
        exponent = (
            self.data.config.skew_exponent
            if self.data.config.relationship_distributions.get(table, "skewed")
            == "skewed"
            else 0
        )
        weights = [(i + 1) ** -exponent for i in candidates]
        selected = self.data.rng.choices(candidates, weights=weights, k=1)[0]
        return self.data._parent("timekeepers", table, selected)

    def adjust(
        self, table: str, row: dict[str, Any], parents: dict[str, dict[str, Any]]
    ) -> None:
        """Fill columns whose values depend on other complete tables."""
        if not self.active:
            return
        if table == "timekeepers":
            # A deterministic first cycle guarantees all four staffing levels.
            from .legal import LEVEL_RATES

            level = tuple(LEVEL_RATES)[(row["timekeeper_id"] - 1) % 4]
            row["timekeeper_level"] = level
            if "billing_rate" in row:
                row["billing_rate"] = LEVEL_RATES[level]
        if table == "invoices" and "total_amount" in row:
            from datetime import date, timedelta

            matter = parents["matters"]
            opened = date.fromisoformat(matter["open_date"])
            reference = self.data.config.get_reference_date().date()
            closed = (
                date.fromisoformat(matter["close_date"])
                if matter["close_date"]
                else reference
            )
            start = opened + timedelta(
                days=self.data.rng.randrange(max(1, (closed - opened).days + 1))
            )
            end = min(start + timedelta(days=29), closed)
            issued = end + timedelta(days=self.data.rng.randint(1, 10))
            row.update(
                client_id=matter["client_id"],
                period_start=start.isoformat(),
                period_end=end.isoformat(),
                invoice_date=issued.isoformat(),
            )
            cents = self.data.db.execute(
                "SELECT COALESCE(SUM(cents),0) FROM daily_amounts WHERE matter=? AND day BETWEEN ? AND ?",
                (row["matter_id"], row["period_start"], row["period_end"]),
            ).fetchone()[0]
            row["total_amount"] = cents / 100
            row["invoice_status"] = (
                "draft"
                if issued > reference
                else self.data.rng.choice(
                    ("issued", "paid", "overdue")
                    if (reference - issued).days > 30
                    else ("issued", "paid")
                )
            )

    def recorded(self, table: str, row: dict[str, Any], index: int) -> None:
        """Persist bounded relational indexes after validation."""
        if not self.active:
            return
        db = self.data.db
        if table == "timekeepers":
            db.execute(
                "INSERT INTO people VALUES (?,?,?)",
                (index, row["timekeeper_id"], row["timekeeper_level"]),
            )
        if table in ("matter_teams", "ethical_walls"):
            db.execute(
                "INSERT INTO staffing VALUES (?,?,?)",
                (row["matter_id"], row["timekeeper_id"], int(table == "ethical_walls")),
            )
        if table == "time_entries" and "amount" in row:
            db.execute(
                "INSERT INTO daily_amounts VALUES (?,?,?) ON CONFLICT(matter,day) DO UPDATE SET cents=cents+excluded.cents",
                (row["matter_id"], row["entry_date"], round(row["amount"] * 100)),
            )

    def verify(self) -> dict[str, int]:
        """Independently audit generated tables using the same SQL as UC read-back."""
        if not self.active:
            return {}
        from .verification import legal_checks

        # Expression indexes keep the independent relational audit bounded and fast.
        self.data.db.execute(
            "CREATE INDEX audit_pairs ON rows (tbl,json_extract(body, '$.matter_id'),json_extract(body, '$.timekeeper_id'))"
        )
        self.data.db.execute(
            "CREATE INDEX audit_clients ON rows (tbl,json_extract(body, '$.client_id'))"
        )
        self.data.db.execute(
            "CREATE INDEX audit_people ON rows (tbl,json_extract(body, '$.timekeeper_id'))"
        )
        # SQLite JSON views expose the spool as normal relational tables.
        for table in self.data.specs:
            cols = ",".join(
                f"json_extract(body, '$.{c['name']}') AS \"{c['name']}\""
                for c in self.data.specs[table]["columns"]
                if not c.get("internal")
            )
            self.data.db.execute(
                f"CREATE TEMP VIEW \"{table}\" AS SELECT {cols} FROM rows WHERE tbl='{table}'"
            )
        result = {
            key: self.data.db.execute(sql).fetchone()[0]
            for key, sql in legal_checks(lambda name: f'"{name}"').items()
        }
        if any(result.values()):
            raise ValueError(f"Legal entitlement verification failed: {result}")
        return result
