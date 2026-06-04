"""The dbt implementation package -- all dbt-specific generation lives here.

Encapsulation contract:

  * The CORE (``tablespec.core`` + ``build_ingest_select`` + ``SQLPlanGenerator``)
    contains NO dbt logic and never imports ``tablespec.dbt``.
  * Both the direct-artifact path and this dbt path depend only on the shared
    core seam (``TableRenderer`` + the logical-plan IR); they never import each
    other.

This package only *generates* dbt project text (pure Python, no dbt dependency).
Actually *running* the generated project needs the ``[dbt]`` extra (dbt-core +
dbt-duckdb), which is a runtime concern, not an import-time one -- so importing
this package never requires dbt to be installed.
"""

from __future__ import annotations

from tablespec.dbt.materialization import Materialization, MaterializationPolicy
from tablespec.dbt.project import DbtProjectError, generate_dbt_dag_project
from tablespec.dbt.registry import NodeRegistry, ResolvedNode
from tablespec.dbt.renderer import DbtRefRenderer, UnknownRelationError
from tablespec.dbt.routing import RoutingPolicy
from tablespec.dbt.single_table import generate_dbt_project

__all__ = [
    "DbtProjectError",
    "DbtRefRenderer",
    "Materialization",
    "MaterializationPolicy",
    "NodeRegistry",
    "ResolvedNode",
    "RoutingPolicy",
    "UnknownRelationError",
    "generate_dbt_dag_project",
    "generate_dbt_project",
]
