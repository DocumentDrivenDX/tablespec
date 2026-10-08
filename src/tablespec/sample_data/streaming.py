"""Disk-backed generation, FK selection, and constraint verification."""

from collections.abc import Iterator
from datetime import date, datetime, timedelta
from decimal import Decimal
import math
import json
from pathlib import Path
import random
import sqlite3
from typing import Any

import yaml

from tablespec.expectation_utils import expectation_dicts_from_umf_data
from tablespec.schemas.generators import _resolve_nullable

from .config import GenerationConfig
from .domains import get_run_domain_pack


def plan_counts(
    specs: dict[str, dict[str, Any]],
    scale: str,
    overrides: dict[str, int] | None = None,
    root_count: int = 100,
    relationships: dict[str, dict[str, Any]] | None = None,
    preset_path: Path | None = None,
    presets: dict[str, Any] | None = None,
) -> dict[str, int]:
    """Resolve counts from configured parent edges and explicit overrides."""
    if preset_path is not None or presets is None:
        presets = yaml.safe_load(
            (preset_path or Path(__file__).with_name("scales.yaml")).read_text()
        )
    if not isinstance(presets, dict):
        raise ValueError("Scale configuration must be a mapping")
    if scale not in presets:
        raise ValueError(f"Unknown scale: {scale}")
    preset = presets[scale]
    counts = dict(overrides or {})
    if set(counts) - set(specs) or any(n < 0 for n in counts.values()):
        raise ValueError("Invalid table count overrides")
    edges = {**preset["children"], **(relationships or {})}
    pending = set(specs) - set(counts)
    while pending:
        progress = False
        for name in sorted(pending):
            edge = edges.get(name.lower()) or edges.get(name)
            if edge:
                parent = next(
                    (n for n in specs if n.lower() == edge["parent"].lower()), None
                )
                if parent is None:
                    raise ValueError(
                        f"Scale parent missing for {name}: {edge['parent']}"
                    )
                if parent not in counts:
                    continue
                counts[name] = round(counts[parent] * edge["per_parent"])
            else:
                fks = specs[name].get("relationships", {}).get("foreign_keys", [])
                if fks:
                    parent = fks[0]["references_table"]
                    if parent not in counts:
                        continue
                    counts[name] = counts[parent] * 3
                else:
                    counts[name] = preset["roots"].get(
                        name, preset["roots"].get(name.lower(), root_count)
                    )
            if counts[name] < 0:
                raise ValueError("Negative relationship count")
            pending.remove(name)
            progress = True
        if not progress:
            raise ValueError(f"Unresolved scale graph: {sorted(pending)}")
    return counts


def _decimal_canonical(value: Decimal) -> Decimal:
    """Exact numeric identity for spool keys, without context rounding."""
    if value == 0:
        return Decimal(0)
    parts = value.as_tuple()
    digits = list(parts.digits)
    exponent = int(parts.exponent)
    while digits[-1] == 0:
        digits.pop()
        exponent += 1
    return Decimal((parts.sign, tuple(digits), exponent))


class GeneratedDataset:
    """Temporary SQLite spool; memory use is bounded by row/batch size.

    Caller owns connection lifetime. Parent rows and uniqueness indexes stay
    on disk. Unsupported validation expectations fail explicitly.
    """

    def __init__(
        self,
        path: Path,
        specs: dict[str, dict[str, Any]],
        counts: dict[str, int],
        config: GenerationConfig,
    ) -> None:
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA cache_size=-4096")
        self.db.execute(
            "CREATE TABLE rows (tbl TEXT, idx INTEGER, body TEXT, PRIMARY KEY(tbl,idx))"
        )
        self.db.execute(
            "CREATE TABLE unique_values (tbl TEXT, cols TEXT, val TEXT, UNIQUE(tbl,cols,val))"
        )
        self.source_metadata: dict[str, Any] | None = None
        self.source_artifacts: dict[str, Path] = {}
        self.specs = specs
        self.counts = counts
        self.config = config
        self.rng = random.Random(config.random_seed)
        pack = get_run_domain_pack(config)
        self.generators = pack.generators(config)
        self.registry = pack.registry()
        self.report: dict[str, Any] = {}
        self.verified = False
        self.verification: dict[str, int] = {}
        self.planner = (
            self.generators.table_planner(self)
            if hasattr(self.generators, "table_planner")
            else None
        )

    def close(self) -> None:
        """Release the spool connection."""
        self.db.close()

    def batches(
        self, table: str, batch_size: int = 500
    ) -> Iterator[list[dict[str, Any]]]:
        """Read bounded batches in stable order."""
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        cursor = self.db.execute(
            "SELECT body FROM rows WHERE tbl=? ORDER BY idx", (table,)
        )
        while values := cursor.fetchmany(batch_size):
            yield [json.loads(value[0]) for value in values]

    def power_index(self, size: int, child: str) -> int:
        """Sample rank weights proportional to integral x^-exponent, without arrays."""
        if size < 1:
            raise ValueError("Cannot sample an empty parent")
        exponent = (
            self.config.skew_exponent
            if self.config.relationship_distributions.get(child, "skewed") == "skewed"
            else 0
        )
        power = 1 - exponent
        return min(
            size - 1,
            int((1 + self.rng.random() * ((size + 1) ** power - 1)) ** (1 / power)) - 1,
        )

    def _parent(
        self, table: str, child: str, index: int | None = None
    ) -> dict[str, Any]:
        size = self.counts[table]
        if not size:
            raise ValueError(f"Foreign key references empty table {table}")
        if index is None:
            index = self.power_index(size, child)
        elif index >= size:
            raise ValueError(f"One-to-one child count exceeds parent count: {child}")
        value = self.db.execute(
            "SELECT body FROM rows WHERE tbl=? AND idx=?", (table, index)
        ).fetchone()
        if value is None:
            raise ValueError(f"Unresolved parent {table}")
        return json.loads(value[0])

    def _value(self, col: dict[str, Any], index: int) -> Any:
        kind = col.get("domain_type")
        if kind:
            method = self.registry.get_sample_generator_method(kind)
            if not method:
                raise ValueError(f"Unsupported domain type {kind}")
            if hasattr(self.generators, "rng"):
                return getattr(self.generators, method)()
            # Legacy generators use module-level random. Isolate its state per run.
            previous = random.getstate()
            random.setstate(self.rng.getstate())
            try:
                value = getattr(self.generators, method)()
                self.rng.setstate(random.getstate())
                return value
            finally:
                random.setstate(previous)
        dtype = col["data_type"].upper()
        if dtype in ("INTEGER", "INT", "LONG", "BIGINT", "SMALLINT"):
            return index + 1
        if dtype in ("DECIMAL", "FLOAT", "DOUBLE"):
            return float(index + 1)
        if dtype == "BOOLEAN":
            return bool(self.rng.getrandbits(1))
        if dtype in ("DATE", "DATETIME", "TIMESTAMP"):
            value = self.config.get_reference_date() - timedelta(
                days=self.rng.randrange(max(1, self.config.temporal_range_days))
            )
            return value.date().isoformat() if dtype == "DATE" else value.isoformat()
        if dtype in ("STRING", "VARCHAR", "CHAR", "TEXT"):
            return f"Synthetic {index + 1}"
        raise ValueError(f"Unsupported generated type {dtype}")

    def generate(self) -> dict[str, Any]:
        """Generate and validate every row before a sink can mutate targets."""
        pending = set(self.specs)
        completed: set[str] = set()
        while pending:
            progress = False
            for name in sorted(pending):
                spec = self.specs[name]
                fks = spec.get("relationships", {}).get("foreign_keys", [])
                if any(fk.get("cross_pipeline") for fk in fks):
                    raise ValueError(
                        "External FK seeding is forbidden for fabricated datasets"
                    )
                if any(fk["references_table"] not in completed for fk in fks):
                    continue
                if self.planner and not self.planner.dependencies(name) <= completed:
                    continue
                self._table(name, spec, fks)
                completed.add(name)
                pending.remove(name)
                progress = True
            if not progress:
                raise ValueError(f"Cyclic or missing FK parents: {sorted(pending)}")
        if self.planner:
            self.verification = self.planner.verify()
            if self.verification:
                self.report["time_entries"]["legal_verification"] = self.verification
        self.db.commit()
        self.verified = True
        return self.report

    def _table(
        self, name: str, spec: dict[str, Any], fks: list[dict[str, Any]]
    ) -> None:
        columns = [col for col in spec["columns"] if not col.get("internal")]
        unique, rules = self._constraints(spec, columns)
        one_to_one = {
            c["name"] for c in columns if c.get("key_type") == "foreign_one_to_one"
        }
        distinct_parents = {
            fk["references_table"] for fk in fks if fk["column"] in one_to_one
        }
        for parent in distinct_parents:
            if self.counts[name] > self.counts[parent]:
                raise ValueError(f"One-to-one child count exceeds parent count: {name}")
        for index in range(self.counts[name]):
            parents: dict[str, dict[str, Any]] = {}
            row: dict[str, Any] = {}
            # Matter context must exist before selecting an eligible timekeeper.
            for fk in sorted(
                fks,
                key=lambda f: (
                    f["references_table"] != "matters",
                    f["references_table"] == "timekeepers",
                ),
            ):
                parent_name = fk["references_table"]
                if parent_name not in parents:
                    selected = (
                        self.planner.select_person(name, index, parents)
                        if self.planner and parent_name == "timekeepers"
                        else None
                    )
                    selected_index = (
                        index
                        if parent_name in distinct_parents
                        else self.planner.parent_index(name, fk, index, parents)
                        if self.planner
                        else None
                    )
                    parents[parent_name] = selected or self._parent(
                        parent_name, name, selected_index
                    )
                row[fk["column"]] = parents[parent_name][fk["references_column"]]
            for col in columns:
                if col["name"] not in row:
                    row[col["name"]] = self._value(col, index)
            if hasattr(self.generators, "correlate"):
                context = {
                    k: v for parent in parents.values() for k, v in parent.items()
                }
                for parent_table, parent in parents.items():
                    for parent_col in self.specs[parent_table]["columns"]:
                        if parent_col.get("domain_type"):
                            context[parent_col["domain_type"]] = parent[
                                parent_col["name"]
                            ]
                fk_columns = {fk["column"] for fk in fks}
                row = self.generators.correlate(
                    row,
                    [c for c in columns if c["name"] not in fk_columns],
                    context,
                    index,
                )
            if self.planner:
                self.planner.adjust(name, row, parents)
            # Apply value sets/ranges only to generic values; semantic conflicts fail.
            for rule in rules:
                kw = rule["kwargs"]
                colname = kw.get("column")
                col = next((c for c in columns if c["name"] == colname), {})
                if (
                    col.get("domain_type")
                    or colname in {fk["column"] for fk in fks}
                    or row.get(colname) is None
                ):
                    continue
                if rule["type"] == "expect_column_values_to_be_in_set":
                    row[colname] = self.rng.choice(kw["value_set"])
                if rule["type"] == "expect_column_values_to_be_between":
                    minimum = self._bound(
                        kw.get("min_value"), col, kw.get("strict_min", False), 1
                    )
                    maximum = self._bound(
                        kw.get("max_value"), col, kw.get("strict_max", False), -1
                    )
                    if minimum is not None:
                        row[colname] = max(minimum, row[colname])
                    if maximum is not None:
                        row[colname] = min(maximum, row[colname])
            if hasattr(self.generators, "validate_correlations"):
                self.generators.validate_correlations(
                    row,
                    {k: v for parent in parents.values() for k, v in parent.items()},
                )
            for fk in fks:
                if (
                    row[fk["column"]]
                    != parents[fk["references_table"]][fk["references_column"]]
                ):
                    raise ValueError(
                        f"FK orphan after correlation: {name}.{fk['column']}"
                    )
            self._check(name, row, columns, unique, rules)
            if self.planner:
                self.planner.recorded(name, row, index)
            self.db.execute(
                "INSERT INTO rows VALUES (?,?,?)", (name, index, json.dumps(row))
            )
        self.report[name] = {
            "row_count": self.counts[name],
            "fk_orphan_count": 0,
            "null_violations": 0,
            "uniqueness_violations": 0,
        }

    @staticmethod
    def _constraints(
        spec: dict[str, Any], columns: list[dict[str, Any]]
    ) -> tuple[list[list[str]], list[dict[str, Any]]]:
        """Share supported constraint admission between generated and supplied rows."""
        rules = expectation_dicts_from_umf_data(spec)
        supported = {
            "expect_column_values_to_not_be_null",
            "expect_column_values_to_be_unique",
            "expect_compound_columns_to_be_unique",
            "expect_column_values_to_be_in_set",
            "expect_column_values_to_be_between",
            "expect_column_values_to_match_regex",
            "expect_column_values_to_be_of_type",
        }
        for rule in rules:
            if rule["type"] not in supported:
                raise ValueError(f"Unsupported sample constraint: {rule['type']}")
        unique = list(spec.get("unique_constraints") or [])
        if spec.get("primary_key"):
            unique.append(spec["primary_key"])
        unique.extend(
            [c["name"]]
            for c in columns
            if c.get("key_type") in ("primary", "unique", "foreign_one_to_one")
        )
        for rule in rules:
            if rule["type"] == "expect_column_values_to_be_unique":
                unique.append([rule["kwargs"]["column"]])
            if rule["type"] == "expect_compound_columns_to_be_unique":
                unique.append(rule["kwargs"]["column_list"])
        unique = [list(cols) for cols in dict.fromkeys(tuple(cols) for cols in unique)]
        return unique, rules

    @staticmethod
    def _bound(value: Any, col: dict[str, Any], strict: bool, direction: int) -> Any:
        """Convert exclusive bounds to the next representable generated value."""
        if value is None or not strict:
            return value
        dtype = col["data_type"].upper()
        if dtype in ("INTEGER", "INT", "LONG", "BIGINT", "SMALLINT"):
            return math.floor(value) + 1 if direction > 0 else math.ceil(value) - 1
        if dtype == "DECIMAL":
            from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

            step = Decimal(10) ** -(col.get("scale") or 0)
            units = (Decimal(str(value)) / step).to_integral_value(
                rounding=ROUND_FLOOR if direction > 0 else ROUND_CEILING
            )
            return float((units + direction) * step)
        if dtype in ("FLOAT", "DOUBLE"):
            return math.nextafter(value, math.inf if direction > 0 else -math.inf)
        if dtype == "DATE":
            return (date.fromisoformat(value) + timedelta(days=direction)).isoformat()
        if dtype in ("DATETIME", "TIMESTAMP"):
            return (
                datetime.fromisoformat(value) + timedelta(microseconds=direction)
            ).isoformat()
        raise ValueError(f"Unsupported exclusive range type: {dtype}")

    def _check(
        self,
        name: str,
        row: dict[str, Any],
        columns: list[dict[str, Any]],
        unique: list[list[str]],
        rules: list[dict[str, Any]],
    ) -> None:
        import re

        for col in columns:
            value = row[col["name"]]
            dtype = col["data_type"].upper()
            if value is not None:
                if dtype in ("VARCHAR", "CHAR", "TEXT", "STRING") and not isinstance(
                    value, str
                ):
                    raise ValueError(f"String type violation: {name}.{col['name']}")
                if dtype in ("INTEGER", "INT", "LONG", "BIGINT", "SMALLINT") and (
                    not isinstance(value, int) or isinstance(value, bool)
                ):
                    raise ValueError(f"Integer type violation: {name}.{col['name']}")
                if dtype in ("DECIMAL", "FLOAT", "DOUBLE") and (
                    not isinstance(value, (int, float, Decimal))
                    or isinstance(value, bool)
                ):
                    raise ValueError(f"Numeric type violation: {name}.{col['name']}")
                if dtype == "BOOLEAN" and not isinstance(value, bool):
                    raise ValueError(f"Boolean type violation: {name}.{col['name']}")
                if dtype == "DECIMAL" and col.get("precision"):
                    decimal = Decimal(str(value))
                    scale = col.get("scale") or 0
                    if (
                        decimal.copy_abs() >= Decimal(10) ** (col["precision"] - scale)
                        or int(_decimal_canonical(decimal).as_tuple().exponent) < -scale
                    ):
                        raise ValueError(
                            f"Decimal precision/scale violation: {name}.{col['name']}"
                        )
            if value is None and (
                not _resolve_nullable(col.get("nullable"))
                or col["name"] in self.specs[name].get("primary_key", [])
            ):
                raise ValueError(f"Null constraint violation: {name}.{col['name']}")
            length = col.get("max_length") or col.get("length")
            if length and isinstance(value, str) and len(value) > length:
                raise ValueError(f"Length constraint violation: {name}.{col['name']}")
        for cols in unique:
            values = [
                str(_decimal_canonical(row[c]))
                if isinstance(row[c], Decimal)
                else row[c]
                for c in cols
            ]
            if any(v is None for v in values):
                continue
            try:
                self.db.execute(
                    "INSERT INTO unique_values VALUES (?,?,?)",
                    (name, json.dumps(cols), json.dumps(values, default=str)),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    f"Uniqueness constraint violation: {name}.{cols}"
                ) from exc
        for rule in rules:
            kw = rule["kwargs"]
            value = row.get(kw.get("column"))
            kind = rule["type"]
            valid = True
            if kind == "expect_column_values_to_not_be_null":
                valid = value is not None
            elif value is not None and kind == "expect_column_values_to_be_in_set":
                valid = value in [
                    Decimal(str(item))
                    if isinstance(value, Decimal)
                    and isinstance(item, (int, float))
                    and not isinstance(item, bool)
                    else item
                    for item in kw["value_set"]
                ]
            elif value is not None and kind == "expect_column_values_to_be_between":
                minimum, maximum = kw.get("min_value"), kw.get("max_value")
                if isinstance(value, Decimal):
                    minimum = Decimal(str(minimum)) if minimum is not None else None
                    maximum = Decimal(str(maximum)) if maximum is not None else None
                valid = (
                    minimum is None
                    or (value > minimum if kw.get("strict_min") else value >= minimum)
                ) and (
                    maximum is None
                    or (value < maximum if kw.get("strict_max") else value <= maximum)
                )
            elif value is not None and kind == "expect_column_values_to_be_of_type":
                expected = str(kw["type_"]).upper().replace("TYPE", "")
                checks = {
                    "STRING": isinstance(value, str),
                    "VARCHAR": isinstance(value, str),
                    "INTEGER": isinstance(value, int) and not isinstance(value, bool),
                    "INT": isinstance(value, int) and not isinstance(value, bool),
                    "LONG": isinstance(value, int) and not isinstance(value, bool),
                    "BOOLEAN": isinstance(value, bool),
                    "DECIMAL": isinstance(value, (int, float, Decimal))
                    and not isinstance(value, bool),
                    "FLOAT": isinstance(value, (int, float, Decimal))
                    and not isinstance(value, bool),
                    "DOUBLE": isinstance(value, (int, float, Decimal))
                    and not isinstance(value, bool),
                    "DATE": isinstance(value, str)
                    and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)),
                    "TIMESTAMP": isinstance(value, str) and "T" in value,
                }
                if expected not in checks:
                    raise ValueError(f"Unsupported type constraint: {expected}")
                valid = checks[expected]
            elif value is not None and kind == "expect_column_values_to_match_regex":
                valid = re.search(kw["regex"], str(value)) is not None
            if not valid:
                raise ValueError(f"Constraint violation: {name} {kind}")
