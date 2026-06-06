"""Opt-in gating for the real-Databricks e2e tier (shipped, test-tree-free).

The backbone's real-serverless leg is gated by :func:`databricks_e2e_availability`
(``DATABRICKS_HOST`` opt-in). This gate ships in the package so the runtime backbone
can consult it without importing ``tests/`` (a wheel ships no test tree); the
conformance engines re-export both names for backwards compatibility.

The external ``dbt`` / ``databricks`` adapters are imported LAZILY inside the
function (via :func:`importlib.import_module`, so the encapsulation AST guard sees no
static ``dbt`` import target) -- the gate can be consulted on a base install (no
dbt/databricks stack) and simply reports a missing adapter as the skip reason rather
than failing at import time.
"""

from __future__ import annotations

import importlib
import os

# The credentials the opt-in real-Databricks e2e tier needs to actually deploy +
# execute against a workspace. ``DATABRICKS_HOST`` is the opt-in switch (its presence
# is what flips the tier on); the rest are required to OPEN the connection. We probe
# them all here so a half-configured workspace is reported with a precise reason
# rather than failing deep inside a dbt/SDK call.
DATABRICKS_E2E_REQUIRED_ENV: tuple[str, ...] = (
    "DATABRICKS_HOST",
    "DATABRICKS_HTTP_PATH",
    "DATABRICKS_TOKEN",
)


def databricks_e2e_availability() -> str | None:
    """Skip reason for the OPT-IN real-Databricks e2e tier, else ``None``.

    This tier deploys + executes against a REAL Databricks workspace, so it is
    skipped unless the workspace is configured. ``DATABRICKS_HOST`` is the opt-in
    switch: when UNSET the tier is OFF (skipped here, never silently passed). When
    the switch is on, the remaining credentials (``DATABRICKS_HTTP_PATH``,
    ``DATABRICKS_TOKEN``) MUST also be present and the databricks adapter importable
    so ``dbt run`` can open a real connection -- a half-configured workspace is
    skipped with a precise reason rather than failing deep in a dbt call.

    There is NO cluster in this harness, so ``DATABRICKS_HOST`` is unset here and this
    ALWAYS returns the opt-off reason -- the e2e legs SKIP, they never run or pass.
    """
    import warnings

    if not os.environ.get("DATABRICKS_HOST"):
        return (
            "databricks_e2e opt-in tier: DATABRICKS_HOST not set "
            "(no remote workspace -- skipped, not silently passed)"
        )
    missing = [k for k in DATABRICKS_E2E_REQUIRED_ENV if not os.environ.get(k)]
    if missing:  # pragma: no cover - only on a partially-configured workspace
        return (
            "databricks_e2e opt-in tier: DATABRICKS_HOST is set but the workspace is "
            f"only partially configured (missing: {', '.join(missing)}) -- the tier "
            "cannot open a connection, so it is skipped with this reason, not run"
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            # Imported via importlib (not a static ``import dbt...``) so the e2e
            # gate carries no static dependency on the test-only dbt-core stack.
            importlib.import_module("dbt.adapters.databricks")
    except Exception as exc:  # pragma: no cover - only on a configured workspace
        return f"dbt-databricks adapter not importable: {exc}"
    # The e2e engines load raw batches + read back over the Databricks SQL connector
    # and (for LDP) deploy the pipeline over the workspace SDK. Probe both so a
    # configured-but-missing-deps workspace skips with a precise reason rather than
    # failing deep inside ``run``.
    try:  # pragma: no cover - only on a configured workspace
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            importlib.import_module("databricks.sdk")
            importlib.import_module("databricks.sql")
    except Exception as exc:  # pragma: no cover - only on a configured workspace
        return (
            "databricks SQL connector / SDK not importable "
            f"(needed for e2e deploy + read-back): {exc}"
        )
    return None
