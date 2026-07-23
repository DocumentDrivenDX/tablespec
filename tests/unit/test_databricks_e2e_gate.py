"""Fail-closed opt-in gate for the real Databricks e2e tier."""

from __future__ import annotations

import os

from tablespec.e2e.gating import DATABRICKS_E2E_REQUIRED_ENV, databricks_e2e_availability


def test_databricks_e2e_gate_skips_without_host(monkeypatch) -> None:
    monkeypatch.delenv("DATABRICKS_HOST", raising=False)
    reason = databricks_e2e_availability()
    assert reason is not None
    assert "DATABRICKS_HOST not set" in reason
    assert "opt-in" in reason


def test_databricks_e2e_gate_partial_config(monkeypatch) -> None:
    monkeypatch.setenv("DATABRICKS_HOST", "https://example.cloud.databricks.com")
    monkeypatch.delenv("DATABRICKS_HTTP_PATH", raising=False)
    monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
    reason = databricks_e2e_availability()
    assert reason is not None
    assert "partially configured" in reason
    assert "DATABRICKS_HTTP_PATH" in reason or "DATABRICKS_TOKEN" in reason


def test_databricks_e2e_required_env_is_documented() -> None:
    assert "DATABRICKS_HOST" in DATABRICKS_E2E_REQUIRED_ENV
    assert "DATABRICKS_TOKEN" in DATABRICKS_E2E_REQUIRED_ENV
    assert len(DATABRICKS_E2E_REQUIRED_ENV) >= 3
