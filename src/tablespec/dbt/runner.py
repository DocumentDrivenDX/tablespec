"""Opt-in dbt execution: emit a project, then run it with dbt-duckdb (ADR-008 §4.6).

:class:`DbtRunner` is the runnable *product* target for the dbt backend. It pairs
the import-safe emitter seam (:func:`tablespec.dbt.emitter.get_emitter`) with a real
``dbt build`` invocation against the emitted project:

  1. ``get_emitter('dbt').emit(umfs, out_dir)`` writes a runnable project.
  2. :meth:`DbtRunner.build` invokes ``dbt build`` (dbt-duckdb) against it, with the
     DuckDB database pinned under the project dir via ``DBT_DUCKDB_PATH`` so the run
     is fully isolated to *out_dir*.
  3. The :class:`DbtRunResult` reports success/failure (the dbt exit code) plus
     captured stdout/stderr for diagnostics.

dbt is a test/dev-time dependency, never a tablespec runtime import: this module
lazy-imports the dbt CLI only inside :meth:`build`, so importing
``tablespec.dbt.runner`` (and constructing a runner / emitting a project) works with
no dbt installed -- only an actual ``build`` call requires the dbt stack.

Scope (ADR-008 / phase-4 eval): the runnable target is **duckdb only**. The
spark/databricks dialects remain compile-only / conformance-lane concerns.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from tablespec.dbt.emitter import EmittedProject, get_emitter
from tablespec.models.umf import UMF

# The DuckDB database file the emitted profiles.yml resolves via env_var; pinning it
# under the project dir keeps every run isolated to out_dir.
_DUCKDB_DB_NAME = "tablespec.duckdb"
_DUCKDB_PATH_ENV = "DBT_DUCKDB_PATH"


class DbtRunnerError(RuntimeError):
    """Raised when the dbt stack cannot be located to run the emitted project."""


@dataclass(frozen=True)
class DbtRunResult:
    """The outcome of a ``dbt`` invocation.

    Attributes:
        success: True iff the dbt process exited 0.
        returncode: the dbt process exit code.
        command: the argv list that was run.
        stdout: captured standard output.
        stderr: captured standard error.
        project_dir: the dbt project the command ran against.
        duckdb_path: the DuckDB database file the run targeted.
    """

    success: bool
    returncode: int
    command: list[str]
    stdout: str
    stderr: str
    project_dir: Path
    duckdb_path: Path


def _dbt_argv() -> list[str]:
    """Return the argv prefix that invokes the dbt CLI.

    Uses ``<python> -m dbt.cli.main`` (works whenever ``dbt-core`` is installed for
    the current interpreter, with no reliance on a ``dbt`` script being on PATH).
    Availability is probed with :func:`importlib.util.find_spec` -- deliberately
    NOT a static ``import dbt`` -- so this module never imports the external ``dbt``
    package (the encapsulation rule: ``src/`` must stay import-safe on a base
    install, dbt being a dev/test-only dependency). Raises :class:`DbtRunnerError`
    when the dbt stack is not installed.
    """
    spec = None
    try:
        spec = importlib.util.find_spec("dbt.cli.main")
    except ModuleNotFoundError:
        spec = None
    if spec is None:  # pragma: no cover - exercised via importorskip in tests
        msg = (
            "dbt-core is not installed; install the dev/test stack "
            "(dbt-core + dbt-duckdb) to run an emitted dbt project."
        )
        raise DbtRunnerError(msg)
    return [sys.executable, "-m", "dbt.cli.main"]


class DbtRunner:
    """Emit a dbt project from UMF(s) and run it with dbt-duckdb."""

    def __init__(self) -> None:
        self._emitter = get_emitter("dbt")

    def emit(
        self,
        umfs: UMF | list[UMF],
        out_dir: str | Path,
        *,
        project_name: str | None = None,
        dialect: str = "duckdb",
    ) -> EmittedProject:
        """Emit a runnable dbt project for *umfs* under *out_dir* (no dbt needed)."""
        umf_list = [umfs] if isinstance(umfs, UMF) else list(umfs)
        return self._emitter.emit(
            umf_list, out_dir, project_name=project_name, dialect=dialect
        )

    def invoke(
        self,
        project: EmittedProject,
        *command: str,
        duckdb_path: str | Path | None = None,
    ) -> DbtRunResult:
        """Invoke ``dbt <command>`` against an already-emitted *project*.

        The DuckDB database file (``DBT_DUCKDB_PATH``) defaults to
        ``<project_dir>/tablespec.duckdb`` so the run is isolated to the project dir.
        Lazy-imports the dbt CLI; raises :class:`DbtRunnerError` if dbt is absent.
        """
        argv = _dbt_argv()
        project_dir = project.project_dir
        db = (
            Path(duckdb_path)
            if duckdb_path is not None
            else project_dir / _DUCKDB_DB_NAME
        )

        env = dict(os.environ, **{_DUCKDB_PATH_ENV: str(db)})
        cmd = [
            *argv,
            *command,
            "--profiles-dir",
            str(project_dir),
            "--project-dir",
            str(project_dir),
        ]
        proc = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return DbtRunResult(
            success=proc.returncode == 0,
            returncode=proc.returncode,
            command=cmd,
            stdout=proc.stdout,
            stderr=proc.stderr,
            project_dir=project_dir,
            duckdb_path=db,
        )

    def build(
        self,
        project: EmittedProject,
        *,
        duckdb_path: str | Path | None = None,
    ) -> DbtRunResult:
        """Run ``dbt build`` against an emitted *project* (the default run target).

        ``dbt build`` runs models AND their data tests, so a green result means the
        models materialized and every emitted generic/contract test passed.
        """
        return self.invoke(project, "build", duckdb_path=duckdb_path)


__all__ = [
    "DbtRunResult",
    "DbtRunner",
    "DbtRunnerError",
]
