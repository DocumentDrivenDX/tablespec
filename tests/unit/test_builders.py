# @covers US-029-AC1
"""Unit tests for UMFBuilder DSL."""

from __future__ import annotations

import pytest

from tablespec.models.umf import Nullable, UMF, UMFColumn
from tests.builders import UMFBuilder

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


class TestBuilderProducesValidUMF:
    """Builder output passes Pydantic validation."""

    def test_minimal_build(self):
        umf = UMFBuilder("test_table").column("id", "INTEGER").build()
        assert isinstance(umf, UMF)
        assert umf.table_name == "test_table"
        assert umf.version == "1.0"
        assert len(umf.columns) == 1

    def test_custom_version(self):
        umf = UMFBuilder("t", version="2.0").column("x", "INTEGER").build()
        assert umf.version == "2.0"


class TestBuildAndAsDictEquivalence:
    """build().model_dump() is structurally equivalent to as_dict()."""

    def test_equivalence(self):
        builder = (
            UMFBuilder("equiv_table")
            .column("id", "INTEGER")
            .column("name", "VARCHAR", length=50)
            .description("Test table")
        )
        from_build = builder.build().model_dump(exclude_none=True)
        from_dict = builder.as_dict()
        assert from_build == from_dict

    def test_equivalence_with_relationships(self):
        builder = (
            UMFBuilder("fk_table")
            .column("id", "INTEGER")
            .column("ref_id", "INTEGER")
            .foreign_key("ref_id", references="other_table.id", confidence=0.9)
        )
        from_build = builder.build().model_dump(exclude_none=True)
        from_dict = builder.as_dict()
        assert from_build == from_dict


class TestColumnTypes:
    """Builder supports all common column types."""

    def test_varchar_with_length(self):
        umf = UMFBuilder("t").column("name", "VARCHAR", length=100).build()
        assert umf.columns[0].data_type == "VARCHAR"
        assert umf.columns[0].length == 100

    def test_decimal_with_precision_scale(self):
        umf = UMFBuilder("t").column("amount", "DECIMAL", precision=10, scale=2).build()
        col = umf.columns[0]
        assert col.data_type == "DECIMAL"
        assert col.precision == 10
        assert col.scale == 2

    def test_integer(self):
        umf = UMFBuilder("t").column("count", "INTEGER").build()
        assert umf.columns[0].data_type == "INTEGER"

    def test_date(self):
        umf = UMFBuilder("t").column("dob", "DATE").build()
        assert umf.columns[0].data_type == "DATE"

    def test_boolean(self):
        umf = UMFBuilder("t").column("active", "BOOLEAN").build()
        assert umf.columns[0].data_type == "BOOLEAN"

    def test_datetime(self):
        umf = UMFBuilder("t").column("ts", "DATETIME").build()
        assert umf.columns[0].data_type == "DATETIME"

    def test_float(self):
        umf = UMFBuilder("t").column("rate", "FLOAT").build()
        assert umf.columns[0].data_type == "FLOAT"

    def test_text(self):
        umf = UMFBuilder("t").column("notes", "TEXT").build()
        assert umf.columns[0].data_type == "TEXT"

    def test_char(self):
        umf = UMFBuilder("t").column("code", "CHAR", length=2).build()
        assert umf.columns[0].data_type == "CHAR"
        assert umf.columns[0].length == 2


class TestPrimaryKey:
    """primary_key sets the field correctly."""

    def test_single_primary_key(self):
        umf = (
            UMFBuilder("t")
            .column("id", "INTEGER")
            .column("name", "VARCHAR")
            .primary_key("id")
            .build()
        )
        assert umf.primary_key == ["id"]

    def test_compound_primary_key(self):
        umf = (
            UMFBuilder("t")
            .column("a", "INTEGER")
            .column("b", "INTEGER")
            .primary_key("a", "b")
            .build()
        )
        assert umf.primary_key == ["a", "b"]


class TestForeignKey:
    """foreign_key adds to relationships."""

    def test_single_foreign_key(self):
        umf = (
            UMFBuilder("t")
            .column("id", "INTEGER")
            .column("ref_id", "INTEGER")
            .foreign_key("ref_id", references="other.id")
            .build()
        )
        assert umf.relationships is not None
        fks = umf.relationships.foreign_keys
        assert fks is not None
        assert len(fks) == 1
        assert fks[0].column == "ref_id"
        assert fks[0].references_table == "other"
        assert fks[0].references_column == "id"

    def test_foreign_key_with_confidence(self):
        umf = (
            UMFBuilder("t")
            .column("ref_id", "INTEGER")
            .foreign_key("ref_id", references="other.id", confidence=0.85)
            .build()
        )
        assert umf.relationships.foreign_keys[0].confidence == 0.85

    def test_multiple_foreign_keys(self):
        umf = (
            UMFBuilder("t")
            .column("a_id", "INTEGER")
            .column("b_id", "INTEGER")
            .foreign_key("a_id", references="table_a.id")
            .foreign_key("b_id", references="table_b.id")
            .build()
        )
        assert len(umf.relationships.foreign_keys) == 2

    def test_no_relationships_when_no_fks(self):
        umf = UMFBuilder("t").column("id", "INTEGER").build()
        assert umf.relationships is None

    def test_invalid_references_format(self):
        builder = UMFBuilder("t").column("id", "INTEGER")
        with pytest.raises(ValueError, match="table.column"):
            builder.foreign_key("id", references="no_dot_here")


class TestDuplicateColumnNames:
    """Duplicate column names raise ValueError."""

    def test_duplicate_raises(self):
        builder = UMFBuilder("t").column("id", "INTEGER")
        with pytest.raises(ValueError, match="Duplicate column name"):
            builder.column("id", "VARCHAR")


class TestMethodChaining:
    """Method chaining works for all builder methods."""

    def test_full_chain(self):
        umf = (
            UMFBuilder("chained")
            .description("A chained table")
            .table_type("data_table")
            .column("id", "INTEGER", key_type="primary")
            .column("name", "VARCHAR", length=50, description="Full name")
            .column("amount", "DECIMAL", precision=10, scale=2)
            .column("active", "BOOLEAN")
            .column("ref_id", "INTEGER")
            .primary_key("id")
            .foreign_key("ref_id", references="other.id", confidence=0.9)
            .build()
        )
        assert isinstance(umf, UMF)
        assert umf.table_name == "chained"
        assert umf.description == "A chained table"
        assert umf.table_type == "data_table"
        assert len(umf.columns) == 5
        assert umf.primary_key == ["id"]
        assert umf.relationships is not None
        assert len(umf.relationships.foreign_keys) == 1

    def test_each_method_returns_builder(self):
        b = UMFBuilder("t")
        assert isinstance(b.column("x", "INTEGER"), UMFBuilder)
        b2 = UMFBuilder("t2").column("y", "INTEGER")
        assert isinstance(b2.primary_key("y"), UMFBuilder)
        assert isinstance(b2.description("d"), UMFBuilder)
        assert isinstance(b2.table_type("lookup_table"), UMFBuilder)
        b3 = UMFBuilder("t3").column("z", "INTEGER")
        assert isinstance(b3.foreign_key("z", references="o.id"), UMFBuilder)


class TestNullable:
    """Nullable can be bool, dict, or Nullable object."""

    def test_nullable_bool_true(self):
        umf = UMFBuilder("t").column("x", "VARCHAR", nullable=True).build()
        assert umf.columns[0].nullable is not None
        # Bool is stored as Nullable with "default" key
        dump = umf.columns[0].nullable.model_dump()
        assert dump["default"] is True

    def test_nullable_bool_false(self):
        umf = UMFBuilder("t").column("x", "VARCHAR", nullable=False).build()
        dump = umf.columns[0].nullable.model_dump()
        assert dump["default"] is False

    def test_nullable_dict(self):
        umf = (
            UMFBuilder("t")
            .column("x", "VARCHAR", nullable={"MD": False, "MP": True})
            .build()
        )
        n = umf.columns[0].nullable
        assert n.model_dump() == {"MD": False, "MP": True}

    def test_nullable_object(self):
        n = Nullable(MD=False, ME=True)
        umf = UMFBuilder("t").column("x", "VARCHAR", nullable=n).build()
        assert umf.columns[0].nullable is n

    def test_nullable_none_by_default(self):
        umf = UMFBuilder("t").column("x", "VARCHAR").build()
        assert umf.columns[0].nullable is None


class TestColumnExtras:
    """Builder passes through optional column fields."""

    def test_description_and_sample_values(self):
        umf = (
            UMFBuilder("t")
            .column(
                "state",
                "VARCHAR",
                length=2,
                description="US state code",
                sample_values=["CA", "NY", "TX"],
                domain_type="us_state_code",
            )
            .build()
        )
        col = umf.columns[0]
        assert col.description == "US state code"
        assert col.sample_values == ["CA", "NY", "TX"]
        assert col.domain_type == "us_state_code"

    def test_format_and_source(self):
        umf = (
            UMFBuilder("t")
            .column("dob", "DATE", format="YYYY-MM-DD", source="data")
            .build()
        )
        col = umf.columns[0]
        assert col.format == "YYYY-MM-DD"
        assert col.source == "data"

    def test_key_type(self):
        umf = UMFBuilder("t").column("id", "INTEGER", key_type="primary").build()
        assert umf.columns[0].key_type == "primary"


class TestTableMetadata:
    """description() and table_type() set fields correctly."""

    def test_description(self):
        umf = UMFBuilder("t").column("x", "INTEGER").description("My table").build()
        assert umf.description == "My table"

    def test_table_type(self):
        umf = UMFBuilder("t").column("x", "INTEGER").table_type("lookup_table").build()
        assert umf.table_type == "lookup_table"


class TestReproduceUMFDiffFixture:
    """Reproduce the _make_umf fixture from test_umf_diff.py and verify equivalence."""

    def test_equivalent_to_make_umf_default(self):
        """Builder produces same structure as _make_umf() default."""
        # Original from test_umf_diff.py:
        # _make_umf() -> UMF(version="1.0", table_name="test_table",
        #   columns=[UMFColumn(name="col1", data_type="VARCHAR", length=50)])
        from_builder = (
            UMFBuilder("test_table").column("col1", "VARCHAR", length=50).build()
        )
        from_direct = UMF(
            version="1.0",
            table_name="test_table",
            columns=[UMFColumn(name="col1", data_type="VARCHAR", length=50)],
        )
        assert from_builder.model_dump() == from_direct.model_dump()

    def test_equivalent_to_make_umf_with_description(self):
        """Builder matches _make_umf(description=..., table_type=...)."""
        from_builder = (
            UMFBuilder("test_table")
            .column("col1", "VARCHAR", length=50)
            .description("old desc")
            .table_type("provided")
            .build()
        )
        from_direct = UMF(
            version="1.0",
            table_name="test_table",
            columns=[UMFColumn(name="col1", data_type="VARCHAR", length=50)],
            description="old desc",
            table_type="provided",
        )
        assert from_builder.model_dump() == from_direct.model_dump()

    def test_equivalent_multi_column(self):
        """Builder matches _make_umf with multiple columns."""
        from_builder = (
            UMFBuilder("test_table")
            .column("col1", "VARCHAR", length=50)
            .column("col2", "INTEGER", description="second column")
            .build()
        )
        from_direct = UMF(
            version="1.0",
            table_name="test_table",
            columns=[
                UMFColumn(name="col1", data_type="VARCHAR", length=50),
                UMFColumn(
                    name="col2", data_type="INTEGER", description="second column"
                ),
            ],
        )
        assert from_builder.model_dump() == from_direct.model_dump()
