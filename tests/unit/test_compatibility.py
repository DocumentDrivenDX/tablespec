# @covers US-035-AC1
# @covers US-035-AC2
"""Unit tests for schema compatibility checking."""

from copy import deepcopy

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tablespec.compatibility import (
    CompatibilityIssue,
    CompatibilityReport,
    check_compatibility,
)
from tablespec.models.umf import UMF, Nullable, UMFColumn
from tablespec.type_lattice import (
    SAFE_WIDENINGS,
    is_length_compatible,
    is_precision_compatible,
    is_safe_widening,
)
from tests.strategies import umf_object as shared_umf_object

pytestmark = pytest.mark.no_spark


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _col(
    name: str,
    data_type: str = "VARCHAR",
    *,
    length: int | None = 50,
    nullable: Nullable | None = None,
    description: str | None = None,
    precision: int | None = None,
    scale: int | None = None,
    aliases: list[str] | None = None,
    **kwargs,
) -> UMFColumn:
    return UMFColumn(
        name=name,
        data_type=data_type,
        length=length,
        nullable=nullable,
        description=description,
        precision=precision,
        scale=scale,
        aliases=aliases,
        **kwargs,
    )


def _umf(
    columns: list[UMFColumn] | None = None,
    *,
    primary_key: list[str] | None = None,
    description: str | None = None,
) -> UMF:
    cols = columns or [_col("id", "INTEGER", length=None)]
    return UMF(
        version="1.0",
        table_name="test_table",
        columns=cols,
        primary_key=primary_key,
        description=description,
    )


def _issues_by_change(
    report: CompatibilityReport, change: str
) -> list[CompatibilityIssue]:
    return [i for i in report.issues if i.change == change]


def _issues_by_severity(
    report: CompatibilityReport, severity: str
) -> list[CompatibilityIssue]:
    return [i for i in report.issues if i.severity == severity]


# ---------------------------------------------------------------------------
# type_lattice unit tests
# ---------------------------------------------------------------------------


class TestSafeWidening:
    def test_identical_types_are_safe(self):
        ok, reason = is_safe_widening("INTEGER", "INTEGER")
        assert ok
        assert "identical" in reason.lower()

    @pytest.mark.parametrize("old,new", list(SAFE_WIDENINGS.keys()))
    def test_all_safe_widenings(self, old, new):
        ok, reason = is_safe_widening(old, new)
        assert ok
        assert reason

    def test_reverse_is_not_safe(self):
        ok, _ = is_safe_widening("DECIMAL", "INTEGER")
        assert not ok

    def test_case_insensitive(self):
        ok, _ = is_safe_widening("integer", "decimal")
        assert ok

    def test_unrelated_types(self):
        ok, _ = is_safe_widening("BOOLEAN", "VARCHAR")
        assert not ok


class TestLengthCompatible:
    def test_same(self):
        assert is_length_compatible(50, 50)

    def test_widening(self):
        assert is_length_compatible(50, 100)

    def test_narrowing(self):
        assert not is_length_compatible(100, 50)

    def test_bounded_to_unbounded(self):
        assert is_length_compatible(50, None)

    def test_unbounded_to_bounded(self):
        assert not is_length_compatible(None, 50)

    def test_both_unbounded(self):
        assert is_length_compatible(None, None)


class TestPrecisionCompatible:
    def test_same(self):
        assert is_precision_compatible(10, 2, 10, 2)

    def test_widening(self):
        assert is_precision_compatible(10, 2, 18, 4)

    def test_narrowing_precision(self):
        assert not is_precision_compatible(18, 2, 10, 2)

    def test_narrowing_scale(self):
        assert not is_precision_compatible(10, 4, 10, 2)

    def test_none_to_none(self):
        assert is_precision_compatible(None, None, None, None)

    def test_specified_to_none(self):
        assert is_precision_compatible(10, 2, None, None)

    def test_none_to_specified(self):
        assert not is_precision_compatible(None, None, 10, 2)


# ---------------------------------------------------------------------------
# Compatibility checker — parametrized golden-style tests
# ---------------------------------------------------------------------------


class TestColumnAddition:
    def test_add_nullable_column_is_safe(self):
        old = _umf([_col("id", "INTEGER", length=None)])
        new = _umf(
            [
                _col("id", "INTEGER", length=None),
                _col("email", "VARCHAR", nullable=Nullable(MD=True, MP=True)),
            ]
        )
        report = check_compatibility(old, new)
        assert report.is_backward_compatible
        added = _issues_by_change(report, "added")
        assert len(added) == 1
        assert added[0].severity == "info"

    def test_add_required_column_is_breaking(self):
        old = _umf([_col("id", "INTEGER", length=None)])
        new = _umf(
            [
                _col("id", "INTEGER", length=None),
                _col("ssn", "VARCHAR", nullable=Nullable(MD=False)),
            ]
        )
        report = check_compatibility(old, new)
        assert not report.is_forward_compatible
        added = _issues_by_change(report, "added_required")
        assert len(added) == 1
        assert added[0].severity == "breaking"

    def test_add_column_without_nullable_is_safe(self):
        """Column with nullable=None is treated as fully nullable."""
        old = _umf([_col("id", "INTEGER", length=None)])
        new = _umf(
            [_col("id", "INTEGER", length=None), _col("note", "TEXT", length=None)]
        )
        report = check_compatibility(old, new)
        assert report.is_backward_compatible


class TestColumnRemoval:
    def test_remove_column_is_breaking(self):
        old = _umf([_col("id", "INTEGER", length=None), _col("name", "VARCHAR")])
        new = _umf([_col("id", "INTEGER", length=None)])
        report = check_compatibility(old, new)
        assert not report.is_backward_compatible
        removed = _issues_by_change(report, "removed")
        assert len(removed) == 1
        assert removed[0].component == "column.name"


class TestColumnRename:
    def test_rename_via_alias_is_info(self):
        old = _umf([_col("id", "INTEGER", length=None), _col("fname", "VARCHAR")])
        new = _umf(
            [
                _col("id", "INTEGER", length=None),
                _col("first_name", "VARCHAR", aliases=["fname"]),
            ]
        )
        report = check_compatibility(old, new)
        assert report.is_backward_compatible
        renamed = _issues_by_change(report, "renamed")
        assert len(renamed) == 1
        assert renamed[0].severity == "info"
        assert renamed[0].old_value == "fname"
        assert renamed[0].new_value == "first_name"
        # Should NOT be reported as removed
        assert not _issues_by_change(report, "removed")


class TestTypeWidening:
    @pytest.mark.parametrize("old_type,new_type", list(SAFE_WIDENINGS.keys()))
    def test_safe_widening_is_info(self, old_type, new_type):
        length = 50 if old_type in ("CHAR", "VARCHAR") else None
        old = _umf([_col("x", old_type, length=length)])
        new_length = 50 if new_type in ("CHAR", "VARCHAR") else None
        new = _umf([_col("x", new_type, length=new_length)])
        report = check_compatibility(old, new)
        assert report.is_backward_compatible
        widened = _issues_by_change(report, "type_widened")
        assert len(widened) == 1


class TestTypeNarrowing:
    def test_decimal_to_integer_is_breaking(self):
        old = _umf([_col("amount", "DECIMAL", length=None, precision=10, scale=2)])
        new = _umf([_col("amount", "INTEGER", length=None)])
        report = check_compatibility(old, new)
        assert not report.is_backward_compatible
        narrowed = _issues_by_change(report, "type_narrowed")
        assert len(narrowed) == 1

    def test_embedding_dimension_change_is_breaking(self):
        old = _umf([_col("embedding", "EMBEDDING", length=None, dimension=1024)])
        new = _umf([_col("embedding", "EMBEDDING", length=None, dimension=768)])
        report = check_compatibility(old, new)
        assert not report.is_backward_compatible
        dimension_issues = _issues_by_change(report, "dimension_narrowed")
        assert len(dimension_issues) == 1
        assert dimension_issues[0].old_value == 1024
        assert dimension_issues[0].new_value == 768

    def test_text_to_varchar_is_breaking(self):
        old = _umf([_col("bio", "TEXT", length=None)])
        new = _umf([_col("bio", "VARCHAR")])
        report = check_compatibility(old, new)
        assert not report.is_backward_compatible


class TestLengthChange:
    def test_varchar_widening(self):
        old = _umf([_col("name", "VARCHAR", length=50)])
        new = _umf([_col("name", "VARCHAR", length=100)])
        report = check_compatibility(old, new)
        assert report.is_backward_compatible
        assert _issues_by_change(report, "length_widened")

    def test_varchar_narrowing(self):
        old = _umf([_col("name", "VARCHAR", length=100)])
        new = _umf([_col("name", "VARCHAR", length=50)])
        report = check_compatibility(old, new)
        assert not report.is_backward_compatible
        assert _issues_by_change(report, "length_narrowed")


class TestPrecisionScaleChange:
    def test_precision_widening(self):
        old = _umf([_col("amount", "DECIMAL", length=None, precision=10, scale=2)])
        new = _umf([_col("amount", "DECIMAL", length=None, precision=18, scale=4)])
        report = check_compatibility(old, new)
        assert report.is_backward_compatible
        assert _issues_by_change(report, "precision_widened")

    def test_precision_narrowing(self):
        old = _umf([_col("amount", "DECIMAL", length=None, precision=18, scale=4)])
        new = _umf([_col("amount", "DECIMAL", length=None, precision=10, scale=2)])
        report = check_compatibility(old, new)
        assert not report.is_backward_compatible
        assert _issues_by_change(report, "precision_narrowed")


class TestNullableRelaxation:
    def test_required_to_nullable_is_safe(self):
        old = _umf([_col("x", "VARCHAR", nullable=Nullable(MD=False))])
        new = _umf([_col("x", "VARCHAR", nullable=Nullable(MD=True))])
        report = check_compatibility(old, new)
        assert report.is_backward_compatible
        relaxed = _issues_by_change(report, "nullable_relaxed")
        assert len(relaxed) == 1
        assert relaxed[0].severity == "info"


class TestNullableTightening:
    def test_nullable_to_required_is_breaking(self):
        old = _umf([_col("x", "VARCHAR", nullable=Nullable(MD=True))])
        new = _umf([_col("x", "VARCHAR", nullable=Nullable(MD=False))])
        report = check_compatibility(old, new)
        assert not report.is_backward_compatible
        tightened = _issues_by_change(report, "nullable_tightened")
        assert len(tightened) == 1
        assert tightened[0].severity == "breaking"


class TestContextAwareNullable:
    def test_tightening_one_context(self):
        """MD: true->false is breaking, MP stays false->false."""
        old = _umf([_col("x", "VARCHAR", nullable=Nullable(MD=True, MP=False))])
        new = _umf([_col("x", "VARCHAR", nullable=Nullable(MD=False, MP=False))])
        report = check_compatibility(old, new)
        assert not report.is_backward_compatible
        tightened = _issues_by_change(report, "nullable_tightened")
        assert len(tightened) == 1
        assert "MD" in tightened[0].description

    def test_new_context_added_is_info(self):
        """{MD: false} -> {MD: false, MP: true} = info (new context, no existing consumers)."""
        old = _umf([_col("x", "VARCHAR", nullable=Nullable(MD=False))])
        new = _umf([_col("x", "VARCHAR", nullable=Nullable(MD=False, MP=True))])
        report = check_compatibility(old, new)
        assert report.is_backward_compatible
        added = _issues_by_change(report, "nullable_context_added")
        assert len(added) == 1
        assert added[0].severity == "info"

    def test_multi_context_mixed(self):
        """Multiple changes across contexts."""
        old = _umf(
            [_col("x", "VARCHAR", nullable=Nullable(MD=True, MP=False, ME=True))]
        )
        new = _umf(
            [_col("x", "VARCHAR", nullable=Nullable(MD=False, MP=False, ME=True))]
        )
        report = check_compatibility(old, new)
        # MD tightened -> breaking
        assert not report.is_backward_compatible
        # MP unchanged, ME unchanged
        tightened = _issues_by_change(report, "nullable_tightened")
        assert len(tightened) == 1


class TestPrimaryKeyChanges:
    def test_pk_added(self):
        old = _umf([_col("id", "INTEGER", length=None)])
        new = _umf([_col("id", "INTEGER", length=None)], primary_key=["id"])
        report = check_compatibility(old, new)
        pk_issues = [i for i in report.issues if i.component == "table.primary_key"]
        assert len(pk_issues) == 1
        assert pk_issues[0].change == "primary_key_added"
        assert pk_issues[0].severity == "warning"

    def test_pk_removed(self):
        old = _umf([_col("id", "INTEGER", length=None)], primary_key=["id"])
        new = _umf([_col("id", "INTEGER", length=None)])
        report = check_compatibility(old, new)
        assert not report.is_backward_compatible
        pk_issues = [i for i in report.issues if i.component == "table.primary_key"]
        assert pk_issues[0].change == "primary_key_removed"

    def test_pk_changed(self):
        old = _umf(
            [_col("id", "INTEGER", length=None), _col("code", "VARCHAR")],
            primary_key=["id"],
        )
        new = _umf(
            [_col("id", "INTEGER", length=None), _col("code", "VARCHAR")],
            primary_key=["id", "code"],
        )
        report = check_compatibility(old, new)
        assert not report.is_backward_compatible
        pk_issues = [i for i in report.issues if i.component == "table.primary_key"]
        assert pk_issues[0].change == "primary_key_changed"


class TestDescriptionChange:
    def test_description_only_is_info(self):
        old = _umf([_col("id", "INTEGER", length=None, description="old")])
        new = _umf([_col("id", "INTEGER", length=None, description="new")])
        report = check_compatibility(old, new)
        assert report.is_backward_compatible
        assert report.is_forward_compatible
        desc = _issues_by_change(report, "description_changed")
        assert len(desc) == 1
        assert desc[0].severity == "info"


# ---------------------------------------------------------------------------
# Hypothesis property-based tests
# ---------------------------------------------------------------------------

# Strategy for generating a minimal UMF with random column names
_col_name_st = st.from_regex(r"[A-Za-z][A-Za-z0-9_]{0,10}", fullmatch=True)
_data_type_st = st.sampled_from(
    ["VARCHAR", "INTEGER", "DECIMAL", "DATE", "BOOLEAN", "TEXT"]
)


@st.composite
def umf_object(draw):
    """Generate a random UMF with 1-5 columns."""
    n = draw(st.integers(min_value=1, max_value=5))
    names = draw(st.lists(_col_name_st, min_size=n, max_size=n, unique=True))
    cols = []
    for name in names:
        dtype = draw(_data_type_st)
        length = (
            draw(st.integers(min_value=1, max_value=255))
            if dtype in ("VARCHAR", "CHAR")
            else None
        )
        precision = (
            draw(st.integers(min_value=1, max_value=38)) if dtype == "DECIMAL" else None
        )
        scale = (
            draw(st.integers(min_value=0, max_value=10)) if dtype == "DECIMAL" else None
        )
        cols.append(
            UMFColumn(
                name=name,
                data_type=dtype,
                length=length,
                precision=precision,
                scale=scale,
            )
        )
    return UMF(version="1.0", table_name="test_table", columns=cols)


class TestHypothesisProperties:
    @given(umf=umf_object())
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_reflexivity(self, umf):
        """check_compatibility(umf, umf) is always fully compatible with no issues."""
        report = check_compatibility(umf, umf)
        assert report.is_backward_compatible
        assert report.is_forward_compatible
        assert len(report.issues) == 0

    @given(umf=umf_object())
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_add_nullable_column_always_backward_compatible(self, umf):
        """Adding a nullable column never breaks backward compatibility."""
        new = deepcopy(umf)
        new.columns.append(
            UMFColumn(
                name="zzz_extra",
                data_type="VARCHAR",
                length=100,
                nullable=Nullable(MD=True),
            )
        )
        report = check_compatibility(umf, new)
        assert report.is_backward_compatible

    @given(umf=umf_object())
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_remove_any_column_always_breaking(self, umf):
        """Removing any column is always a breaking change."""
        if len(umf.columns) < 2:
            return  # Can't remove if only 1 column (min_length=1)
        new = deepcopy(umf)
        new.columns.pop()
        report = check_compatibility(umf, new)
        assert not report.is_backward_compatible
        assert any(i.change == "removed" for i in report.issues)


class TestSharedStrategyProperties:
    """Property-based tests using the shared umf_object strategy from tests.strategies."""

    @given(umf=shared_umf_object())
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_reflexivity_with_shared_strategy(self, umf):
        """check_compatibility(umf, umf) reports no breaking issues for any UMF."""
        report = check_compatibility(umf, umf)
        assert report.is_backward_compatible
        assert report.is_forward_compatible
        assert len(report.issues) == 0
