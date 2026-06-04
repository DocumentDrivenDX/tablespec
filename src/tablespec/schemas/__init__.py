"""Schema generation utilities for UMF metadata.

This package is part of the dbt-free CORE. It deliberately does NOT import
``tablespec.dbt`` (the single-table ``generate_dbt_project`` lives there now and
is re-exported at the top level), so importing core schema generators never pulls
in the dbt implementation package. See ``tests/test_core_encapsulation.py``.
"""

from .generators import (
    generate_json_schema,
    generate_pyspark_schema,
    generate_sql_ddl,
)
from .ingest_generator import build_ingest_select, generate_ingest_sql
from .relationship_resolver import (
    JoinInfo,
    PivotSpec,
    RelationshipResolver,
    ResolvedPlan,
)
from .sql_generator import SQLPlanGenerator, generate_sql_plan

__all__ = [
    "build_ingest_select",
    "generate_ingest_sql",
    "generate_json_schema",
    "generate_pyspark_schema",
    "generate_sql_ddl",
    "generate_sql_plan",
    "JoinInfo",
    "PivotSpec",
    "RelationshipResolver",
    "ResolvedPlan",
    "SQLPlanGenerator",
]
