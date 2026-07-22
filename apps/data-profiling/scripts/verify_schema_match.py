"""
Compare CSV column headers in data/synthetic/prod_main_clinical/
against the actual Databricks table columns in test_main_clinical.

Uses the Databricks SDK (profile: gfischer) + Statement Execution API.
Prints a diff for each table: MATCH / MISSING / EXTRA columns.

Usage:
  python scripts/verify_schema_match.py
  python scripts/verify_schema_match.py --catalog dev --schema test_main_clinical
  python scripts/verify_schema_match.py --catalog test_main --schema clinical
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--catalog", default="dev")
parser.add_argument("--schema", default="test_main_clinical")
parser.add_argument("--csv-dir", default="data/synthetic/prod_main_clinical")
parser.add_argument("--date-tag", default="20260618")
parser.add_argument("--warehouse-id", default="2ad65b4df5cd3a9e")
parser.add_argument("--profile", default="gfischer")
args = parser.parse_args()

# Imported after parse_args so --help returns immediately instead of paying the
# databricks-sdk import cost first.
from databricks.sdk import WorkspaceClient  # noqa: E402
from databricks.sdk.service.sql import StatementState  # noqa: E402

w = WorkspaceClient(profile=args.profile)

# ── Pull columns from Databricks information_schema ───────────────────────────
SQL = f"""
SELECT table_name, column_name, ordinal_position
FROM   {args.catalog}.information_schema.columns
WHERE  table_schema = '{args.schema}'
ORDER  BY table_name, ordinal_position
"""

print(
    f"Querying {args.catalog}.information_schema.columns where table_schema = '{args.schema}' ..."
)

resp = w.statement_execution.execute_statement(
    warehouse_id=args.warehouse_id,
    statement=SQL,
    wait_timeout="30s",
)

# Poll if still running
while resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
    time.sleep(2)
    resp = w.statement_execution.get_statement(resp.statement_id)

if resp.status.state != StatementState.SUCCEEDED:
    print(f"ERROR: query failed — {resp.status.error}")
    raise SystemExit(1)

# Build dict: table -> [col, col, ...]  (ordered by ordinal_position)
dbx_cols: dict[str, list[str]] = {}
if resp.result and resp.result.data_array:
    for row in resp.result.data_array:
        tbl, col, _ = row[0], row[1], row[2]
        dbx_cols.setdefault(tbl, []).append(col)

if not dbx_cols:
    print(f"\nNo tables found in {args.catalog}.{args.schema}.")
    print("Double-check --catalog and --schema. Trying common alternatives:")
    for alt_cat, alt_sch in [
        ("dev", "test_main_clinical"),
        ("test_main", "clinical"),
        ("prod_main", "clinical"),
    ]:
        print(
            f"  python scripts/verify_schema_match.py --catalog {alt_cat} --schema {alt_sch}"
        )
    raise SystemExit(0)

print(
    f"Found {len(dbx_cols)} tables in {args.catalog}.{args.schema}: {sorted(dbx_cols)}\n"
)

# ── Read CSV headers ──────────────────────────────────────────────────────────
csv_dir = Path(args.csv_dir)
TABLES = [
    "practitioner",
    "location",
    "encounter",
    "condition",
    "procedure",
    "lab_result",
    "observation",
    "medication",
    "immunization",
    "appointment",
]

csv_cols: dict[str, list[str]] = {}
for tbl in TABLES:
    f = csv_dir / f"{tbl}_{args.date_tag}.csv"
    if f.exists():
        with open(f, newline="", encoding="utf-8") as fh:
            csv_cols[tbl] = next(csv.reader(fh))
    else:
        csv_cols[tbl] = []

# ── Diff ──────────────────────────────────────────────────────────────────────
any_diff = False
for tbl in TABLES:
    dbx = dbx_cols.get(tbl, [])
    csv = csv_cols.get(tbl, [])

    if not dbx:
        print(f"[SKIP]  {tbl:<20s}  — not found in Databricks schema")
        continue

    csv_data = list(csv)
    dbx_set = set(dbx)
    csv_set = set(csv_data)

    missing_from_csv = sorted(dbx_set - csv_set)  # in Databricks but not in CSV
    extra_in_csv = sorted(csv_set - dbx_set)  # in CSV but not in Databricks
    order_match = dbx == csv_data

    if not missing_from_csv and not extra_in_csv:
        order_note = "" if order_match else "  (col ORDER differs)"
        print(f"[OK]    {tbl:<20s}  {len(dbx)} cols match{order_note}")
    else:
        any_diff = True
        print(
            f"[DIFF]  {tbl:<20s}  Databricks={len(dbx)} cols  CSV={len(csv_data)} cols"
        )
        if missing_from_csv:
            print(f"        MISSING from CSV  : {missing_from_csv}")
        if extra_in_csv:
            print(f"        EXTRA in CSV      : {extra_in_csv}")
        if not order_match and not missing_from_csv and not extra_in_csv:
            print(f"        Databricks order  : {dbx}")
            print(f"        CSV order         : {csv_data}")

print()
if any_diff:
    print(
        "ACTION NEEDED: update generate_synthetic_clinical_data.py to fix the diffs above."
    )
else:
    print(
        "All tables match the Databricks schema (META_ columns excluded from comparison)."
    )
