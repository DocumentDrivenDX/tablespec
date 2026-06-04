"""Backward-compatible shim for the single-table dbt project generator.

The implementation now lives in :mod:`tablespec.dbt.single_table` (all
dbt-specific code is encapsulated under ``tablespec.dbt``). This module preserves
the historical import path ``tablespec.schemas.dbt_generator.generate_dbt_project``
used by existing golden tests and consumers.
"""

from __future__ import annotations

from tablespec.dbt.single_table import generate_dbt_project

__all__ = ["generate_dbt_project"]
