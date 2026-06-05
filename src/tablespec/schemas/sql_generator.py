"""SQL plan generation from UMF metadata and relationships.

Generates pure SQL execution plans from UMF metadata for building derived tables
through sequential joins. Creates transparent, verifiable SQL that can be executed
against any SQL engine supporting temporary views.

This module is engine-agnostic: it emits standard SQL with temporary views for
transparency. The generated SQL uses a sequential join strategy where each step
builds on the previous view.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Callable, Literal

from tablespec.core.relations import LiteralRenderer, TableRenderer

from .relationship_resolver import RelationshipResolver

if TYPE_CHECKING:
    from tablespec.models.umf import UMF

logger = logging.getLogger(__name__)

_SQL_KEYWORDS = {
    "CASE",
    "WHEN",
    "THEN",
    "ELSE",
    "END",
    "AND",
    "OR",
    "NOT",
    "IN",
    "IS",
    "NULL",
    "TRUE",
    "FALSE",
    "LIKE",
    "BETWEEN",
    "AS",
    "FROM",
    "SELECT",
    "WHERE",
    "GROUP",
    "BY",
    "ORDER",
    "HAVING",
    "LIMIT",
    "COALESCE",
    "NULLIF",
    "CAST",
    "TRIM",
    "UPPER",
    "LOWER",
    "LENGTH",
    "SUBSTRING",
    "CONCAT",
    "REPLACE",
    "DATE",
    "TIMESTAMP",
    "INTERVAL",
    "COUNT",
    "SUM",
    "AVG",
    "MIN",
    "MAX",
    "ROW_NUMBER",
    "RANK",
    "PARTITION",
    "OVER",
    "ASC",
    "DESC",
    "DISTINCT",
    "ALL",
    "ANY",
    "EXISTS",
    "UNION",
    "INTERSECT",
    "EXCEPT",
    "JOIN",
    "LEFT",
    "RIGHT",
    "INNER",
    "OUTER",
    "FULL",
    "CROSS",
    "ON",
    "USING",
    "CONCAT_WS",
}

_IDENTIFIER_RE = re.compile(r"(?<![\w\.])([A-Za-z_][A-Za-z0-9_]*)")

_SPARK_TYPE_MAP = {
    "TEXT": "STRING",
    "CHAR": "STRING",
    "STRING": "STRING",
    "STRINGTYPE": "STRING",
    "INTEGER": "INT",
    "INTEGERTYPE": "INT",
    "INT": "INT",
    "BIGINT": "INT",
    "SMALLINT": "INT",
    "TINYINT": "INT",
    "DECIMAL": "DECIMAL(18,2)",
    "FLOAT": "FLOAT",
    "DOUBLE": "DOUBLE",
    "DATE": "DATE",
    "DATETYPE": "DATE",
    "DATETIME": "TIMESTAMP",
    "TIMESTAMP": "TIMESTAMP",
    "BOOLEAN": "BOOLEAN",
    "BOOLEANTYPE": "BOOLEAN",
}

_AGGREGATE_FUNCTIONS = [
    "COUNT(",
    "MIN(",
    "MAX_BY(",
    "MIN_BY(",
    "MAX(",
    "SUM(",
    "AVG(",
]


def _parse_table_ref(name: str) -> tuple[str | None, str]:
    """Split a possibly-qualified table name into (namespace, bare_name).

    Args:
        name: Table name, optionally qualified as ``namespace.table``.

    Returns:
        Tuple of (namespace, bare_name).  ``namespace`` is ``None`` when
        *name* contains no dot.

    Examples:
        >>> _parse_table_ref("my_table")
        (None, 'my_table')
        >>> _parse_table_ref("other_ns.my_table")
        ('other_ns', 'my_table')

    """
    if "." in name:
        parts = name.split(".", maxsplit=1)
        return parts[0], parts[1]
    return None, name


class SQLPlanGenerator:
    """Generate SQL execution plans from UMF metadata and relationships.

    Pure-data implementation: accepts UMF Pydantic models, performs no file I/O,
    and has no dependency on any specific pipeline framework.

    Args:
        template_vars: Optional template variables for substitution in SQL
            expressions.  ``{{var_name}}`` patterns in derivation expressions
            are replaced with the corresponding value.
        table_resolver: Optional callable that maps a table name to a resolved
            name (e.g. catalog-qualified path).  When ``None``, table names are
            used as-is.  Mutually exclusive with *table_renderer* (it is a
            shorthand for ``LiteralRenderer(resolver=table_resolver)``).
        table_renderer: Optional :class:`~tablespec.core.relations.TableRenderer`.
            This is the single relation-rendering seam: every site that inlines a
            relation name routes it through ``self._renderer.render(name)``.  When
            ``None``, a :class:`LiteralRenderer` wrapping *table_resolver* is used,
            preserving the historical inline-the-name behaviour byte-for-byte.
            Inject a ``DbtRefRenderer`` here to emit ``{{ ref() }}`` instead.

    """

    def __init__(
        self,
        template_vars: dict[str, str] | None = None,
        table_resolver: Callable[[str], str] | None = None,
        *,
        table_renderer: TableRenderer | None = None,
    ) -> None:
        if table_renderer is not None and table_resolver is not None:
            msg = "Pass either table_resolver or table_renderer, not both"
            raise ValueError(msg)
        self.template_vars: dict[str, str] = template_vars or {}
        self.table_resolver = table_resolver
        # The one relation-rendering seam. Defaults to the historical literal
        # behaviour so existing artifacts/goldens are unchanged.
        self._renderer: TableRenderer = (
            table_renderer
            if table_renderer is not None
            else LiteralRenderer(resolver=table_resolver)
        )
        self.logger = logging.getLogger(self.__class__.__name__)

        # Instance state reset per ``generate_for_table`` call
        self._related_umfs: dict[str, UMF] = {}
        self._pre_aggregated_columns: dict[str, list[dict[str, str | bool]]] = {}
        self._agg_view_source_columns: dict[str, str] = {}
        self._required_columns: dict[str, set[str]] = {}
        self._accumulated_columns: dict[str, str] = {}
        self._join_sequence: list[dict[str, Any]] = []
        # Maps (source_table, target_column_name) -> the pivoted column alias the
        # pivot CTE actually emits (e.g. ("diagnosis", "diagnosis_1") ->
        # "diagnosis__diagnosis_1"). The final-assembly column mapping consults
        # this so a target column derived from a pivot source references the
        # pivoted output column rather than the raw source column.
        self._pivot_column_map: dict[tuple[str, str], str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_for_table(
        self,
        table_umf: UMF,
        related_umfs: dict[str, UMF],
        *,
        mode: Literal["views", "cte"] = "views",
    ) -> str:
        """Generate a complete SQL plan for a single target table.

        Args:
            table_umf: UMF metadata for the target table.
            related_umfs: Dict mapping table names to UMF models for all
                tables that participate in derivations (source tables).
            mode: Output format.  ``"views"`` (default) emits sequential
                ``CREATE OR REPLACE TEMPORARY VIEW`` statements.
                ``"cte"`` emits a single ``WITH ... SELECT`` statement
                using Common Table Expressions.

        Returns:
            Multi-statement SQL string (views mode) or a single CTE
            statement (cte mode).

        Raises:
            ValueError: If the table name cannot be determined.

        """
        table_name = table_umf.table_name
        if not table_name:
            msg = "table_name could not be determined from table_umf"
            raise ValueError(msg)
        sql = self._generate_table_sql(table_name, table_umf, related_umfs)
        if mode == "cte":
            return self._convert_views_to_cte(sql)
        return sql

    # ------------------------------------------------------------------
    # CTE conversion
    # ------------------------------------------------------------------

    _VIEW_PATTERN = re.compile(
        r"CREATE\s+OR\s+REPLACE\s+TEMPORARY\s+VIEW\s+(\S+)\s+AS\s*\n",
        re.IGNORECASE,
    )

    def _convert_views_to_cte(self, views_sql: str) -> str:
        """Post-process views-mode SQL into a single ``WITH ... SELECT`` statement.

        Each ``CREATE OR REPLACE TEMPORARY VIEW <name> AS`` block is
        converted into a CTE entry.  SQL comment blocks between statements
        are preserved inside the CTE body so traceability is maintained.
        """
        # Split on CREATE OR REPLACE TEMPORARY VIEW boundaries
        parts = self._VIEW_PATTERN.split(views_sql)
        # parts looks like: [preamble, name1, body1, name2, body2, ...]
        if len(parts) < 3:
            # No views found — return as-is
            return views_sql

        preamble = parts[0]
        cte_entries: list[str] = []
        last_name: str | None = None
        seen_names: set[str] = set()
        # A comment block trailing one view's statement is actually the NEXT
        # step's leading comment (views are joined with "\n\n"). Carry it forward
        # so traceability comments survive WITHOUT leaving a stray ';' mid-CTE.
        carried_comment = ""

        for i in range(1, len(parts), 2):
            name = parts[i]
            body = parts[i + 1] if i + 1 < len(parts) else ""

            select_body, trailing_comment = self._split_cte_body(body)
            if carried_comment:
                select_body = f"{carried_comment}\n{select_body}"
            carried_comment = trailing_comment

            # Avoid duplicate CTE names (diamond dependencies)
            if name in seen_names:
                continue
            seen_names.add(name)

            cte_entries.append(f"{name} AS (\n{select_body}\n)")
            last_name = name

        if not cte_entries or last_name is None:
            return views_sql

        cte_block = ",\n\n".join(cte_entries)
        result = f"{preamble.rstrip()}\nWITH\n{cte_block}\nSELECT * FROM {last_name};\n"
        return result

    @staticmethod
    def _split_cte_body(body: str) -> tuple[str, str]:
        """Split one view body into ``(select_body, trailing_comment)``.

        A views-mode body is a single ``CREATE OR REPLACE TEMPORARY VIEW ... AS``
        statement -- one SELECT terminated by ``;`` -- optionally followed by the
        *next* step's leading comment block (an artefact of joining views with
        ``"\\n\\n"``). For a valid CTE we keep the SELECT (without its terminating
        ``;``) and return the trailing comment separately so the caller can carry
        it forward as the next CTE's leading comment (preserving traceability
        without leaving a stray ``;`` mid-CTE).
        """
        text = body.strip()
        semi = text.rfind(";")
        if semi == -1:
            return text, ""
        tail = text[semi + 1 :].strip()
        # Only the LAST ';' followed solely by comments/blank is the terminator.
        if tail != "" and not all(
            line.strip() == "" or line.lstrip().startswith("--")
            for line in tail.splitlines()
        ):
            return text, ""
        return text[:semi].strip(), tail

    # ------------------------------------------------------------------
    # Internal orchestration
    # ------------------------------------------------------------------

    def _generate_table_sql(
        self, table_name: str, table_umf: UMF, related_umfs: dict[str, UMF]
    ) -> str:
        """Generate the complete SQL plan for *table_name*."""
        # Reset per-table state
        self._related_umfs = related_umfs
        self._pre_aggregated_columns = {}
        self._agg_view_source_columns = {}
        self._required_columns = self._build_required_columns_map(table_umf)
        self._accumulated_columns = {}
        self._pivot_column_map = {}

        sections: list[str] = []

        # Resolve relationships via the metadata-driven resolver
        resolver = RelationshipResolver(related_umfs)
        plan = resolver.resolve_plan(table_umf)

        join_sequence: list[dict[str, Any]] = plan.join_sequence
        base_table: str | None = plan.base_table
        base_table_strategy: str | None = plan.base_table_strategy
        union_sources: list[dict[str, Any]] | None = plan.union_sources

        self._join_sequence = join_sequence

        # Header
        if base_table_strategy == "union_sources":
            header_base = "member_universe (UNION of source tables)"
        elif base_table_strategy == "unpivot":
            header_base = f"{base_table} (UNPIVOT)"
        else:
            header_base = base_table or ""

        sections.append(
            self._generate_header(
                table_name, table_umf, header_base, len(join_sequence)
            )
        )

        # Base view
        if base_table_strategy == "unpivot" and base_table:
            sections.append(self._generate_unpivot_base_view(table_umf, base_table))
        elif base_table_strategy == "union_sources" and union_sources:
            sections.append(
                self._generate_member_universe_view(table_umf, union_sources)
            )
            agg_sections = self._generate_pre_aggregation_views(
                table_umf, union_sources
            )
            sections.extend(agg_sections)
        elif base_table:
            sections.append(self._generate_base_view(table_umf, base_table))
        else:
            self.logger.info(
                f"No base table for {table_name} - generating synthetic table from derivations"
            )

        # Sequential join steps
        current_view = "disposition_base"
        for step, join_info in enumerate(join_sequence, 1):
            join_sql = self._generate_join_step(step, join_info, current_view)
            sections.append(join_sql)
            current_view = f"disposition_step_{step}"

        # Pre-aggregation view join steps
        if self._pre_aggregated_columns:
            agg_views: dict[str, list[str]] = {}
            for col_name, agg_sources in sorted(self._pre_aggregated_columns.items()):
                for agg_info in agg_sources:
                    view_name = str(agg_info["agg_view_name"])
                    if view_name not in agg_views:
                        agg_views[view_name] = []
                    if col_name not in agg_views[view_name]:
                        agg_views[view_name].append(col_name)

            step = len(join_sequence)
            for agg_view_name, col_names in sorted(agg_views.items()):
                step += 1
                agg_join_sql = self._generate_agg_view_join(
                    step, agg_view_name, col_names, current_view, table_umf
                )
                sections.append(agg_join_sql)
                current_view = f"disposition_step_{step}"

        # Final assembly
        effective_base = (
            "member_universe" if base_table_strategy == "union_sources" else base_table
        )
        sections.append(
            self._generate_final_assembly(
                table_name, table_umf, current_view, effective_base
            )
        )

        return "\n\n".join(sections)

    # ------------------------------------------------------------------
    # Helpers: name resolution
    # ------------------------------------------------------------------

    def _resolve_table_name(self, table_name: str) -> str:
        """Render a relation name via the configured :class:`TableRenderer`.

        This is the single seam through which every external relation flows. The
        default :class:`LiteralRenderer` reproduces the historical behaviour
        (apply ``table_resolver`` if any, else identity); a ``DbtRefRenderer``
        turns the same call into a ``{{ ref() }}`` / ``{{ source() }}`` literal.
        """
        return self._renderer.render(table_name)

    @staticmethod
    def _sanitize_alias(name: str) -> str:
        """Replace dots with underscores for use in SQL identifiers."""
        return name.replace(".", "_")

    def _get_table_columns(self, table_name: str) -> list[str]:
        """Return column names for *table_name* from ``_related_umfs``."""
        # Try the name as-given first, then the bare name
        umf = self._related_umfs.get(table_name)
        if umf is None:
            _, bare = _parse_table_ref(table_name)
            umf = self._related_umfs.get(bare)
        if umf is None:
            self.logger.warning(f"Table {table_name} not found in related_umfs")
            return []
        return [col.name for col in umf.columns] if umf.columns else []

    # ------------------------------------------------------------------
    # Template variable substitution
    # ------------------------------------------------------------------

    def _substitute_template_vars(self, text: str) -> str:
        """Replace ``{{var}}`` patterns in *text* with values from ``template_vars``."""
        if not self.template_vars:
            return text
        result = text
        for var_name, var_value in self.template_vars.items():
            result = result.replace(f"{{{{{var_name}}}}}", var_value)
        return result

    # ------------------------------------------------------------------
    # Required-columns tracking
    # ------------------------------------------------------------------

    def _build_required_columns_map(self, table_umf: UMF) -> dict[str, set[str]]:
        """Map source table names to the set of their columns used by derivations."""
        required: dict[str, set[str]] = {}

        for col in table_umf.columns:
            if not col.derivation or not col.derivation.candidates:
                continue

            for cand in col.derivation.candidates:
                if not cand.table:
                    continue

                col_names: list[str] = []
                if cand.column:
                    col_names.append(cand.column)
                elif cand.expression:
                    col_names.extend(
                        self._extract_columns_from_expression(cand.expression)
                    )

                for col_name in col_names:
                    _, bare_name = _parse_table_ref(cand.table)
                    required.setdefault(bare_name, set()).add(col_name)
                    if cand.table != bare_name:
                        required.setdefault(cand.table, set()).add(col_name)

        return required

    def _extract_columns_from_expression(self, expression: str) -> list[str]:
        """Extract likely column references from a SQL expression."""
        pattern = r"\b([a-zA-Z][a-zA-Z0-9_]*)\b"
        matches = re.findall(pattern, expression)

        columns: list[str] = []
        for match in matches:
            if match.upper() in _SQL_KEYWORDS:
                continue
            if len(match) == 1:
                continue
            if match.isupper():
                continue
            if "__" in match:
                columns.append(match.split("__")[-1])
            else:
                columns.append(match)
        return columns

    def _get_required_columns_for_table(self, table_name: str) -> set[str] | None:
        """Return the set of required columns for *table_name*, or ``None`` if unfiltered."""
        if table_name in self._required_columns:
            return self._required_columns[table_name]
        _, bare = _parse_table_ref(table_name)
        if bare in self._required_columns:
            return self._required_columns[bare]
        return None

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _generate_header(
        self, table_name: str, table_umf: UMF, base_table: str, join_count: int
    ) -> str:
        """Generate a SQL file header comment block."""
        return f"""-- ============================================================================
-- SQL Execution Plan: {table_name}
-- ============================================================================
-- Purpose: Build {table_name} dataset through sequential joins
-- Base Table: {base_table} (hub table)
-- Total Joins: {join_count}
-- Strategy: Pure SQL with temporary views for transparency
-- ============================================================================"""

    # ------------------------------------------------------------------
    # Base view generation
    # ------------------------------------------------------------------

    def _generate_base_view(self, table_umf: UMF, base_table: str) -> str:
        """Generate the base view selecting required columns from *base_table*."""
        resolved_table = self._resolve_table_name(base_table)
        base_columns = self._get_table_columns(base_table)

        # Filter to derivation-required columns + join key + meta columns
        required_cols = self._get_required_columns_for_table(base_table)
        if required_cols:
            pk_col = table_umf.primary_key[0] if table_umf.primary_key else None
            selected_columns = [
                col
                for col in base_columns
                if col in required_cols or col == pk_col or col.startswith("meta_")
            ]
        else:
            selected_columns = base_columns

        for col in selected_columns:
            self._accumulated_columns[col] = "base"

        column_list = ",\n  ".join(selected_columns)

        return f"""-- ============================================================================
-- STEP 0: Create base view from {base_table}
-- ============================================================================
CREATE OR REPLACE TEMPORARY VIEW disposition_base AS
SELECT
  {column_list}
FROM {resolved_table};"""

    def _generate_unpivot_base_view(self, table_umf: UMF, base_table: str) -> str:
        """Generate the base view with UNPIVOT transformation."""
        resolved_table = self._resolve_table_name(base_table)
        metadata = table_umf.metadata
        if metadata is None:
            msg = "UNPIVOT strategy requires metadata to be set on the UMF"
            raise ValueError(msg)

        columns = metadata.unpivot_columns
        value_column = metadata.unpivot_value_column
        if not columns or not value_column:
            msg = (
                f"UNPIVOT strategy requires unpivot_columns and "
                f"unpivot_value_column in metadata. Got columns={columns}, "
                f"value_column={value_column}"
            )
            raise ValueError(msg)

        in_clause = ",\n    ".join(columns)

        # Track accumulated columns
        base_columns = self._get_table_columns(base_table)
        unpivot_source_cols = set(columns)
        for col in base_columns:
            if col not in unpivot_source_cols:
                self._accumulated_columns[col] = "base"
        self._accumulated_columns[value_column] = "base"
        self._accumulated_columns["source_column"] = "base"

        # Optional dedup with ROW_NUMBER
        dedup_strategy = metadata.dedup_strategy
        if dedup_strategy == "latest" and table_umf.primary_key:
            partition_cols = self._build_unpivot_dedup_partition(table_umf)
            cte_in_clause = ",\n      ".join(columns)
            return f"""-- ============================================================================
-- STEP 0: Create base view from {base_table} with UNPIVOT (dedup: latest per PK)
-- ============================================================================
CREATE OR REPLACE TEMPORARY VIEW disposition_base AS
WITH unpivoted AS (
  SELECT *
  FROM {resolved_table}
  UNPIVOT EXCLUDE NULLS (
    {value_column} FOR source_column IN (
      {cte_in_clause}
    )
  )
),
ranked AS (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY {partition_cols}
      ORDER BY meta_load_dt DESC
    ) AS rn
  FROM unpivoted
)
SELECT * EXCEPT (rn)
FROM ranked
WHERE rn = 1;"""

        return f"""-- ============================================================================
-- STEP 0: Create base view from {base_table} with UNPIVOT
-- ============================================================================
CREATE OR REPLACE TEMPORARY VIEW disposition_base AS
SELECT *
FROM {resolved_table}
UNPIVOT EXCLUDE NULLS (
  {value_column} FOR source_column IN (
    {in_clause}
  )
);"""

    def _build_unpivot_dedup_partition(self, table_umf: UMF) -> str:
        """Build PARTITION BY clause for UNPIVOT dedup using source column expressions."""
        pk_columns = table_umf.primary_key or []
        col_lookup = {col.name: col for col in table_umf.columns}

        partition_exprs: list[str] = []
        for pk_col in pk_columns:
            col_def = col_lookup.get(pk_col)
            if (
                not col_def
                or not col_def.derivation
                or not col_def.derivation.candidates
            ):
                partition_exprs.append(pk_col)
                continue

            candidate = col_def.derivation.candidates[0]
            if candidate.expression:
                partition_exprs.append(candidate.expression)
            elif candidate.column:
                partition_exprs.append(candidate.column)
            else:
                partition_exprs.append(pk_col)

        return ", ".join(partition_exprs)

    def _generate_member_universe_view(
        self, table_umf: UMF, union_sources: list[dict[str, Any]]
    ) -> str:
        """Generate the member universe base view from a UNION of source tables."""
        pk_col = table_umf.primary_key[0] if table_umf.primary_key else "id"

        union_parts: list[str] = []
        for source in union_sources:
            source_table = source["table"]
            join_col = source["join_column"]
            resolved = self._resolve_table_name(source_table)

            # Check for derived column expression
            derived_cols = self._get_derived_columns_for_source(source_table)
            if join_col in derived_cols:
                expr, _ = derived_cols[join_col]
                select_expr = f"({expr}) AS {pk_col}"
                key_ref = f"({expr})"
            else:
                select_expr = f"{join_col} AS {pk_col}"
                key_ref = join_col

            # The universe key becomes the target's primary key; never admit a
            # NULL key row (it would surface as a spurious NULL-PK member).
            union_parts.append(
                f"SELECT DISTINCT {select_expr} FROM {resolved} "
                f"WHERE {key_ref} IS NOT NULL"
            )

        union_sql = "\nUNION\n".join(union_parts)

        self._accumulated_columns[pk_col] = "base"

        return f"""-- ============================================================================
-- STEP 0: Create member_universe from UNION of {len(union_sources)} source tables
-- ============================================================================
CREATE OR REPLACE TEMPORARY VIEW member_universe AS
{union_sql};

-- Create base view from member_universe
CREATE OR REPLACE TEMPORARY VIEW disposition_base AS
SELECT {pk_col} FROM member_universe;"""

    # ------------------------------------------------------------------
    # Derived columns helpers
    # ------------------------------------------------------------------

    def _get_derived_columns_for_source(
        self, source_table: str
    ) -> dict[str, tuple[str, bool]]:
        """Get derived column definitions from a source table's UMF.

        Returns:
            Dict mapping column name to (SQL expression, needs_except).

        """
        derived_cols: dict[str, tuple[str, bool]] = {}
        umf = self._related_umfs.get(source_table)
        if umf is None:
            _, bare = _parse_table_ref(source_table)
            umf = self._related_umfs.get(bare)
        if umf is None or not umf.columns:
            return derived_cols

        for col in umf.columns:
            if not col.derivation or not col.derivation.candidates:
                continue
            for cand in col.derivation.candidates:
                if cand.expression and cand.table == source_table:
                    needs_except = col.source != "derived"
                    expr = self._substitute_template_vars(cand.expression)
                    derived_cols[col.name] = (expr, needs_except)
                    break

        return derived_cols

    def _get_derived_column_expression(
        self, table_umf: UMF, col_name: str
    ) -> str | None:
        """Get the derivation expression for a column in the target table."""
        if not table_umf.columns:
            return None

        for col in table_umf.columns:
            if col.name != col_name:
                continue
            if not col.derivation or not col.derivation.candidates:
                return None
            for cand in col.derivation.candidates:
                if cand.expression and (
                    cand.table
                    in (table_umf.table_name, "intermediate", "member_universe")
                ):
                    return self._substitute_template_vars(cand.expression)
        return None

    def _infer_join_column_from_umf(self, table_name: str) -> str | None:
        """Try to infer join column from UMF primary key or common patterns.

        Delegates to :func:`.relationship_resolver.infer_join_key`.
        """
        from .relationship_resolver import infer_join_key

        _, bare = _parse_table_ref(table_name)
        umf = self._related_umfs.get(table_name) or self._related_umfs.get(bare)
        if umf is None or not umf.columns:
            return None

        columns = [col.name for col in umf.columns]
        lookup_name = table_name if table_name in self._related_umfs else bare
        return infer_join_key(lookup_name, columns, {lookup_name: umf})

    # ------------------------------------------------------------------
    # Pre-aggregation views
    # ------------------------------------------------------------------

    def _generate_pre_aggregation_views(
        self, table_umf: UMF, union_sources: list[dict[str, Any]]
    ) -> list[str]:
        """Generate pre-aggregation views for columns with aggregate expressions."""
        agg_specs: dict[str, list[dict[str, Any]]] = {}

        for col in table_umf.columns:
            if not col.derivation or not col.derivation.candidates:
                continue
            for cand in col.derivation.candidates:
                if not cand.expression:
                    continue
                expr_upper = cand.expression.upper()
                agg_func = None
                if "COUNT(" in expr_upper:
                    agg_func = "COUNT"
                elif "MIN(" in expr_upper:
                    agg_func = "MIN"
                elif "MAX_BY(" in expr_upper:
                    agg_func = "MAX_BY"
                elif "MAX(" in expr_upper:
                    agg_func = "MAX"
                elif "SUM(" in expr_upper:
                    agg_func = "SUM"

                if agg_func and cand.table and cand.table != "intermediate":
                    _, source_table = _parse_table_ref(cand.table)
                    agg_specs.setdefault(source_table, []).append(
                        {
                            "col_name": col.name,
                            "function": agg_func,
                            "expression": cand.expression,
                            "source_column": cand.column or "*",
                            "join_via": cand.join_via,
                            "order_by": cand.order_by,
                            "row_filter": cand.row_filter,
                            "select_columns": cand.select_columns,
                        }
                    )

                    if col.name not in self._pre_aggregated_columns:
                        self._pre_aggregated_columns[col.name] = []
                    self._pre_aggregated_columns[col.name].append(
                        {
                            "source_table": source_table,
                            "agg_view_name": f"{source_table}_agg",
                        }
                    )

        if not agg_specs:
            return []

        sections: list[str] = []
        for source_table, specs in sorted(agg_specs.items()):
            # Find join column
            join_col = None
            source_col = None
            for source in union_sources:
                if source["table"] == source_table:
                    join_col = source["join_column"]
                    source_col = source.get("source_column")
                    break

            if not join_col:
                join_col = self._infer_join_column_from_umf(source_table)
            if not join_col:
                self.logger.warning(
                    f"Could not determine join column for {source_table} aggregation"
                )
                continue

            pk_col = table_umf.primary_key[0] if table_umf.primary_key else "id"
            resolved_table = self._resolve_table_name(source_table)
            derived_cols = self._get_derived_columns_for_source(source_table)

            # Separate window vs GROUP BY specs
            window_specs = [s for s in specs if s.get("order_by")]
            non_window_specs = [s for s in specs if not s.get("order_by")]

            if window_specs:
                # Group by row_filter
                filter_groups: dict[str, list[dict[str, Any]]] = {}
                for spec in window_specs:
                    filter_key = (spec.get("row_filter") or "").strip()
                    filter_groups.setdefault(filter_key, []).append(spec)

                for filter_idx, (_filter_key, filter_specs) in enumerate(
                    sorted(filter_groups.items())
                ):
                    view_suffix = f"_{filter_idx + 1}" if len(filter_groups) > 1 else ""
                    agg_view_name = f"{source_table}_agg{view_suffix}"

                    section = self._generate_window_aggregation_view(
                        source_table=source_table,
                        specs=filter_specs,
                        join_col=join_col,
                        pk_col=pk_col,
                        resolved_table=resolved_table,
                        derived_cols=derived_cols,
                        view_name_suffix=view_suffix,
                    )
                    if section:
                        sections.append(section)
                        if source_col:
                            self._agg_view_source_columns[agg_view_name] = source_col
                        for spec in filter_specs:
                            col_name = spec["col_name"]
                            if col_name in self._pre_aggregated_columns:
                                for entry in self._pre_aggregated_columns[col_name]:
                                    if entry["source_table"] == source_table:
                                        entry["agg_view_name"] = agg_view_name
                                        entry["is_window_function"] = True
                        for spec in filter_specs:
                            for sel_col in spec.get("select_columns") or []:
                                if sel_col not in self._pre_aggregated_columns:
                                    self._pre_aggregated_columns[sel_col] = []
                                self._pre_aggregated_columns[sel_col].append(
                                    {
                                        "source_table": source_table,
                                        "agg_view_name": agg_view_name,
                                        "is_window_function": True,
                                    }
                                )

                if not non_window_specs:
                    continue

            # GROUP BY approach. When this source ALSO produced a window view, the
            # window view already claimed the bare ``{source_table}_agg`` name, so
            # the GROUP BY view must use a DISTINCT name -- otherwise the second
            # CREATE OR REPLACE clobbers the window view and the window-derived
            # columns (e.g. latest_claim_status) vanish from the agg join.
            group_by_specs = non_window_specs if window_specs else specs
            group_view_name = (
                f"{source_table}_agg_grouped" if window_specs else f"{source_table}_agg"
            )
            # Point the GROUP BY columns' pre-aggregation bookkeeping at the
            # distinct grouped view so the agg-view join references the right view.
            if window_specs:
                for spec in group_by_specs:
                    for entry in self._pre_aggregated_columns.get(spec["col_name"], []):
                        if (
                            entry["source_table"] == source_table
                            and not entry.get("is_window_function")
                        ):
                            entry["agg_view_name"] = group_view_name
            agg_columns: list[str] = []
            for spec in group_by_specs:
                func = spec["function"]
                src_col = spec["source_column"]
                col_name = spec["col_name"]
                expression_raw = spec.get("expression", "")
                expression = self._substitute_template_vars(expression_raw)

                if self._is_complex_aggregate_expression(expression):
                    agg_columns.append(f"  {expression} AS {col_name}")
                elif func == "COUNT":
                    agg_columns.append(f"  COUNT(*) AS {col_name}")
                else:
                    agg_columns.append(f"  {func}({src_col}) AS {col_name}")

            from_clause = resolved_table
            has_alias = False

            if derived_cols:
                all_expressions = " ".join(
                    spec.get("expression", "") for spec in group_by_specs
                )
                referenced_derived = [
                    (col_n, expr, needs_except)
                    for col_n, (expr, needs_except) in sorted(derived_cols.items())
                    if col_n in all_expressions or col_n == join_col
                ]

                if referenced_derived:
                    except_col_names = [
                        col_n for col_n, _, ne in referenced_derived if ne
                    ]
                    derived_select = ",\n    ".join(
                        f"({expr}) AS {col_n}" for col_n, expr, _ in referenced_derived
                    )
                    except_clause = (
                        f" EXCEPT ({', '.join(except_col_names)})"
                        if except_col_names
                        else ""
                    )
                    from_clause = f"""(
  SELECT
    *{except_clause},
    {derived_select}
  FROM {resolved_table}
) src"""
                    has_alias = True

                    def _qualify_column_refs(
                        col_expr: str, derived_cols_list: list[tuple[str, str, bool]]
                    ) -> str:
                        qualified = col_expr
                        for cn, _, _ in derived_cols_list:
                            qualified = qualified.replace(f" {cn} ", f" src.{cn} ")
                            qualified = qualified.replace(f"({cn})", f"(src.{cn})")
                            qualified = qualified.replace(f" {cn}=", f" src.{cn}=")
                            qualified = qualified.replace(
                                f"WHEN {cn} ", f"WHEN src.{cn} "
                            )
                        return qualified

                    agg_columns = [
                        _qualify_column_refs(c, referenced_derived) for c in agg_columns
                    ]

            agg_columns_str = ",\n".join(agg_columns)

            # Check for join_via
            join_via_spec = None
            for spec in specs:
                if spec.get("join_via"):
                    join_via_spec = spec["join_via"]
                    break

            if join_via_spec:
                lookup_table = self._resolve_table_name(join_via_spec.lookup_table)
                from_clause_with_alias = (
                    from_clause if has_alias else f"{from_clause} src"
                )
                section = f"""-- ============================================================================
-- PRE-AGGREGATION: {source_table} aggregate columns (via {join_via_spec.lookup_table} lookup)
-- ============================================================================
CREATE OR REPLACE TEMPORARY VIEW {group_view_name} AS
SELECT
  lookup.{join_via_spec.lookup_key} AS {pk_col},
{agg_columns_str}
FROM {from_clause_with_alias}
INNER JOIN {lookup_table} lookup
  ON src.{join_via_spec.target_key} = lookup.{join_via_spec.target_key}
GROUP BY lookup.{join_via_spec.lookup_key};"""
            else:
                col_prefix = "src." if has_alias else ""
                section = f"""-- ============================================================================
-- PRE-AGGREGATION: {source_table} aggregate columns
-- ============================================================================
CREATE OR REPLACE TEMPORARY VIEW {group_view_name} AS
SELECT
  {col_prefix}{join_col} AS {pk_col},
{agg_columns_str}
FROM {from_clause}
GROUP BY {col_prefix}{join_col};"""
            sections.append(section)

            if source_col:
                self._agg_view_source_columns[group_view_name] = source_col

        return sections

    def _generate_window_aggregation_view(
        self,
        source_table: str,
        specs: list[dict[str, Any]],
        join_col: str,
        pk_col: str,
        resolved_table: str,
        derived_cols: dict[str, tuple[str, bool]] | None = None,
        view_name_suffix: str = "",
    ) -> str:
        """Generate a window-function based aggregation view."""
        window_specs = [s for s in specs if s.get("order_by")]
        if not window_specs:
            return ""

        first_spec = window_specs[0]
        order_by_cols = first_spec["order_by"]
        row_filter_raw = first_spec.get("row_filter")
        row_filter = (
            self._substitute_template_vars(row_filter_raw) if row_filter_raw else None
        )

        # Merge select_columns from all specs
        select_columns: list[str] = []
        seen_cols: set[str] = set()
        for spec in window_specs:
            for col in spec.get("select_columns") or []:
                if col not in seen_cols:
                    select_columns.append(col)
                    seen_cols.add(col)

        # Append DESC only when the order_by entry does not already carry an
        # explicit direction, so a column listed as ``service_date`` renders
        # ``service_date DESC`` while one already listed as ``service_date DESC``
        # (or ASC) is left untouched -- never ``service_date DESC DESC``. Pin
        # ``NULLS LAST`` so NULL ordering is identical across backends (DuckDB and
        # Spark default NULL placement diverges by direction), keeping the
        # "most recent non-null" window pick deterministic.
        def _with_direction(col: str) -> str:
            stripped = col.strip()
            tokens = stripped.upper().split()
            has_dir = "ASC" in tokens or "DESC" in tokens
            has_nulls = "NULLS" in tokens
            result = stripped if has_dir else f"{stripped} DESC"
            if not has_nulls:
                result = f"{result} NULLS LAST"
            return result

        order_by_clause = ", ".join(_with_direction(col) for col in order_by_cols)

        # Bare order_by column names (direction stripped): these must be PROJECTED
        # into the ``filtered`` CTE so the ``ranked`` CTE's ORDER BY can resolve
        # them. They are then DROPPED from the view's final output (via an explicit
        # final projection) so only the declared output columns survive.
        def _bare_col(col: str) -> str:
            parts = col.strip().rsplit(None, 1)
            if len(parts) == 2 and parts[1].upper() in ("ASC", "DESC"):
                return parts[0].strip()
            return col.strip()

        order_by_bare = [_bare_col(c) for c in order_by_cols]

        output_columns: list[str] = []
        # Names the view ultimately exposes, in order, starting with the join key.
        final_output_names: list[str] = [pk_col]
        produced_cols: set[str] = {pk_col}
        for spec in specs:
            col_name = spec["col_name"]
            src_col = spec["source_column"]
            if src_col and src_col != "*":
                src_col = self._substitute_template_vars(src_col)
                output_columns.append(f"  {src_col} AS {col_name}")
                if col_name not in produced_cols:
                    final_output_names.append(col_name)
                    produced_cols.add(col_name)

        for col in select_columns:
            output_columns.append(f"  {col}")
            if col not in produced_cols:
                final_output_names.append(col)
                produced_cols.add(col)

        # Project any order_by column not already produced (and not the partition
        # key) so the window ORDER BY can reference it. These are NOT added to
        # ``final_output_names`` -- they are scratch columns dropped by the final
        # explicit projection below.
        order_by_passthrough = [
            c
            for c in order_by_bare
            if c and c not in produced_cols and c != join_col
        ]
        for col in order_by_passthrough:
            output_columns.append(f"  {col}")
            produced_cols.add(col)

        # Build FROM clause with derived columns if needed
        from_clause = resolved_table
        col_prefix = ""

        if derived_cols:
            all_cols_to_check = [join_col, *order_by_cols, *select_columns]
            referenced_derived = [
                (col_name, expr, needs_except)
                for col_name, (expr, needs_except) in sorted(derived_cols.items())
                if any(col_name in col_ref for col_ref in all_cols_to_check)
                or col_name == join_col
            ]

            if referenced_derived:
                except_col_names = [
                    col_name
                    for col_name, _, needs_except in referenced_derived
                    if needs_except
                ]
                derived_select = ",\n    ".join(
                    f"({expr}) AS {col_name}"
                    for col_name, expr, _ in referenced_derived
                )
                except_clause = (
                    f" EXCEPT ({', '.join(except_col_names)})"
                    if except_col_names
                    else ""
                )
                from_clause = f"""(
  SELECT
    *{except_clause},
    {derived_select}
  FROM {resolved_table}
) src"""
                col_prefix = "src."

        # WHERE clause
        where_clause = ""
        if row_filter:
            qualified_filter = row_filter
            if col_prefix and derived_cols:
                for col_name in derived_cols:
                    qualified_filter = qualified_filter.replace(
                        f" {col_name} ", f" {col_prefix}{col_name} "
                    )
                    qualified_filter = qualified_filter.replace(
                        f"({col_name})", f"({col_prefix}{col_name})"
                    )
            where_clause = f"\n  WHERE {qualified_filter}"

        output_cols_str = (
            ",\n".join(output_columns)
            if output_columns
            else f"  {first_spec['source_column']} AS {first_spec['col_name']}"
        )

        # Final projection: list only the declared output columns explicitly. This
        # drops both ``rn`` and the order-by scratch columns WITHOUT a star-exclude,
        # which differs between dialects (DuckDB ``* EXCLUDE (a, b)`` vs Spark
        # ``* EXCEPT (a, b)``); an explicit column list is valid on both.
        final_projection = ",\n  ".join(final_output_names)

        agg_view_name = f"{source_table}_agg{view_name_suffix}"
        return f"""-- ============================================================================
-- PRE-AGGREGATION: {agg_view_name} (window function - max row with traceability)
-- ============================================================================
CREATE OR REPLACE TEMPORARY VIEW {agg_view_name} AS
WITH filtered AS (
  SELECT
    {col_prefix}{join_col} AS {pk_col},
{output_cols_str}
  FROM {from_clause}{where_clause}
),
ranked AS (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY {pk_col}
      ORDER BY {order_by_clause}
    ) AS rn
  FROM filtered
)
SELECT
  {final_projection}
FROM ranked
WHERE rn = 1;"""

    # ------------------------------------------------------------------
    # Join step generation
    # ------------------------------------------------------------------

    def _generate_join_step(
        self, step: int, join_info: dict[str, Any], prev_view: str
    ) -> str:
        """Dispatch to the appropriate join strategy handler."""
        strategy = join_info.get("strategy", "direct")
        if strategy == "direct":
            return self._generate_direct_join(step, join_info, prev_view)
        if strategy == "pivot":
            return self._generate_pivot_join(step, join_info, prev_view)
        if strategy in ("first", "first_record"):
            return self._generate_first_record_join(step, join_info, prev_view)
        msg = f"Unknown join strategy: {strategy}"
        raise ValueError(msg)

    def _prepare_join_context(
        self, join_info: dict[str, Any]
    ) -> tuple[str, str, str, str, str, str, str, list[str]]:
        """Extract common join setup from a join_info dict.

        Returns:
            Tuple of (target_table, source_col, target_col, join_filter,
            resolved_table, table_alias, sanitized_alias, base_column_selections).
        """
        target_table = join_info["target_table"]
        source_col = join_info["source_column"]
        target_col = join_info["target_column"]

        join_via = join_info.get("join_via")
        if join_via:
            source_col = join_via["source_key"]
            target_col = join_via["target_key"]

        join_filter: str = join_info.get("join_filter") or ""
        resolved_table = self._resolve_table_name(target_table)

        table_instance = join_info.get("table_instance")
        table_alias = table_instance if table_instance else target_table
        sanitized_alias = self._sanitize_alias(table_alias)

        base_column_selections = [
            f"base.{col}" for col in sorted(self._accumulated_columns.keys())
        ]

        return (
            target_table,
            source_col,
            target_col,
            join_filter,
            resolved_table,
            table_alias,
            sanitized_alias,
            base_column_selections,
        )

    def _generate_direct_join(
        self, step: int, join_info: dict[str, Any], prev_view: str
    ) -> str:
        """Generate SQL for a direct LEFT/INNER JOIN."""
        (
            target_table,
            source_col,
            target_col,
            join_filter,
            resolved_table,
            table_alias,
            sanitized_alias,
            base_column_selections,
        ) = self._prepare_join_context(join_info)
        cardinality = join_info["cardinality"].get("notation", "1:1")
        table_instance = join_info.get("table_instance")

        target_columns = self._get_table_columns(target_table)

        required_cols = self._get_required_columns_for_table(target_table)
        if required_cols:
            target_columns = [
                col
                for col in target_columns
                if col in required_cols or col.startswith("meta_")
            ]

        target_column_selections: list[str] = []
        for col in target_columns:
            alias = f"{sanitized_alias}__{col}"
            target_column_selections.append(f"target.{col} AS {alias}")
            self._accumulated_columns[alias] = sanitized_alias

        all_selections = base_column_selections + target_column_selections
        column_list = ",\n  ".join(all_selections)

        on_clause = f"base.{source_col} = target.{target_col}"
        if join_filter:
            rewritten_filter = self._rewrite_join_filter(join_filter, target_table)
            on_clause += f" AND {rewritten_filter}"

        step_label = (
            f"{target_table} as {table_alias}" if table_instance else target_table
        )

        join_type = join_info.get("join_type", "left").upper()
        join_clause = f"{join_type} JOIN"

        return f"""-- ============================================================================
-- STEP {step}: Join {step_label} (Direct Join - {cardinality})
-- ============================================================================
CREATE OR REPLACE TEMPORARY VIEW disposition_step_{step} AS
SELECT
  {column_list}
FROM {prev_view} base
{join_clause} {resolved_table} target
  ON {on_clause};"""

    def _generate_pivot_join(
        self, step: int, join_info: dict[str, Any], prev_view: str
    ) -> str:
        """Generate SQL for a pivot join."""
        target_table = join_info["target_table"]
        source_col = join_info["source_column"]
        target_col = join_info["target_column"]
        cardinality = join_info["cardinality"].get("notation", "1:N")
        join_filter = join_info.get("join_filter")

        resolved_table = self._resolve_table_name(target_table)

        pivot_spec = join_info.get("pivot", {})
        value_column = pivot_spec.get("value_column", "Value")
        prefix = pivot_spec.get("prefix", "Value")
        max_records = int(pivot_spec.get("max_records", 6))

        where_clause = ""
        if join_filter:
            rewritten_filter = self._rewrite_join_filter(
                join_filter, target_table, alias=target_table
            )
            where_clause = f"\n  WHERE {rewritten_filter}"

        pivot_agg_selections: list[str] = []
        pivot_column_names: list[str] = []
        for i in range(1, max_records + 1):
            target_col_name = f"{prefix}{i}"
            col_alias = f"{target_table}__{target_col_name}"
            pivot_agg_selections.append(
                f"MAX(CASE WHEN rn = {i} THEN {value_column} END) AS {col_alias}"
            )
            pivot_column_names.append(col_alias)
            self._accumulated_columns[col_alias] = target_table
            # Record so the final-assembly mapping points the target column
            # (e.g. diagnosis_1) at the pivoted output (diagnosis__diagnosis_1)
            # rather than the raw source column.
            self._pivot_column_map[(target_table, target_col_name)] = col_alias

        pivot_agg_str = ",\n  ".join(pivot_agg_selections)

        base_column_selections = [
            f"base.{col}"
            for col in sorted(self._accumulated_columns.keys())
            if col not in pivot_column_names
        ]
        pivot_column_selections = [f"pivoted.{col}" for col in pivot_column_names]

        all_selections = base_column_selections + pivot_column_selections
        column_list = ",\n  ".join(all_selections)

        filter_note = f" (Filtered: {join_filter})" if join_filter else ""

        return f"""-- ============================================================================
-- STEP {step}: Join {target_table} (Pivot Join - {cardinality}){filter_note}
-- ============================================================================
CREATE OR REPLACE TEMPORARY VIEW {target_table}_pivoted AS
WITH ranked AS (
  SELECT
    {target_col},
    {value_column},
    ROW_NUMBER() OVER (PARTITION BY {target_col} ORDER BY {value_column} ASC NULLS LAST) as rn
  FROM {resolved_table}{where_clause}
)
SELECT
  {target_col},
  {pivot_agg_str}
FROM ranked
WHERE rn <= {max_records}
GROUP BY {target_col};

CREATE OR REPLACE TEMPORARY VIEW disposition_step_{step} AS
SELECT
  {column_list}
FROM {prev_view} base
LEFT JOIN {target_table}_pivoted pivoted
  ON base.{source_col} = pivoted.{target_col};"""

    def _generate_first_record_join(
        self, step: int, join_info: dict[str, Any], prev_view: str
    ) -> str:
        """Generate SQL for a first-record join (ROW_NUMBER partitioned dedup)."""
        (
            target_table,
            source_col,
            target_col,
            join_filter,
            resolved_table,
            table_alias,
            sanitized_alias,
            base_column_selections,
        ) = self._prepare_join_context(join_info)
        cardinality = join_info["cardinality"].get("notation", "1:0..N")
        table_instance = join_info.get("table_instance")

        where_clause = ""
        if join_filter:
            rewritten_filter = self._rewrite_join_filter(
                join_filter, target_table, alias=target_table
            )
            where_clause = f"\n  WHERE {rewritten_filter}"

        target_columns = self._get_table_columns(target_table)

        required_cols = self._get_required_columns_for_table(target_table)
        if required_cols:
            filtered_columns = [
                col
                for col in target_columns
                if col in required_cols or col.startswith("meta_")
            ]
        else:
            filtered_columns = target_columns

        # Determine ordering columns
        order_columns = target_col
        if target_columns:
            type_cols = [col for col in target_columns if "type" in col.lower()]
            name_cols = [
                col
                for col in target_columns
                if any(x in col.lower() for x in ["name", "lastname", "last_name"])
            ]
            if type_cols and name_cols:
                order_columns = f"{type_cols[0]}, {name_cols[0]}"
            elif type_cols:
                order_columns = type_cols[0]
            elif name_cols:
                order_columns = name_cols[0]
            else:
                order_col = next(
                    (
                        col
                        for col in target_columns
                        if col.lower() != target_col.lower()
                    ),
                    target_col,
                )
                order_columns = order_col

        # Build subquery column set
        subquery_columns = set(filtered_columns)
        subquery_columns.add(target_col)
        for order_col_item in order_columns.split(","):
            subquery_columns.add(order_col_item.strip())

        # Check for derived columns
        derived_cols = self._get_derived_columns_for_source(target_table)
        derived_in_subquery: list[tuple[str, str]] = []
        if derived_cols:
            for col_name in list(subquery_columns):
                if col_name in derived_cols:
                    expr, _ = derived_cols[col_name]
                    derived_in_subquery.append((col_name, expr))
                    subquery_columns.discard(col_name)

        subquery_column_list = ",\n    ".join(sorted(subquery_columns))

        target_column_selections: list[str] = []
        for col in filtered_columns:
            alias = f"{sanitized_alias}__{col}"
            target_column_selections.append(f"target.{col} AS {alias}")
            self._accumulated_columns[alias] = sanitized_alias

        all_selections = base_column_selections + target_column_selections
        column_list = ",\n  ".join(all_selections)

        step_label = (
            f"{target_table} as {table_alias}" if table_instance else target_table
        )
        filter_note = f" (Filtered: {join_filter})" if join_filter else ""

        # Build FROM clause with derived columns
        if derived_in_subquery:
            derived_select = ",\n    ".join(
                f"({expr}) AS {col_name}" for col_name, expr in derived_in_subquery
            )
            full_subquery_column_list = subquery_column_list
            if subquery_column_list:
                full_subquery_column_list += ",\n    " + ",\n    ".join(
                    col_name for col_name, _ in derived_in_subquery
                )
            else:
                full_subquery_column_list = ",\n    ".join(
                    col_name for col_name, _ in derived_in_subquery
                )
            inner_from = f"""(
    SELECT
      *,
      {derived_select}
    FROM {resolved_table}
  ) src"""
        else:
            full_subquery_column_list = subquery_column_list
            inner_from = resolved_table

        return f"""-- ============================================================================
-- STEP {step}: Join {step_label} (First Record - {cardinality}){filter_note}
-- ============================================================================
CREATE OR REPLACE TEMPORARY VIEW {table_alias}_first AS
SELECT
  {full_subquery_column_list}
FROM (
  SELECT
    {full_subquery_column_list},
    ROW_NUMBER() OVER (PARTITION BY {target_col} ORDER BY {order_columns}) as rn
  FROM {inner_from}{where_clause}
) ranked
WHERE rn = 1;

CREATE OR REPLACE TEMPORARY VIEW disposition_step_{step} AS
SELECT
  {column_list}
FROM {prev_view} base
LEFT JOIN {table_alias}_first target
  ON base.{source_col} = target.{target_col};"""

    # ------------------------------------------------------------------
    # Aggregation view join
    # ------------------------------------------------------------------

    def _generate_agg_view_join(
        self,
        step: int,
        agg_view_name: str,
        col_names: list[str],
        prev_view: str,
        table_umf: UMF,
    ) -> str:
        """Generate SQL for joining a pre-aggregation view."""
        pk_col = table_umf.primary_key[0] if table_umf.primary_key else "id"

        base_column_selections = [
            f"base.{col}" for col in sorted(self._accumulated_columns.keys())
        ]

        agg_column_selections: list[str] = []
        for col_name in col_names:
            alias = f"{agg_view_name}__{col_name}"
            agg_column_selections.append(f"agg.{col_name} AS {alias}")
            self._accumulated_columns[alias] = agg_view_name

        all_selections = base_column_selections + agg_column_selections
        column_list = ",\n  ".join(all_selections)

        # Check if source column is derived
        source_col = self._agg_view_source_columns.get(agg_view_name)
        join_key_expr = f"base.{pk_col}"

        if source_col and source_col != pk_col:
            derived_expr = self._get_derived_column_expression(table_umf, source_col)
            if derived_expr:
                join_key_expr = derived_expr.replace(pk_col, f"base.{pk_col}")

        return f"""-- ============================================================================
-- STEP {step}: Join {agg_view_name} (Pre-aggregated Data)
-- ============================================================================
CREATE OR REPLACE TEMPORARY VIEW disposition_step_{step} AS
SELECT
  {column_list}
FROM {prev_view} base
LEFT JOIN {agg_view_name} agg
  ON {join_key_expr} = agg.{pk_col};"""

    # ------------------------------------------------------------------
    # Expression rewriting
    # ------------------------------------------------------------------

    def _rewrite_join_filter(
        self, join_filter: str, target_table: str, alias: str = "target"
    ) -> str:
        """Rewrite bare column references in a join filter to use the given alias."""
        result = join_filter
        table_cols = set(self._get_table_columns(target_table))

        # Longest-first replacement to avoid partial matches
        for col in sorted(table_cols, key=len, reverse=True):
            pattern = rf"(?<![.\w])({re.escape(str(col))})(?![\w])"
            result = re.sub(pattern, rf"{alias}.\1", result)

        return result

    def _rewrite_expression_for_alias(
        self, expression: str, alias_prefix: str, table_name: str
    ) -> str:
        """Rewrite bare column references in *expression* with *alias_prefix*."""
        table_cols = set(self._get_table_columns(table_name))

        def _token_repl(m: re.Match[str]) -> str:
            tok = m.group(1)
            if tok in table_cols:
                return f"{alias_prefix}{tok}"
            return tok

        return _IDENTIFIER_RE.sub(_token_repl, expression)

    # ------------------------------------------------------------------
    # Final assembly
    # ------------------------------------------------------------------

    def _generate_final_assembly(
        self,
        table_name: str,
        table_umf: UMF,
        final_view: str,
        base_table: str | None,
    ) -> str:
        """Generate the final SELECT with column derivations and survivorship."""
        column_mappings: list[str] = []

        for col_def in sorted(table_umf.columns, key=lambda c: c.name.lower()):
            col_name = col_def.name
            derivation = col_def.derivation
            data_type = (col_def.data_type or "STRING").upper()
            column_default = col_def.default

            if derivation:
                mapping = self._generate_column_mapping(
                    col_name, derivation, base_table, data_type, column_default
                )
                column_mappings.append(f"  {mapping} AS {col_name}")
            elif column_default is not None:
                spark_type = self._get_spark_type(data_type)
                default_literal = self._format_default_value_literal(column_default)
                column_mappings.append(
                    f"  CAST({default_literal} AS {spark_type}) AS {col_name}"
                )
            else:
                spark_type = self._get_spark_type(data_type)
                column_mappings.append(f"  CAST(NULL AS {spark_type}) AS {col_name}")

        # Provenance passthrough
        if self._join_sequence:
            provenance_cols = self._get_joined_provenance_columns(self._join_sequence)
            for table_alias, prov_col in provenance_cols:
                sanitized = self._sanitize_alias(table_alias)
                prefixed = f"{sanitized}__{prov_col}"
                column_mappings.append(f"  base.{prefixed} AS {prefixed}")

        column_mappings_str = ",\n".join(column_mappings)

        if not base_table:
            return f"""-- ============================================================================
-- FINAL ASSEMBLY: {table_name} (Synthetic Table)
-- ============================================================================
CREATE OR REPLACE TEMPORARY VIEW {table_name} AS
SELECT
{column_mappings_str};"""

        return f"""-- ============================================================================
-- FINAL ASSEMBLY: {table_name} with Column Derivations
-- ============================================================================
CREATE OR REPLACE TEMPORARY VIEW {table_name} AS
SELECT
{column_mappings_str}
FROM {final_view} base;"""

    def _get_joined_provenance_columns(
        self, join_sequence: list[dict[str, Any]]
    ) -> list[tuple[str, str]]:
        """Collect meta_* columns from all joined tables."""
        provenance_cols: list[tuple[str, str]] = []
        for join_info in join_sequence:
            target_table = join_info["target_table"]
            table_alias = join_info.get("table_instance", target_table)
            for col in self._get_table_columns(target_table):
                if col.startswith("meta_"):
                    provenance_cols.append((table_alias, col))
        return provenance_cols

    # ------------------------------------------------------------------
    # Column mapping / derivation
    # ------------------------------------------------------------------

    def _generate_column_mapping(
        self,
        col_name: str,
        derivation: Any,
        base_table: str | None,
        data_type: str = "STRING",
        column_default: str | float | bool | None = None,
    ) -> str:
        """Generate a SQL expression for a single column derivation."""
        candidates = derivation.candidates if derivation else []
        survivorship = derivation.survivorship if derivation else None
        survivorship_default = survivorship.default_value if survivorship else None
        default_value = (
            survivorship_default if survivorship_default is not None else column_default
        )
        strategy = survivorship.strategy if survivorship else None

        derivation_strategy = derivation.strategy if derivation else None

        if derivation_strategy in ("primary_key", "base_column"):
            return f"base.{col_name}"

        if not candidates:
            if default_value is not None:
                default_literal = self._format_default_value_literal(
                    default_value, data_type
                )
                spark_type = self._get_spark_type(data_type)
                return f"CAST({default_literal} AS {spark_type})"
            spark_type = self._get_spark_type(data_type)
            return f"CAST(NULL AS {spark_type})"

        # Single candidate
        if len(candidates) == 1:
            single_expr = self._generate_single_candidate_mapping(
                candidates[0], base_table, col_name
            )
            if default_value is not None:
                default_literal = self._format_default_value_literal(
                    default_value, data_type
                )
                return f"COALESCE({single_expr}, {default_literal})"
            return single_expr

        # max_across_sources
        if strategy == "max_across_sources":
            return self._generate_greatest_mapping(
                candidates, base_table, col_name, default_value, data_type
            )

        # Multiple candidates -> COALESCE
        return self._generate_multiple_candidate_mapping(
            candidates, base_table, col_name, default_value, data_type
        )

    def _generate_single_candidate_mapping(
        self,
        candidate: Any,
        base_table: str | None,
        target_col_name: str = "",
    ) -> str:
        """Generate SQL mapping for a single derivation candidate."""
        table = candidate.table
        source_column = candidate.column or ""
        expression_raw = candidate.expression
        expression = (
            self._substitute_template_vars(expression_raw) if expression_raw else None
        )

        # Check pre-aggregated columns
        col_to_check = (
            target_col_name
            if target_col_name in self._pre_aggregated_columns
            else source_column
        )
        if col_to_check in self._pre_aggregated_columns:
            agg_sources = self._pre_aggregated_columns[col_to_check]
            for agg_info in agg_sources:
                if table == agg_info["source_table"]:
                    agg_view_name = agg_info["agg_view_name"]
                    if self._expression_has_aggregate(expression):
                        return f"base.{agg_view_name}__{col_to_check}"
                    if expression:
                        return self._rewrite_expression_for_alias(
                            expression, f"base.{agg_view_name}__", table
                        )
                    return f"base.{agg_view_name}__{col_to_check}"

        column = source_column
        table_instance = candidate.table_instance

        if not table:
            return "NULL"

        # Pivoted source: the pivot CTE emits one numbered column per target
        # column (e.g. diagnosis_1 -> diagnosis__diagnosis_1), so a target column
        # derived from a pivot source references that pivoted output, NOT the raw
        # source column (which the pivot CTE does not project).
        pivoted_alias = self._pivot_column_map.get((table, target_col_name))
        if pivoted_alias is not None:
            return f"base.{pivoted_alias}"

        table_alias = self._sanitize_alias(table_instance if table_instance else table)

        source_expr = expression if expression else column
        if not source_expr:
            return "NULL"

        # Base table column
        if base_table and table == base_table:
            if expression:
                return self._rewrite_expression_for_alias(source_expr, "base.", table)
            return f"base.{column}"

        # Expression with alias rewriting
        if expression:
            agg_view_alias = None
            for agg_sources in self._pre_aggregated_columns.values():
                for agg_info in agg_sources:
                    if agg_info["source_table"] == table:
                        agg_view_alias = agg_info["agg_view_name"]
                        break
                if agg_view_alias:
                    break
            alias_prefix = (
                f"base.{agg_view_alias}__"
                if agg_view_alias
                else f"base.{table_alias}__"
            )
            return self._rewrite_expression_for_alias(source_expr, alias_prefix, table)

        # Simple column reference
        return f"base.{table_alias}__{column}"

    def _generate_multiple_candidate_mapping(
        self,
        candidates: list[Any],
        base_table: str | None,
        target_col_name: str = "",
        default_value: str | float | bool | None = None,
        data_type: str = "STRING",
    ) -> str:
        """Generate COALESCE mapping for multiple candidates."""
        is_string_type = data_type.upper() in (
            "STRING",
            "STRINGTYPE",
            "VARCHAR",
            "CHAR",
            "TEXT",
        )

        coalesce_parts: list[str] = []
        for candidate in sorted(
            candidates, key=lambda x: x.priority if x.priority is not None else 999
        ):
            part = self._generate_single_candidate_mapping(
                candidate, base_table, target_col_name
            )
            if part and part.strip():
                if is_string_type and part != "NULL":
                    part = f"NULLIF({part}, '')"
                coalesce_parts.append(part)

        if default_value is not None:
            coalesce_parts.append(
                self._format_default_value_literal(default_value, data_type)
            )

        if len(coalesce_parts) == 0:
            return "NULL"
        if len(coalesce_parts) == 1:
            return coalesce_parts[0]

        if len(coalesce_parts) <= 3:
            return f"COALESCE({', '.join(coalesce_parts)})"
        parts_formatted = ",\n    ".join(coalesce_parts)
        return f"COALESCE(\n    {parts_formatted}\n)"

    def _generate_greatest_mapping(
        self,
        candidates: list[Any],
        base_table: str | None,
        target_col_name: str = "",
        default_value: str | float | bool | None = None,
        data_type: str = "STRING",
    ) -> str:
        """Generate GREATEST mapping for max_across_sources strategy."""
        greatest_parts: list[str] = []
        for candidate in candidates:
            part = self._generate_single_candidate_mapping(
                candidate, base_table, target_col_name
            )
            if part and part.strip() and part != "NULL":
                greatest_parts.append(part)

        if len(greatest_parts) == 0:
            if default_value is not None:
                return self._format_default_value_literal(default_value, data_type)
            return "NULL"

        if len(greatest_parts) == 1:
            if default_value is not None:
                default_literal = self._format_default_value_literal(
                    default_value, data_type
                )
                return f"COALESCE({greatest_parts[0]}, {default_literal})"
            return greatest_parts[0]

        parts_formatted = ", ".join(greatest_parts)
        if default_value is not None:
            default_literal = self._format_default_value_literal(
                default_value, data_type
            )
            return f"COALESCE(GREATEST({parts_formatted}), {default_literal})"
        return f"GREATEST({parts_formatted})"

    # ------------------------------------------------------------------
    # Type / literal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_spark_type(data_type: str) -> str:
        """Convert a UMF data type to a SQL type string."""
        return _SPARK_TYPE_MAP.get(data_type.upper(), "STRING")

    @staticmethod
    def _format_default_value_literal(
        default_value: str | float | bool | None, data_type: str = "STRING"
    ) -> str:
        """Format a default value as a SQL literal."""
        if data_type.upper() in ("STRING", "TEXT", "CHAR", "STRINGTYPE"):
            if default_value is None or default_value == "":
                return "''"
            if isinstance(default_value, (int, float)):
                return f"'{default_value!s}'"

        if default_value is None:
            return "NULL"
        if isinstance(default_value, bool):
            return "TRUE" if default_value else "FALSE"
        if isinstance(default_value, (int, float)):
            return str(default_value)
        escaped = str(default_value).replace("'", "''")
        return f"'{escaped}'"

    # ------------------------------------------------------------------
    # Aggregate expression detection
    # ------------------------------------------------------------------

    @staticmethod
    def _is_complex_aggregate_expression(expression: str) -> bool:
        """Check if an expression is complex and should be used verbatim."""
        if not expression:
            return False
        expr_upper = expression.upper()

        if "CASE" in expr_upper:
            return True

        agg_count = sum(1 for agg in _AGGREGATE_FUNCTIONS if agg in expr_upper)
        if agg_count > 1:
            return True

        if "MAX_BY(" in expr_upper:
            return True

        format_funcs = ["DATE_FORMAT(", "CAST(", "COALESCE(", "CONCAT(", "IFNULL("]
        has_format_func = any(func in expr_upper for func in format_funcs)
        has_aggregate = any(agg in expr_upper for agg in _AGGREGATE_FUNCTIONS)
        return bool(has_format_func and has_aggregate)

    @staticmethod
    def _expression_has_aggregate(expression: str | None) -> bool:
        """Check if expression contains SQL aggregate functions."""
        if not expression:
            return False
        expr_upper = expression.upper()
        return any(agg in expr_upper for agg in _AGGREGATE_FUNCTIONS)


# ------------------------------------------------------------------
# Convenience function
# ------------------------------------------------------------------


def generate_sql_plan(
    table_umf: UMF,
    related_umfs: dict[str, UMF],
    *,
    template_vars: dict[str, str] | None = None,
    table_resolver: Callable[[str], str] | None = None,
    table_renderer: TableRenderer | None = None,
    mode: Literal["views", "cte"] = "views",
) -> str:
    """Generate a SQL execution plan for a single target table.

    This is a convenience wrapper around :class:`SQLPlanGenerator`.

    Args:
        table_umf: UMF metadata for the target table.
        related_umfs: Dict mapping table names to UMF models for source tables.
        template_vars: Optional template variable substitutions.
        table_resolver: Optional callable to resolve table names.
        table_renderer: Optional :class:`TableRenderer` seam (mutually exclusive
            with *table_resolver*); inject a ``DbtRefRenderer`` to emit refs.
        mode: Output format — ``"views"`` (default) or ``"cte"``.

    Returns:
        Multi-statement SQL string (views mode) or single CTE statement
        (cte mode).

    """
    generator = SQLPlanGenerator(
        template_vars=template_vars,
        table_resolver=table_resolver,
        table_renderer=table_renderer,
    )
    return generator.generate_for_table(table_umf, related_umfs, mode=mode)


__all__ = ["SQLPlanGenerator", "generate_sql_plan"]
