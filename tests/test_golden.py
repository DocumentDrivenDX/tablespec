"""Golden file tests for schema generators.

Each test case is a pair of files in tests/golden/<generator>/:
  - <name>.input.yaml  — UMF input data
  - <name>.expected.*   — expected generator output

The test runner discovers all input files, runs the corresponding generator,
and compares the output against the expected file.
"""

import json
from pathlib import Path

import pytest
import yaml

from tablespec.schemas.generators import (
    generate_json_schema,
    generate_pyspark_schema,
    generate_sql_ddl,
)
from tablespec.schemas.ingest_generator import generate_ingest_sql

GOLDEN_DIR = Path(__file__).parent / "golden"


def _discover_cases(subdir: str, expected_ext: str) -> list[tuple[str, Path, Path]]:
    """Discover golden test cases in a subdirectory.

    Returns list of (test_name, input_path, expected_path) tuples.
    """
    case_dir = GOLDEN_DIR / subdir
    if not case_dir.exists():
        return []

    cases = []
    for input_file in sorted(case_dir.glob("*.input.yaml")):
        name = input_file.name.replace(".input.yaml", "")
        expected_file = case_dir / f"{name}.expected.{expected_ext}"
        if expected_file.exists():
            cases.append((name, input_file, expected_file))
    return cases


# --- SQL DDL golden tests ---

sql_ddl_cases = _discover_cases("sql_ddl", "sql")


@pytest.mark.parametrize(
    "name,input_path,expected_path",
    sql_ddl_cases,
    ids=[c[0] for c in sql_ddl_cases],
)
def test_sql_ddl_golden(name: str, input_path: Path, expected_path: Path) -> None:
    """Verify SQL DDL output matches golden file."""
    umf_data = yaml.safe_load(input_path.read_text())
    actual = generate_sql_ddl(umf_data)
    expected = expected_path.read_text().rstrip("\n")
    assert actual == expected, (
        f"SQL DDL golden mismatch for '{name}'.\n"
        f"--- expected ---\n{expected}\n"
        f"--- actual ---\n{actual}"
    )


# --- Ingest SQL golden tests ---

ingest_sql_cases = _discover_cases("ingest_sql", "sql")


@pytest.mark.parametrize(
    "name,input_path,expected_path",
    ingest_sql_cases,
    ids=[c[0] for c in ingest_sql_cases],
)
def test_ingest_sql_golden(name: str, input_path: Path, expected_path: Path) -> None:
    """Verify raw->ingest SQL artifact matches golden file."""
    umf_data = yaml.safe_load(input_path.read_text())
    actual = generate_ingest_sql(umf_data)
    expected = expected_path.read_text().rstrip("\n")
    assert actual == expected, (
        f"Ingest SQL golden mismatch for '{name}'.\n"
        f"--- expected ---\n{expected}\n"
        f"--- actual ---\n{actual}"
    )


# --- PySpark schema golden tests ---

pyspark_cases = _discover_cases("pyspark_schema", "py")


@pytest.mark.parametrize(
    "name,input_path,expected_path",
    pyspark_cases,
    ids=[c[0] for c in pyspark_cases],
)
def test_pyspark_schema_golden(
    name: str, input_path: Path, expected_path: Path
) -> None:
    """Verify PySpark schema output matches golden file."""
    umf_data = yaml.safe_load(input_path.read_text())
    actual = generate_pyspark_schema(umf_data)
    expected = expected_path.read_text().rstrip("\n")
    assert actual == expected, (
        f"PySpark schema golden mismatch for '{name}'.\n"
        f"--- expected ---\n{expected}\n"
        f"--- actual ---\n{actual}"
    )


# --- JSON Schema golden tests ---

json_schema_cases = _discover_cases("json_schema", "json")


@pytest.mark.parametrize(
    "name,input_path,expected_path",
    json_schema_cases,
    ids=[c[0] for c in json_schema_cases],
)
def test_json_schema_golden(name: str, input_path: Path, expected_path: Path) -> None:
    """Verify JSON Schema output matches golden file."""
    umf_data = yaml.safe_load(input_path.read_text())
    actual = generate_json_schema(umf_data)
    expected = json.loads(expected_path.read_text())
    assert actual == expected, (
        f"JSON Schema golden mismatch for '{name}'.\n"
        f"--- expected ---\n{json.dumps(expected, indent=2)}\n"
        f"--- actual ---\n{json.dumps(actual, indent=2)}"
    )
