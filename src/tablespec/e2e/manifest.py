"""On-disk artifact layout + the :class:`CompiledArtifacts` manifest.

The e2e bootstrap COMPILES a tablespec (UMF) set into runtime artifacts and the
runtime BACKBONE then consumes those COMPILED artifacts -- never the UMF directly.
This module pins the exact directory layout + filenames every compile seam writes
to, and the manifest dataclass that enumerates every persisted path so the
backbone (and the asserted e2e tests) can locate artifacts without re-deriving
names.

There is intentionally NO single ``tablespec generate`` entry point that produces
all of these (the CLI ``generate`` only emits sql/pyspark/json/ingest). The
COMPILE ORCHESTRATOR (:mod:`tablespec.e2e.compile`) calls each seam explicitly and
persists its output here.

Directory layout (rooted at ``<out_dir>/``), per the corrected plan
================================================================================

    <out_dir>/
      manifest.json                         # serialized CompiledArtifacts (paths)
      umf/
        <table>.umf.yaml                    # the (Path A inferred / Path B loaded)
                                            #   UMF snapshot the compile ran against
      ingest/
        <table>.ingest.sql                  # generate_ingest_sql: raw DDL + typed
                                            #   DDL + raw->ingested transform
      schemas/
        <table>.ddl.sql                     # generate_sql_ddl
        <table>.schema.py                   # generate_pyspark_schema (StructType src)
        <table>.schema.json                 # generate_json_schema
      validation/
        <table>.suite.json                  # COMPILED baseline suite: the full
                                            #   expectation list (raw + ingested
                                            #   stages co-mingled, classified at
                                            #   execute time by execute_staged)
      dbt_ingest/
        <table>/                            # single-table ingest dbt project
          dbt_project.yml, profiles.yml, models/..., (whole tree)
      dbt_gold/                             # multi-table GOLD dbt DAG project
        dbt_project.yml, profiles.yml, models/..., (whole tree)
      ldp/                                  # Lakeflow Declarative Pipelines project
        raw/raw_<t>.sql, ingested/ingested_<t>.sql, gold/gold_<t>.sql
      gold_plan/
        <target>.plan.sql                   # generate_sql_plan: SINGLE-target gold
                                            #   plan (NOT the dbt dag project)

Notes
-----
* The dbt/ldp seams already accept ``out_dir`` and write their own trees; the
  manifest records the project ROOT directory for each, plus a few load-bearing
  files inside it that the backbone needs by exact path (e.g. ``dbt_project.yml``).
* ``schemas/<table>.schema.py`` holds the PySpark ``StructType`` *source string*
  returned by :func:`generate_pyspark_schema` (it is Python source, not a schema
  JSON).
* Every path in the manifest is ABSOLUTE once :meth:`CompiledArtifacts.resolve`
  has been called against the chosen ``out_dir`` (the dataclass stores paths
  relative to ``root`` and exposes absolute accessors).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# --- pinned layout constants (single source of truth for filenames) -----------

MANIFEST_FILENAME = "manifest.json"

UMF_DIR = "umf"
INGEST_DIR = "ingest"
SCHEMAS_DIR = "schemas"
VALIDATION_DIR = "validation"
DBT_INGEST_DIR = "dbt_ingest"
DBT_GOLD_DIR = "dbt_gold"
LDP_DIR = "ldp"
GOLD_PLAN_DIR = "gold_plan"


def umf_snapshot_path(root: Path, table: str) -> Path:
    """Absolute path of the compiled UMF snapshot for *table*."""
    return root / UMF_DIR / f"{table}.umf.yaml"


def ingest_sql_path(root: Path, table: str) -> Path:
    """Absolute path of the ``generate_ingest_sql`` artifact for *table*."""
    return root / INGEST_DIR / f"{table}.ingest.sql"


def ddl_path(root: Path, table: str) -> Path:
    """Absolute path of the ``generate_sql_ddl`` artifact for *table*."""
    return root / SCHEMAS_DIR / f"{table}.ddl.sql"


def pyspark_schema_path(root: Path, table: str) -> Path:
    """Absolute path of the ``generate_pyspark_schema`` source for *table*."""
    return root / SCHEMAS_DIR / f"{table}.schema.py"


def json_schema_path(root: Path, table: str) -> Path:
    """Absolute path of the ``generate_json_schema`` artifact for *table*."""
    return root / SCHEMAS_DIR / f"{table}.schema.json"


def suite_path(root: Path, table: str) -> Path:
    """Absolute path of the COMPILED baseline validation suite for *table*."""
    return root / VALIDATION_DIR / f"{table}.suite.json"


def dbt_ingest_project_dir(root: Path, table: str) -> Path:
    """Absolute root dir of the single-table ingest dbt project for *table*."""
    return root / DBT_INGEST_DIR / table


def dbt_gold_project_dir(root: Path) -> Path:
    """Absolute root dir of the multi-table GOLD dbt DAG project."""
    return root / DBT_GOLD_DIR


def ldp_project_dir(root: Path) -> Path:
    """Absolute root dir of the LDP project."""
    return root / LDP_DIR


def gold_plan_path(root: Path, target: str) -> Path:
    """Absolute path of the SINGLE-target gold ``generate_sql_plan`` artifact."""
    return root / GOLD_PLAN_DIR / f"{target}.plan.sql"


# --- per-table artifact bundle ------------------------------------------------


@dataclass(frozen=True)
class TableArtifacts:
    """Compiled artifacts produced for a single table.

    Every field is an ABSOLUTE path to a persisted file (or, for ``dbt_ingest``,
    a project ROOT directory). ``None`` means that seam was not run for this table
    (e.g. ``gold_plan`` is only emitted for gold-target tables).
    """

    table_name: str
    umf_snapshot: Path
    ingest_sql: Path
    ddl_sql: Path
    pyspark_schema: Path
    json_schema: Path
    suite_json: Path
    dbt_ingest_project: Path | None = None
    gold_plan_sql: Path | None = None


# --- whole-compile manifest ---------------------------------------------------


@dataclass(frozen=True)
class CompiledArtifacts:
    """Manifest enumerating every artifact a compile run persisted.

    This is the contract between the COMPILE ORCHESTRATOR (writer) and the runtime
    BACKBONE / e2e assertions (reader). It is serialized to ``<root>/manifest.json``
    so a backbone run can be driven purely from disk.

    Attributes:
        root: absolute compile output directory (all other paths live under it).
        source: ``"tables"`` (Path A: inferred from ``spark.table``) or ``"specs"``
            (Path B: loaded from UMF YAML) -- records which entry point produced the
            UMF the compile ran against.
        profile_enriched: True iff Path A additionally ran ``NativeSparkProfiler``
            + ``ProfileToGxMapper`` so the compiled suites carry profile-derived
            expectations (False = schema-only inference).
        tables: per-table artifact bundles, keyed by table name (insertion order
            preserved for deterministic iteration).
        dbt_gold_project: absolute root dir of the multi-table GOLD dbt DAG project
            (one per compile, spanning ``tables``), or ``None`` if not compiled.
        ldp_project: absolute root dir of the LDP project (one per compile), or
            ``None`` if not compiled.
    """

    root: Path
    source: str
    profile_enriched: bool
    tables: dict[str, TableArtifacts] = field(default_factory=dict)
    dbt_gold_project: Path | None = None
    ldp_project: Path | None = None

    @property
    def manifest_path(self) -> Path:
        """Absolute path of the serialized manifest file."""
        return self.root / MANIFEST_FILENAME

    def table(self, name: str) -> TableArtifacts:
        """Return the artifact bundle for *name* (KeyError if absent)."""
        raise NotImplementedError

    def all_ingest_sql(self) -> list[Path]:
        """Every per-table ingest SQL artifact, in table order."""
        raise NotImplementedError

    def all_suites(self) -> list[Path]:
        """Every per-table compiled validation suite, in table order."""
        raise NotImplementedError

    def to_json(self) -> str:
        """Serialize this manifest to a JSON string (paths relative to ``root``)."""
        raise NotImplementedError

    def write(self) -> Path:
        """Persist this manifest to ``manifest_path`` and return that path."""
        raise NotImplementedError

    @classmethod
    def load(cls, root: Path) -> CompiledArtifacts:
        """Load a manifest previously written under *root* (re-absolutizing paths)."""
        raise NotImplementedError
