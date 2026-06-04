"""The LDP implementation package -- a PROTOTYPE sibling of the dbt emitter.

This package is EXPLORATORY and clearly EXPERIMENTAL. It generates a Lakeflow
Declarative Pipelines (LDP, the rebrand of Delta Live Tables) project from a UMF
set, parallel to ``tablespec.dbt``, to prove the shared core is target-agnostic.

Encapsulation contract (enforced by ``tests/test_core_encapsulation.py``):

  * The CORE (``tablespec.core`` -- the logical-plan IR / ``NodeRegistry`` / the
    ``TableRenderer`` Protocol -- plus ``build_ingest_select`` and
    ``cast_column_sql``) contains NO LDP logic and never imports ``tablespec.ldp``.
  * ``tablespec.ldp`` is fed ONLY by that core seam; it never imports
    ``tablespec.dbt``, and ``tablespec.dbt`` never imports ``tablespec.ldp``. The
    two backends are independent siblings on the shared core.

This package only *generates* LDP SQL text (pure Python). LDP runs ONLY on
Databricks; there is no Databricks runtime here, so the generated SQL is NOT
executed end-to-end -- see the module docstring of :mod:`tablespec.ldp.project`
for the honest list of what is and is not tested.
"""

from __future__ import annotations

from tablespec.ldp.expectations import (
    LdpExpectation,
    OnViolation,
    derive_comments,
    derive_expectations,
)
from tablespec.ldp.project import LdpProjectError, generate_ldp_project
from tablespec.ldp.renderer import LdpRefRenderer, UnknownDatasetError

__all__ = [
    "LdpExpectation",
    "LdpProjectError",
    "LdpRefRenderer",
    "OnViolation",
    "UnknownDatasetError",
    "derive_comments",
    "derive_expectations",
    "generate_ldp_project",
]
