"""JDBC source kind compiles first-class (no live DB required)."""

from __future__ import annotations

from pathlib import Path

from tablespec.e2e.compile import compile_umfs
from tablespec.models.umf import UMF


def _jdbc_umf() -> UMF:
    return UMF.model_validate(
        {
            "version": "1.0",
            "table_name": "customers",
            "source": {
                "kind": "jdbc",
                "url": "jdbc:sqlserver://localhost:1433;databaseName=Northwind",
                "dbtable": "dbo.customers",
                "password_secret_ref": "secrets/jdbc-password",
            },
            "columns": [
                {
                    "name": "customer_id",
                    "data_type": "CHAR",
                    "max_length": 5,
                    "nullable": {"default": False},
                },
                {
                    "name": "company_name",
                    "data_type": "VARCHAR",
                    "max_length": 40,
                    "nullable": {"default": True},
                },
            ],
            "primary_key": ["customer_id"],
        }
    )


def test_jdbc_source_compiles_artifact_tree(tmp_path: Path) -> None:
    arts = compile_umfs([_jdbc_umf()], tmp_path, source="specs", dialect="spark")
    ta = arts.table("customers")
    assert ta.ingest_sql.exists()
    assert ta.suite_json.exists()
    assert ta.umf_snapshot.exists()
    snap = ta.umf_snapshot.read_text(encoding="utf-8")
    assert "kind: jdbc" in snap or "kind:jdbc" in snap.replace(" ", "")
    assert "password_secret_ref" in snap
    assert "plaintext" not in snap.lower()
    # Ingest SQL is generated (typed path); no embedded password.
    sql = ta.ingest_sql.read_text(encoding="utf-8")
    assert "ingested_customers" in sql or "raw_customers" in sql
    assert "secrets/jdbc-password" not in sql  # secret stays in UMF/source only


def test_jdbc_plaintext_password_rejected() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        UMF.model_validate(
            {
                "version": "1.0",
                "table_name": "t",
                "source": {
                    "kind": "jdbc",
                    "url": "jdbc:x",
                    "dbtable": "dbo.t",
                    "password": "s3cret",  # forbidden
                },
                "columns": [
                    {
                        "name": "id",
                        "data_type": "INTEGER",
                        "nullable": {"default": False},
                    }
                ],
            }
        )
