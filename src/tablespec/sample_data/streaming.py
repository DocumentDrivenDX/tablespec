"""Disk-backed generation, FK selection, and constraint verification."""

from collections.abc import Iterator
from datetime import timedelta
import json
from pathlib import Path
import random
import sqlite3
from typing import Any

import yaml

from tablespec.expectation_utils import expectation_dicts_from_umf_data
from tablespec.schemas.generators import _resolve_nullable

from .config import GenerationConfig
from .domains import get_domain_pack


def plan_counts(
    specs: dict[str, dict[str, Any]],
    scale: str,
    overrides: dict[str, int] | None = None,
    root_count: int = 100,
    relationships: dict[str, dict[str, Any]] | None = None,
    preset_path: Path | None = None,
) -> dict[str, int]:
    """Resolve counts from configured parent edges and explicit overrides."""
    presets = yaml.safe_load(
        (preset_path or Path(__file__).with_name("scales.yaml")).read_text()
    )
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
        self.specs = specs
        self.counts = counts
        self.config = config
        self.rng = random.Random(config.random_seed)
        pack = get_domain_pack(config.domain)
        self.generators = pack.generators(config)
        self.registry = pack.registry()
        self.report: dict[str, Any] = {}

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

    def _parent(self, table: str, child: str) -> dict[str, Any]:
        size = self.counts[table]
        if not size:
            raise ValueError(f"Foreign key references empty table {table}")
        hot = max(1, size // 5)
        ratio = (
            self.config.high_frequency_key_ratio
            if self.config.relationship_distributions.get(
                child,
                self.config.relationship_distributions.get(child.lower(), "skewed"),
            )
            == "skewed"
            else 0
        )
        index = self.rng.randrange(hot if self.rng.random() < ratio else size)
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
                self._table(name, spec, fks)
                completed.add(name)
                pending.remove(name)
                progress = True
            if not progress:
                raise ValueError(f"Cyclic or missing FK parents: {sorted(pending)}")
        self.db.commit()
        return self.report

    def _table(
        self, name: str, spec: dict[str, Any], fks: list[dict[str, Any]]
    ) -> None:
        columns = [col for col in spec["columns"] if not col.get("internal")]
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
            [c["name"]] for c in columns if c.get("key_type") in ("primary", "unique")
        )
        for rule in rules:
            if rule["type"] == "expect_column_values_to_be_unique":
                unique.append([rule["kwargs"]["column"]])
            if rule["type"] == "expect_compound_columns_to_be_unique":
                unique.append(rule["kwargs"]["column_list"])
        unique = [list(cols) for cols in dict.fromkeys(tuple(cols) for cols in unique)]
        for index in range(self.counts[name]):
            parents: dict[str, dict[str, Any]] = {}
            row: dict[str, Any] = {}
            for fk in fks:
                if fk["references_table"] not in parents:
                    parents[fk["references_table"]] = self._parent(
                        fk["references_table"], name
                    )
                parent = parents[fk["references_table"]]
                row[fk["column"]] = parent[fk["references_column"]]
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
            # Apply value sets/ranges only to generic values; semantic conflicts fail.
            for rule in rules:
                kw = rule["kwargs"]
                colname = kw.get("column")
                col = next((c for c in columns if c["name"] == colname), {})
                if col.get("domain_type") or colname in {fk["column"] for fk in fks}:
                    continue
                if rule["type"] == "expect_column_values_to_be_in_set":
                    row[colname] = self.rng.choice(kw["value_set"])
                if rule["type"] == "expect_column_values_to_be_between":
                    minimum = kw.get("min_value")
                    maximum = kw.get("max_value")
                    if minimum is not None:
                        row[colname] = max(minimum, row[colname])
                    if maximum is not None:
                        row[colname] = min(maximum, row[colname])
            for fk in fks:
                if (
                    row[fk["column"]]
                    != parents[fk["references_table"]][fk["references_column"]]
                ):
                    raise ValueError(
                        f"FK orphan after correlation: {name}.{fk['column']}"
                    )
            self._check(name, row, columns, unique, rules)
            self.db.execute(
                "INSERT INTO rows VALUES (?,?,?)", (name, index, json.dumps(row))
            )
        self.report[name] = {
            "row_count": self.counts[name],
            "fk_orphan_count": 0,
            "null_violations": 0,
            "uniqueness_violations": 0,
        }

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
                    not isinstance(value, (int, float)) or isinstance(value, bool)
                ):
                    raise ValueError(f"Numeric type violation: {name}.{col['name']}")
                if dtype == "BOOLEAN" and not isinstance(value, bool):
                    raise ValueError(f"Boolean type violation: {name}.{col['name']}")
                if dtype == "DECIMAL" and col.get("precision"):
                    from decimal import Decimal

                    decimal = Decimal(str(value))
                    scale = col.get("scale") or 0
                    if abs(decimal) >= Decimal(10) ** (
                        col["precision"] - scale
                    ) or decimal != decimal.quantize(Decimal(10) ** -scale):
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
            values = [row[c] for c in cols]
            if any(v is None for v in values):
                continue
            try:
                self.db.execute(
                    "INSERT INTO unique_values VALUES (?,?,?)",
                    (name, json.dumps(cols), json.dumps(values)),
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
                valid = value in kw["value_set"]
            elif value is not None and kind == "expect_column_values_to_be_between":
                valid = (kw.get("min_value") is None or value >= kw["min_value"]) and (
                    kw.get("max_value") is None or value <= kw["max_value"]
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
                    "DECIMAL": isinstance(value, (int, float))
                    and not isinstance(value, bool),
                    "FLOAT": isinstance(value, (int, float))
                    and not isinstance(value, bool),
                    "DOUBLE": isinstance(value, (int, float))
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
