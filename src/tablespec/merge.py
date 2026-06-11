"""Merge multiple table files using Spark and UMF metadata."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile
from typing import TYPE_CHECKING

try:
    from pyspark.sql import DataFrame, SparkSession
    from pyspark.sql import functions as F
    from pyspark.sql.window import Window
except ImportError:
    DataFrame = None  # type: ignore[assignment,misc]
    SparkSession = None  # type: ignore[assignment,misc]

try:
    from tablespec.casting_utils import cast_timestamp_with_epoch_fallback
except ImportError:
    cast_timestamp_with_epoch_fallback = None  # type: ignore[assignment]

from tablespec.ingestion import get_reader
from tablespec.ingestion.raw_ingester import build_column_lookup, map_headers

try:
    from tablespec.spark_factory import SparkSessionFactory
except ImportError:
    SparkSessionFactory = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from tablespec.models import UMF, UMFColumn


@dataclass(frozen=True)
class MergeResult:
    """Result of a merge operation."""

    rows_written: int
    source_row_counts: dict[str, int]


def merge_table_files(
    umf: UMF,
    sources: Sequence[Path],
    output_path: Path,
    *,
    emit_audit: bool = False,
    spark: SparkSession | None = None,
) -> MergeResult:
    """Merge multiple files for a table using timestamp scoring."""
    if not umf.primary_key:
        msg = f"Table {umf.table_name} has no primary_key defined; cannot merge"
        raise ValueError(msg)
    if not sources:
        msg = "At least one source file is required for merge"
        raise ValueError(msg)

    if SparkSessionFactory is None:
        msg = "SparkSessionFactory is not available. Install tablespec[spark] for merge support."
        raise ImportError(msg)

    spark_session = spark or SparkSessionFactory.create_session("tablespec-merge")
    timestamp_columns = _get_timestamp_columns(umf.columns)
    source_spec = umf.effective_source()
    if source_spec.kind != "delimited":
        msg = (
            f"merge_table_files only supports delimited sources; "
            f"table {umf.table_name} declares kind={source_spec.kind!r}"
        )
        raise ValueError(msg)
    delimiter = source_spec.delimiter or "|"
    reader = get_reader(source_spec)

    lookup = build_column_lookup(umf, include_non_data=True)
    required_columns = set(umf.primary_key)
    required_columns.update(col.name for col in timestamp_columns)

    data_frames: list[DataFrame] = []
    source_row_counts: dict[str, int] = {}

    for source_index, source in enumerate(sources):
        if not source.exists():
            msg = f"Source file not found: {source}"
            raise ValueError(msg)

        df = reader.read(
            source_spec.model_copy(update={"path": str(source)}), spark_session
        )

        header_mapping = map_headers(df.columns, lookup)
        mapped_targets = {match.umf_column for match in header_mapping.values()}
        missing_required = [
            col for col in required_columns if col not in mapped_targets
        ]
        if missing_required:
            missing_list = ", ".join(sorted(missing_required))
            msg = f"File {source} is missing required columns: {missing_list}"
            raise ValueError(msg)

        for raw_name, match in header_mapping.items():
            if raw_name != match.umf_column:
                df = df.withColumnRenamed(raw_name, match.umf_column)

        # Ensure all expected columns exist (fill missing optional with null)
        for col in umf.columns:
            if col.name not in df.columns:
                df = df.withColumn(col.name, F.lit(None).cast("string"))

        df = df.withColumn("_merge_source_index", F.lit(source_index))
        df = df.withColumn("_merge_source_name", F.lit(source.name))
        df = df.withColumn("_merge_row_index", F.monotonically_increasing_id())

        data_frames.append(df)
        source_row_counts[str(source)] = df.count()

    combined = data_frames[0]
    for df in data_frames[1:]:
        combined = combined.unionByName(
            df.select(combined.columns), allowMissingColumns=True
        )

    scored = _apply_scoring(combined, umf.primary_key, timestamp_columns)
    winners = _select_winners(scored, umf.primary_key)

    audit_columns: list[str] = []
    if emit_audit:
        audit_columns = ["merge_source", "merge_score"]
        _ensure_no_audit_collision([col.name for col in umf.columns], audit_columns)
        winners = winners.withColumn("merge_source", F.col("_merge_source_name"))
        winners = winners.withColumn("merge_score", F.col("_merge_score"))

    output_columns = [col.name for col in umf.columns] + audit_columns
    winners = winners.select(*output_columns)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows_written = winners.count()
    _write_single_csv(winners, output_path, delimiter)

    if _is_disposition_table(umf.table_name):
        _append_disposition_footer(output_path, rows_written)

    return MergeResult(rows_written=rows_written, source_row_counts=source_row_counts)


def _apply_scoring(
    df: DataFrame,
    primary_key: list[str],
    timestamp_columns: list[UMFColumn],
) -> DataFrame:
    if not timestamp_columns:
        return df.withColumn("_merge_score", F.lit(0))

    if cast_timestamp_with_epoch_fallback is None:
        msg = "casting_utils module is not available. Install tablespec[spark] for merge support."
        raise ImportError(msg)

    for col in timestamp_columns:
        parsed_col = cast_timestamp_with_epoch_fallback(F.col(col.name), col.format)
        df = df.withColumn(f"_ts_{col.name}", parsed_col)

    window = Window.partitionBy(*primary_key)
    score_exprs = []
    for col in timestamp_columns:
        ts_col = F.col(f"_ts_{col.name}")
        max_col = F.max(ts_col).over(window)
        df = df.withColumn(f"_max_{col.name}", max_col)
        score_exprs.append(
            F.when((max_col.isNotNull()) & (ts_col == max_col), F.lit(1)).otherwise(0)
        )

    score = score_exprs[0]
    for expr in score_exprs[1:]:
        score = score + expr

    return df.withColumn("_merge_score", score)


def _select_winners(df: DataFrame, primary_key: list[str]) -> DataFrame:
    window = Window.partitionBy(*primary_key).orderBy(
        F.col("_merge_score").desc(),
        F.col("_merge_source_index").asc(),
        F.col("_merge_row_index").asc(),
    )
    ranked = df.withColumn("_merge_rank", F.row_number().over(window))
    return ranked.filter(F.col("_merge_rank") == 1)


def _write_single_csv(df: DataFrame, output_path: Path, delimiter: str) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        df.coalesce(1).write.options(header=True, sep=delimiter, emptyValue="").mode(
            "overwrite"
        ).csv(tmpdir)
        temp_dir = Path(tmpdir)
        part_files = list(temp_dir.glob("part-*"))
        if not part_files:
            msg = "Failed to write merged output (no part files produced)"
            raise RuntimeError(msg)
        if output_path.exists():
            output_path.unlink()
        shutil.move(part_files[0], output_path)


def _ensure_no_audit_collision(
    columns: Iterable[str], audit_columns: list[str]
) -> None:
    duplicates = [col for col in audit_columns if col in set(columns)]
    if duplicates:
        dup_list = ", ".join(sorted(duplicates))
        msg = f"Audit columns collide with existing columns: {dup_list}"
        raise ValueError(msg)


def _get_timestamp_columns(columns: list[UMFColumn]) -> list[UMFColumn]:
    return [col for col in columns if col.data_type == "TimestampType"]


def _is_disposition_table(table_name: str) -> bool:
    return "disposition" in table_name


def _append_disposition_footer(output_path: Path, record_count: int) -> None:
    content = output_path.read_text(encoding="utf-8")
    if not content.endswith("\n"):
        content += "\n"
    content += f"{record_count}\n"
    output_path.write_text(content, encoding="utf-8")
