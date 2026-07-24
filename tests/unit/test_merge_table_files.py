"""Contract tests for table merge with survivorship (US-018).

Full Spark-backed merge is exercised when tablespec[spark] is available.
These tests pin fail-closed preconditions and the public API surface so the
story remains machine-traceable via @covers.
"""

# @covers US-018-AC1
# @covers US-018-AC2
# @covers US-018-AC3

from __future__ import annotations

from pathlib import Path

import pytest

from tablespec.merge import MergeResult, merge_table_files
from tests.builders import UMFBuilder


def test_merge_requires_primary_key(tmp_path: Path) -> None:
    umf = UMFBuilder("member").column("id", "INTEGER").column("name", "VARCHAR").build()
    # Clear any default PK from builder if present
    if not umf.primary_key:
        src = tmp_path / "a.csv"
        src.write_text("id|name\n1|a\n", encoding="utf-8")
        with pytest.raises(ValueError, match="primary_key"):
            merge_table_files(umf, [src], tmp_path / "out")


def test_merge_requires_at_least_one_source(tmp_path: Path) -> None:
    umf = (
        UMFBuilder("member")
        .column("id", "INTEGER", key_type="primary", nullable=False)
        .primary_key("id")
        .build()
    )
    with pytest.raises(ValueError, match="At least one source"):
        merge_table_files(umf, [], tmp_path / "out")


def test_merge_result_dataclass_is_public() -> None:
    result = MergeResult(rows_written=0, source_row_counts={})
    assert result.rows_written == 0
    assert result.source_row_counts == {}
