"""Unit tests for UMF Pydantic models."""

# @covers US-002-AC1
# @covers US-002-AC2
# @covers US-002-AC3
# @covers US-002-AC4

from __future__ import annotations

from pydantic import ValidationError
import pytest
from hypothesis import given, settings

from tablespec.models.umf import (
    UMF,
    DerivationCandidate,
    ForeignKey,
    Nullable,
    Survivorship,
    UMFColumn,
    UMFColumnDerivation,
)
from tests.strategies import umf_object

pytestmark = pytest.mark.no_spark


class TestNullable:
    """Test Nullable model."""

    def test_creates_nullable_with_all_lobs(self):
        """Test creating Nullable with all LOBs."""
        nullable = Nullable(MD=False, MP=True, ME=False)
        assert nullable.MD is False
        assert nullable.MP is True
        assert nullable.ME is False

    def test_allows_none_values(self):
        """Test Nullable allows None for LOBs."""
        nullable = Nullable(MD=None, MP=None, ME=None)
        assert nullable.MD is None
        assert nullable.MP is None
        assert nullable.ME is None

    def test_partial_nullable_specification(self):
        """Test can specify only some LOBs."""
        nullable = Nullable(MD=False, MP=None, ME=None)
        assert nullable.MD is False
        assert nullable.MP is None

    def test_nullable_custom_contexts(self):
        """Test Nullable with arbitrary custom context keys."""
        nullable = Nullable(US=False, EU=True)
        assert nullable.US is False
        assert nullable.EU is True

    def test_nullable_mixed_contexts(self):
        """Test Nullable with both standard and custom keys."""
        nullable = Nullable(MD=False, MP=True, US=False, EU=True)
        assert nullable.MD is False
        assert nullable.MP is True
        assert nullable.US is False
        assert nullable.EU is True

    def test_nullable_model_dump_excludes_none(self):
        """Test model_dump(exclude_none=True) only includes set fields."""
        nullable = Nullable(MD=False, EU=True)
        dumped = nullable.model_dump(exclude_none=True)
        assert dumped == {"MD": False, "EU": True}

        # Empty Nullable should dump to empty dict
        nullable_empty = Nullable()
        dumped_empty = nullable_empty.model_dump(exclude_none=True)
        assert dumped_empty == {}

    def test_is_nullable_for_all_contexts_custom(self):
        """Test is_nullable_for_all_contexts with custom context keys on a UMFColumn."""
        # All custom contexts nullable -> True
        col_all_nullable = UMFColumn(
            name="test_col",
            data_type="VARCHAR",
            nullable=Nullable(US=True, EU=True),
        )
        assert col_all_nullable.is_nullable_for_all_contexts() is True

        # One custom context non-nullable -> False
        col_mixed = UMFColumn(
            name="test_col",
            data_type="VARCHAR",
            nullable=Nullable(US=False, EU=True),
        )
        assert col_mixed.is_nullable_for_all_contexts() is False
        assert col_mixed.is_required_for_any_context() is True

        # Mix of standard and custom contexts
        col_standard_custom = UMFColumn(
            name="test_col",
            data_type="VARCHAR",
            nullable=Nullable(MD=False, production=True),
        )
        assert col_standard_custom.is_nullable_for_all_contexts() is False


class TestDerivationCandidate:
    """Test DerivationCandidate model."""

    def test_creates_candidate(self):
        """Test creating derivation candidate."""
        candidate = DerivationCandidate(
            table="outreach_list", column="birth_date", priority=1
        )
        assert candidate.table == "outreach_list"
        assert candidate.column == "birth_date"
        assert candidate.priority == 1

    def test_validates_priority_positive(self):
        """Test priority must be >= 1."""
        with pytest.raises(ValidationError):
            DerivationCandidate(table="test", column="col1", priority=0)


class TestSurvivorship:
    """Test Survivorship model."""

    def test_creates_survivorship(self):
        """Test creating survivorship strategy."""
        survivorship = Survivorship(
            strategy="highest_priority",
            explanation="Use value from highest priority source",
        )
        assert survivorship.strategy == "highest_priority"
        assert survivorship.explanation == "Use value from highest priority source"

    def test_allows_none_description(self):
        """Test explanation is required."""
        survivorship = Survivorship(
            strategy="most_recent", explanation="Use most recent value"
        )
        assert survivorship.strategy == "most_recent"
        assert survivorship.explanation == "Use most recent value"


class TestUMFColumnDerivation:
    """Test UMFColumnDerivation model."""

    def test_creates_derivation(self):
        """Test creating column derivation."""
        derivation = UMFColumnDerivation(
            candidates=[
                DerivationCandidate(table="source1", column="col1", priority=1),
                DerivationCandidate(table="source2", column="col1", priority=2),
            ],
            survivorship=Survivorship(
                strategy="highest_priority", explanation="Use first available value"
            ),
        )
        assert len(derivation.candidates) == 2
        assert derivation.candidates[0].priority == 1
        assert derivation.survivorship.strategy == "highest_priority"

    def test_requires_at_least_one_candidate(self):
        """Test derivation must have at least one candidate."""
        with pytest.raises(ValidationError):
            UMFColumnDerivation(candidates=[])

    def test_allows_none_survivorship(self):
        """Test survivorship is optional."""
        derivation = UMFColumnDerivation(
            candidates=[DerivationCandidate(table="source1", column="col1", priority=1)]
        )
        assert len(derivation.candidates) == 1
        assert derivation.survivorship is None

    def test_allows_derivation_with_only_survivorship(self):
        """Test derivation can have only survivorship without candidates (enterprise-only fields)."""
        derivation = UMFColumnDerivation(
            survivorship=Survivorship(
                strategy="none",
                explanation="Enterprise-only field with no source candidates",
            )
        )
        assert derivation.candidates is None
        assert derivation.survivorship.strategy == "none"


class TestUMFColumn:
    """Test UMFColumn model."""

    def test_creates_minimal_column(self):
        """Test creating column with required fields only."""
        col = UMFColumn(name="test_col", data_type="VARCHAR")
        assert col.name == "test_col"
        assert col.data_type == "VARCHAR"

    def test_validates_column_name_pattern(self):
        """Test column name must start with letter."""
        with pytest.raises(ValidationError):
            UMFColumn(name="123invalid", data_type="VARCHAR")

        with pytest.raises(ValidationError):
            UMFColumn(name="_invalid", data_type="VARCHAR")

    def test_allows_valid_column_names(self):
        """Test valid column name patterns."""
        valid_names = ["col1", "MyColumn", "col_name_123", "ABC"]
        for name in valid_names:
            col = UMFColumn(name=name, data_type="VARCHAR")
            assert col.name == name

    def test_validates_data_type_enum(self):
        """Test data_type must be valid UMF type."""
        valid_types = [
            "VARCHAR",
            "DECIMAL",
            "INTEGER",
            "DATE",
            "DATETIME",
            "TIMESTAMP",
            "BOOLEAN",
            "FLOAT",
            "TEXT",
            "CHAR",
            "EMBEDDING",
        ]
        for dtype in valid_types:
            kwargs = {"name": "test", "data_type": dtype}
            if dtype == "EMBEDDING":
                kwargs["dimension"] = 8
            col = UMFColumn(**kwargs)
            assert col.data_type == dtype

    def test_rejects_invalid_data_type(self):
        """Test invalid data types are rejected."""
        with pytest.raises(ValidationError):
            UMFColumn(name="test", data_type="INVALID_TYPE")

    def test_column_with_all_fields(self):
        """Test column with all optional fields."""
        col = UMFColumn(
            name="customer_id",
            data_type="INTEGER",
            position="A",
            description="Unique customer identifier",
            nullable=Nullable(MD=False, MP=False, ME=False),
            sample_values=["1", "2", "3"],
            title="Customer ID",
            format="Numeric",
            notes=["Primary key", "Auto-incremented"],
        )

        assert col.name == "customer_id"
        assert col.description == "Unique customer identifier"
        assert col.sample_values == ["1", "2", "3"]
        assert col.nullable.MD is False
        assert len(col.notes) == 2

    def test_string_with_length(self):
        """Test StringType column with length."""
        col = UMFColumn(name="name", data_type="VARCHAR", length=255)
        assert col.length == 255

    def test_decimal_with_precision_and_scale(self):
        """Test DecimalType column with precision and scale."""
        col = UMFColumn(name="amount", data_type="DECIMAL", precision=10, scale=2)
        assert col.precision == 10
        assert col.scale == 2

    def test_validates_length_positive(self):
        """Test length must be positive."""
        with pytest.raises(ValidationError):
            UMFColumn(name="test", data_type="VARCHAR", length=0)

        with pytest.raises(ValidationError):
            UMFColumn(name="test", data_type="VARCHAR", length=-1)

    def test_validates_precision_positive(self):
        """Test precision must be positive."""
        with pytest.raises(ValidationError):
            UMFColumn(name="test", data_type="DECIMAL", precision=0)

    def test_validates_scale_non_negative(self):
        """Test scale must be non-negative."""
        with pytest.raises(ValidationError):
            UMFColumn(name="test", data_type="DECIMAL", precision=10, scale=-1)

        # Scale 0 should be valid
        col = UMFColumn(name="test", data_type="DECIMAL", precision=10, scale=0)
        assert col.scale == 0

    def test_embedding_requires_dimension(self):
        """Test EMBEDDING columns require a dimension."""
        with pytest.raises(ValidationError):
            UMFColumn(name="embedding", data_type="EMBEDDING")

    def test_dimension_rejected_for_non_embedding(self):
        """Test dimension is rejected on non-embedding columns."""
        with pytest.raises(ValidationError):
            UMFColumn(name="name", data_type="VARCHAR", dimension=3)

    def test_embedding_accepts_dimension(self):
        """Test EMBEDDING columns accept a dimension."""
        col = UMFColumn(name="embedding", data_type="EMBEDDING", dimension=1024)
        assert col.dimension == 1024

    def test_column_with_derivation(self):
        """Test column with derivation metadata."""
        col = UMFColumn(
            name="birth_date",
            data_type="DATE",
            derivation=UMFColumnDerivation(
                candidates=[
                    DerivationCandidate(
                        table="outreach_list", column="birth_date", priority=1
                    ),
                    DerivationCandidate(
                        table="outreach_list_diags", column="birth_date", priority=2
                    ),
                ],
                survivorship=Survivorship(
                    strategy="highest_priority",
                    explanation="Use DOB from outreach list; fallback to diags",
                ),
            ),
        )
        assert col.name == "birth_date"
        assert col.derivation is not None
        assert len(col.derivation.candidates) == 2
        assert col.derivation.candidates[0].table == "outreach_list"
        assert col.derivation.survivorship.strategy == "highest_priority"

    def test_column_with_provenance_and_pivot(self):
        """Test column with provenance policy and pivot metadata."""
        col = UMFColumn(
            name="tgt_qlty_gap1",
            data_type="VARCHAR",
            length=15,
            provenance_policy="outreach_only",
            provenance_notes="Quality gaps only tracked in outreach files",
            pivot_field=True,
            pivot_index=1,
            pivot_max_count=6,
            pivot_source_table="outreach_list_gaps",
            pivot_source_column="quality_gap_group",
        )
        assert col.name == "tgt_qlty_gap1"
        assert col.provenance_policy == "outreach_only"
        assert col.provenance_notes == "Quality gaps only tracked in outreach files"
        assert col.pivot_field is True
        assert col.pivot_index == 1
        assert col.pivot_max_count == 6
        assert col.pivot_source_table == "outreach_list_gaps"
        assert col.pivot_source_column == "quality_gap_group"

    def test_validates_provenance_policy_enum(self):
        """Test provenance_policy must be valid enum value."""
        valid_policies = [
            "enterprise_only",
            "enterprise_preferred",
            "outreach_only",
            "survivorship",
        ]
        for policy in valid_policies:
            col = UMFColumn(name="test", data_type="VARCHAR", provenance_policy=policy)
            assert col.provenance_policy == policy

        # Invalid policy should fail
        with pytest.raises(ValidationError):
            UMFColumn(
                name="test", data_type="VARCHAR", provenance_policy="invalid_policy"
            )

    def test_validates_pivot_index_positive(self):
        """Test pivot_index must be >= 1."""
        col = UMFColumn(name="test", data_type="VARCHAR", pivot_index=1)
        assert col.pivot_index == 1

        with pytest.raises(ValidationError):
            UMFColumn(name="test", data_type="VARCHAR", pivot_index=0)

    def test_validates_pivot_max_count_positive(self):
        """Test pivot_max_count must be >= 1."""
        col = UMFColumn(name="test", data_type="VARCHAR", pivot_max_count=6)
        assert col.pivot_max_count == 6

        with pytest.raises(ValidationError):
            UMFColumn(name="test", data_type="VARCHAR", pivot_max_count=0)


class TestForeignKey:
    """Test ForeignKey model."""

    def test_creates_foreign_key(self):
        """Test creating foreign key relationship."""
        fk = ForeignKey(
            column="customer_id",
            references_table="Customers",
            references_column="id",
        )

        assert fk.column == "customer_id"
        assert fk.references_table == "Customers"
        assert fk.references_column == "id"

    def test_foreign_key_with_confidence(self):
        """Test foreign key with confidence score."""
        fk = ForeignKey(
            column="customer_id",
            references_table="Customers",
            references_column="id",
            confidence=0.95,
        )

        assert fk.confidence == 0.95

    def test_validates_confidence_range(self):
        """Test confidence must be between 0 and 1."""
        with pytest.raises(ValidationError):
            ForeignKey(
                column="test",
                references_table="Test",
                references_column="id",
                confidence=1.5,
            )

        with pytest.raises(ValidationError):
            ForeignKey(
                column="test",
                references_table="Test",
                references_column="id",
                confidence=-0.1,
            )

    def test_parses_legacy_references_format(self):
        """Test parsing legacy 'table.column' format."""
        # The legacy parsing requires references_table and references_column to be provided
        # The validator parses the 'references' field if the others are missing
        fk = ForeignKey(
            column="customer_id",
            references_table="Customers",
            references_column="id",
            references="Customers.id",  # Legacy field
        )

        # Should have both formats
        assert fk.references_table == "Customers"
        assert fk.references_column == "id"
        assert fk.references == "Customers.id"

    def test_join_type_defaults_to_none(self):
        """Test that join_type defaults to None (LEFT JOIN behavior)."""
        fk = ForeignKey(
            column="member_id",
            references_table="other_table",
            references_column="member_id",
        )
        assert fk.join_type is None

    def test_join_type_inner(self):
        """Test that join_type='inner' is accepted."""
        fk = ForeignKey(
            column="member_id",
            references_table="other_table",
            references_column="member_id",
            join_type="inner",
        )
        assert fk.join_type == "inner"

    def test_cross_pipeline_defaults_to_false(self):
        """Test cross_pipeline field defaults to False."""
        fk = ForeignKey(
            column="member_id",
            references_table="members",
            references_column="id",
        )

        assert fk.cross_pipeline is False
        assert fk.references_pipeline is None

    def test_cross_pipeline_reference(self):
        """Test creating a cross-pipeline foreign key reference."""
        fk = ForeignKey(
            column="client_member_id",
            references_table="provided",
            references_column="client_member_id",
            cross_pipeline=True,
            references_pipeline="hc_2026_ent",
        )

        assert fk.column == "client_member_id"
        assert fk.references_table == "provided"
        assert fk.cross_pipeline is True
        assert fk.references_pipeline == "hc_2026_ent"


class TestUMF:
    """Test UMF main model."""

    @pytest.fixture
    def minimal_umf_data(self):
        """Minimal valid UMF data."""
        return {
            "version": "1.0",
            "table_name": "test_table",
            "canonical_name": "TestTable",
            "columns": [
                {"name": "id", "data_type": "INTEGER"},
            ],
        }

    @pytest.fixture
    def full_umf_data(self):
        """Full UMF data with all features."""
        return {
            "version": "1.0",
            "table_name": "medical_claims",
            "canonical_name": "MedicalClaims",
            "source_file": "claims_spec.xlsx",
            "sheet_name": "Medical Claims",
            "description": "Healthcare claims and billing information",
            "table_type": "data_table",
            "columns": [
                {
                    "name": "claim_id",
                    "data_type": "VARCHAR",
                    "length": 50,
                    "description": "Unique claim identifier",
                    "nullable": {"MD": False, "MP": False, "ME": False},
                },
                {
                    "name": "claim_amount",
                    "data_type": "DECIMAL",
                    "precision": 10,
                    "scale": 2,
                    "nullable": {"MD": True, "MP": True, "ME": True},
                },
            ],
            "validation_rules": {
                "expectations": [
                    {
                        "type": "expect_column_values_to_be_unique",
                        "kwargs": {"column": "claim_id"},
                        "meta": {"description": "claim_id must be unique"},
                    }
                ]
            },
            "relationships": {
                "foreign_keys": [
                    {
                        "column": "provider_id",
                        "references_table": "Providers",
                        "references_column": "id",
                        "confidence": 0.95,
                    }
                ]
            },
            "metadata": {
                "created_by": "data-platform-team",
                "pipeline_phase": 4,
            },
        }

    def test_creates_minimal_umf(self, minimal_umf_data):
        """Test creating minimal UMF model."""
        umf = UMF(**minimal_umf_data)

        assert umf.version == "1.0"
        assert umf.table_name == "test_table"
        assert len(umf.columns) == 1

    def test_creates_full_umf(self, full_umf_data):
        """Test creating full UMF model with all features."""
        umf = UMF(**full_umf_data)

        assert umf.table_name == "medical_claims"
        assert umf.description == "Healthcare claims and billing information"
        assert len(umf.columns) == 2
        assert umf.validation_rules is not None
        assert umf.relationships is not None
        assert umf.metadata.pipeline_phase == 4

    def test_validates_version_format(self):
        """Test version must be in X.Y format."""
        with pytest.raises(ValidationError):
            UMF(
                version="invalid",
                table_name="test",
                canonical_name="Test",
                columns=[{"name": "col1", "data_type": "STRING"}],
            )

    def test_allows_valid_version_formats(self):
        """Test valid version formats."""
        valid_versions = ["1.0", "2.0", "1.5", "10.25"]
        for version in valid_versions:
            umf = UMF(
                version=version,
                table_name="test",
                canonical_name="Test",
                columns=[{"name": "col1", "data_type": "VARCHAR"}],
            )
            assert umf.version == version

    def test_validates_table_name_pattern(self):
        """Test table name must follow naming rules."""
        with pytest.raises(ValidationError):
            UMF(
                version="1.0",
                table_name="123_invalid",
                columns=[{"name": "col1", "data_type": "VARCHAR"}],
            )

    def test_requires_at_least_one_column(self):
        """Test UMF must have at least one column."""
        with pytest.raises(ValidationError):
            UMF(version="1.0", table_name="test", canonical_name="Test", columns=[])

    def test_validates_unique_column_names(self):
        """Test column names must be unique."""
        with pytest.raises(ValidationError) as exc_info:
            UMF(
                version="1.0",
                table_name="test",
                canonical_name="Test",
                columns=[
                    {"name": "duplicate", "data_type": "VARCHAR"},
                    {"name": "duplicate", "data_type": "INTEGER"},
                ],
            )
        assert "Column names must be unique" in str(exc_info.value)

    def test_allows_different_column_names(self):
        """Test different column names are allowed."""
        umf = UMF(
            version="1.0",
            table_name="test",
            canonical_name="Test",
            columns=[
                {"name": "col1", "data_type": "VARCHAR"},
                {"name": "col2", "data_type": "INTEGER"},
            ],
        )
        assert len(umf.columns) == 2

    def test_forbids_extra_fields(self):
        """Test model forbids extra fields not in schema."""
        with pytest.raises(ValidationError):
            UMF(
                version="1.0",
                table_name="test",
                canonical_name="Test",
                columns=[{"name": "col1", "data_type": "VARCHAR"}],
                extra_field="not_allowed",
            )

    def test_metadata_pipeline_phase_range(self):
        """Test pipeline_phase must be between 1 and 7."""
        with pytest.raises(ValidationError):
            UMF(
                version="1.0",
                table_name="test",
                canonical_name="Test",
                columns=[{"name": "col1", "data_type": "VARCHAR"}],
                metadata={"pipeline_phase": 0},
            )

        with pytest.raises(ValidationError):
            UMF(
                version="1.0",
                table_name="test",
                canonical_name="Test",
                columns=[{"name": "col1", "data_type": "VARCHAR"}],
                metadata={"pipeline_phase": 8},
            )

        # Valid phases
        for phase in range(1, 8):
            umf = UMF(
                version="1.0",
                table_name="test",
                canonical_name="Test",
                columns=[{"name": "col1", "data_type": "VARCHAR"}],
                metadata={"pipeline_phase": phase},
            )
            assert umf.metadata.pipeline_phase == phase

    def test_serializes_to_dict(self, full_umf_data):
        """Test UMF can be serialized to dict."""
        umf = UMF(**full_umf_data)
        data = umf.model_dump()

        assert data["version"] == "1.0"
        assert data["table_name"] == "medical_claims"
        assert isinstance(data, dict)

    def test_dict_exclude_none(self, minimal_umf_data):
        """Test exclude_none removes None values."""
        umf = UMF(**minimal_umf_data)
        data = umf.model_dump(exclude_none=True)

        # Optional fields should not be present
        assert "description" not in data
        assert "source_file" not in data
        assert "validation_rules" not in data


class TestPropertyBasedUMFEmbedding:
    """Property-based tests for UMF model roundtrip."""

    @given(umf=umf_object())
    @settings(max_examples=50, deadline=None)
    def test_roundtrip_model_dump_and_reconstruct(self, umf):
        """Any UMF from umf_object() round-trips through model_dump/reconstruct."""
        data = umf.model_dump()
        reconstructed = UMF(**data)

        assert reconstructed.version == umf.version
        assert reconstructed.table_name == umf.table_name
        assert len(reconstructed.columns) == len(umf.columns)

        for orig_col, new_col in zip(umf.columns, reconstructed.columns):
            assert new_col.name == orig_col.name
            assert new_col.data_type == orig_col.data_type
            assert new_col.length == orig_col.length
            assert new_col.precision == orig_col.precision
            assert new_col.scale == orig_col.scale
            assert new_col.nullable == orig_col.nullable
            assert new_col.description == orig_col.description


class TestPropertyBasedUMF:
    """Property-based tests for UMF model roundtrip."""

    @given(umf=umf_object())
    @settings(max_examples=50, deadline=None)
    def test_roundtrip_model_dump_and_reconstruct(self, umf):
        """Any UMF from umf_object() round-trips through model_dump/reconstruct."""
        data = umf.model_dump()
        reconstructed = UMF(**data)

        assert reconstructed.version == umf.version
        assert reconstructed.table_name == umf.table_name
        assert len(reconstructed.columns) == len(umf.columns)

        for orig_col, new_col in zip(umf.columns, reconstructed.columns):
            assert new_col.name == orig_col.name
            assert new_col.data_type == orig_col.data_type
            assert new_col.length == orig_col.length
            assert new_col.precision == orig_col.precision
            assert new_col.scale == orig_col.scale
            assert new_col.nullable == orig_col.nullable
            assert new_col.description == orig_col.description


class TestDeprecationWarnings:
    """Test that legacy fields emit DeprecationWarning per ADR-005 Phase C."""

    def test_validation_rules_emits_warning(self):
        from tablespec.models.umf import ValidationRules

        with pytest.warns(
            DeprecationWarning, match="UMF.validation_rules is deprecated"
        ):
            UMF(
                version="1.0",
                table_name="test",
                columns=[UMFColumn(name="id", data_type="INTEGER")],
                validation_rules=ValidationRules(expectations=[]),
            )

    def test_quality_checks_emits_warning(self):
        from tablespec.models.umf import QualityChecks

        with pytest.warns(DeprecationWarning, match="UMF.quality_checks is deprecated"):
            UMF(
                version="1.0",
                table_name="test",
                columns=[UMFColumn(name="id", data_type="INTEGER")],
                quality_checks=QualityChecks(checks=[]),
            )

    def test_expectations_field_does_not_warn(self):
        import warnings as _warnings

        from tablespec.models.umf import ExpectationSuite

        with _warnings.catch_warnings():
            _warnings.simplefilter("error", DeprecationWarning)
            UMF(
                version="1.0",
                table_name="test",
                columns=[UMFColumn(name="id", data_type="INTEGER")],
                expectations=ExpectationSuite(expectations=[]),
            )

    def test_no_expectation_fields_does_not_warn(self):
        import warnings as _warnings

        with _warnings.catch_warnings():
            _warnings.simplefilter("error", DeprecationWarning)
            UMF(
                version="1.0",
                table_name="test",
                columns=[UMFColumn(name="id", data_type="INTEGER")],
            )


class TestMergeCondition:
    """Test MergeCondition and column-level merge fields."""

    def test_merge_condition_model(self):
        from tablespec.models.umf import MergeCondition

        cond = MergeCondition(column="load_mode", values=["I", "A"])
        assert cond.column == "load_mode"
        assert cond.values == ["I", "A"]

    def test_column_merge_strategy_fields(self):
        from tablespec.models.umf import MergeCondition

        col = UMFColumn(
            name="chase_load_date",
            data_type="DATE",
            merge_strategy="keep_minimum",
            merge_source="file_date_yyyymmdd",
            merge_condition=MergeCondition(column="load_mode", values=["I"]),
        )
        assert col.merge_strategy == "keep_minimum"
        assert col.merge_source == "file_date_yyyymmdd"
        assert col.merge_condition is not None
        assert col.merge_condition.values == ["I"]

    def test_merge_strategy_defaults_to_none(self):
        col = UMFColumn(name="a", data_type="VARCHAR")
        assert col.merge_strategy is None
        assert col.merge_source is None
        assert col.merge_condition is None

    def test_invalid_merge_strategy_rejected(self):
        with pytest.raises(ValidationError):
            UMFColumn(name="a", data_type="VARCHAR", merge_strategy="not_a_strategy")


class TestInternalColumn:
    """Test the internal helper-column flag."""

    def test_internal_defaults_false(self):
        assert UMFColumn(name="a", data_type="VARCHAR").internal is False

    def test_internal_column(self):
        col = UMFColumn(name="winning_row_anchor", data_type="VARCHAR", internal=True)
        assert col.internal is True


class TestBooleanNullable:
    """Test that nullable accepts plain booleans alongside Nullable contexts."""

    def test_nullable_true(self):
        col = UMFColumn(name="a", data_type="VARCHAR", nullable=True)
        assert col.is_nullable_for_all_contexts() is True
        assert col.is_required_for_any_context() is False

    def test_nullable_false(self):
        col = UMFColumn(name="a", data_type="VARCHAR", nullable=False)
        assert col.is_nullable_for_all_contexts() is False
        assert col.is_required_for_any_context() is True

    def test_nullable_model_still_works(self):
        col = UMFColumn(
            name="a", data_type="VARCHAR", nullable=Nullable(MD=False, MP=True, ME=True)
        )
        assert col.is_nullable_for_all_contexts() is False


class TestParseTableReference:
    """Test parse_table_reference on relationship and derivation models."""

    def test_foreign_key_bare_reference(self):
        fk = ForeignKey(
            column="member_id", references_table="member_roster", references_column="id"
        )
        ref = fk.parse_table_reference()
        assert ref.pipeline is None
        assert ref.table == "member_roster"
        assert ref.is_external() is False

    def test_foreign_key_qualified_reference(self):
        fk = ForeignKey(
            column="icd_code",
            references_table="reference_data.icd_codes",
            references_column="code",
        )
        ref = fk.parse_table_reference()
        assert ref.pipeline == "reference_data"
        assert ref.table == "icd_codes"
        assert ref.is_external() is True

    def test_outgoing_relationship_reference(self):
        from tablespec.models.umf import OutgoingRelationship

        rel = OutgoingRelationship(
            target_table="other_pipeline.target",
            source_column="a",
            target_column="b",
            type="foreign_to_primary",
            confidence=0.9,
        )
        ref = rel.parse_table_reference()
        assert ref.pipeline == "other_pipeline"
        assert ref.table == "target"

    def test_incoming_relationship_reference(self):
        from tablespec.models.umf import IncomingRelationship

        rel = IncomingRelationship(
            source_table="src_table",
            source_column="a",
            target_column="b",
            type="foreign_to_foreign",
            confidence=0.9,
        )
        ref = rel.parse_table_reference()
        assert ref.pipeline is None
        assert ref.table == "src_table"

    def test_derivation_candidate_reference(self):
        cand = DerivationCandidate(table="pipe.tab", column="c", priority=1)
        ref = cand.parse_table_reference()
        assert (ref.pipeline, ref.table) == ("pipe", "tab")


class TestTableReference:
    """Test TableReference parsing and formatting."""

    def test_parse_bare(self):
        from tablespec.models.pipeline import TableReference

        ref = TableReference.parse("outreach_list")
        assert ref.pipeline is None
        assert ref.table == "outreach_list"
        assert str(ref) == "outreach_list"

    def test_parse_qualified(self):
        from tablespec.models.pipeline import TableReference

        ref = TableReference.parse("reference_data.icd_codes")
        assert ref.pipeline == "reference_data"
        assert ref.table == "icd_codes"
        assert str(ref) == "reference_data.icd_codes"

    def test_to_qualified_name_resolves_bare_with_current_pipeline(self):
        from tablespec.models.pipeline import TableReference

        ref = TableReference.parse("outreach_list")
        assert ref.to_qualified_name("my_pipeline") == "my_pipeline.outreach_list"
        assert ref.to_qualified_name() == "outreach_list"

    def test_qualified_ignores_current_pipeline(self):
        from tablespec.models.pipeline import TableReference

        ref = TableReference.parse("other.t")
        assert ref.to_qualified_name("my_pipeline") == "other.t"

    def test_splits_on_first_dot_only(self):
        from tablespec.models.pipeline import TableReference

        ref = TableReference.parse("a.b.c")
        assert ref.pipeline == "a"
        assert ref.table == "b.c"


class TestRelationshipJoinExtensions:
    """Test join_filter and alternative_joins fields."""

    def test_foreign_key_join_filter(self):
        fk = ForeignKey(
            column="member_id",
            references_table="enterprise",
            references_column="member_id",
            join_filter="clientid = 2",
        )
        assert fk.join_filter == "clientid = 2"

    def test_alternative_joins(self):
        from tablespec.models.umf import OutgoingRelationship

        rel = OutgoingRelationship(
            target_table="t",
            source_column="a",
            target_column="b",
            type="foreign_to_primary",
            confidence=1.0,
            alternative_joins=[{"source_column": "c", "target_column": "d"}],
        )
        assert rel.alternative_joins == [{"source_column": "c", "target_column": "d"}]


class TestDerivationCandidateUnionValue:
    """Test union_value literal on derivation candidates."""

    def test_union_value_literal(self):
        cand = DerivationCandidate(
            table="crosswalk", column="c", priority=1, union_value=True
        )
        assert cand.union_value is True

    def test_union_value_defaults_none(self):
        cand = DerivationCandidate(table="t", column="c", priority=1)
        assert cand.union_value is None


class TestUMFMetadataSqlGenerationFields:
    """Test SQL-generation control fields on UMFMetadata."""

    def test_base_and_final_filters(self):
        from tablespec.models.umf import UMFMetadata

        meta = UMFMetadata(
            base_table="charge_file",
            base_table_filter="assess_type IN ('QUA','RA')",
            base_join_column="mrn",
            final_filter="disposition_id IS NOT NULL",
        )
        assert meta.base_table_filter == "assess_type IN ('QUA','RA')"
        assert meta.base_join_column == "mrn"
        assert meta.final_filter == "disposition_id IS NOT NULL"

    def test_union_base_tables_config(self):
        from tablespec.models.umf import UMFMetadata

        meta = UMFMetadata(
            union_base_tables=["crosswalk_outreach_list"],
            union_type="union_all",
            union_exclude_base=True,
            union_coalesce_base=True,
        )
        assert meta.union_base_tables == ["crosswalk_outreach_list"]
        assert meta.union_type == "union_all"
        assert meta.union_exclude_base is True
        assert meta.union_coalesce_base is True

    def test_union_defaults(self):
        from tablespec.models.umf import UMFMetadata

        meta = UMFMetadata()
        assert meta.union_base_tables is None
        assert meta.union_type is None
        assert meta.union_exclude_base is False
        assert meta.union_coalesce_base is False
        assert meta.final_dedup is None

    def test_final_dedup_distinct(self):
        from tablespec.models.umf import UMFMetadata

        meta = UMFMetadata(final_dedup="distinct")
        assert meta.final_dedup == "distinct"

    def test_invalid_union_type_rejected(self):
        from tablespec.models.umf import UMFMetadata

        with pytest.raises(ValidationError):
            UMFMetadata(union_type="cross_join")

    def test_base_table_strategy_values_round_trip(self):
        from tablespec.models.umf import UMFMetadata

        for strategy in ("union_sources", "unpivot", "union_branches"):
            meta = UMFMetadata(base_table_strategy=strategy)
            assert meta.base_table_strategy == strategy
        assert UMFMetadata().base_table_strategy is None

    def test_invalid_base_table_strategy_rejected(self):
        from tablespec.models.umf import UMFMetadata

        with pytest.raises(ValidationError):
            UMFMetadata(base_table_strategy="member_universe")


class TestIngestionUpdateMode:
    """Test IngestionConfig.update_mode."""

    def test_update_mode_defaults_to_upsert(self):
        from tablespec.models.umf import IngestionConfig

        assert IngestionConfig().update_mode == "upsert"

    def test_update_only(self):
        from tablespec.models.umf import IngestionConfig

        assert IngestionConfig(update_mode="update_only").update_mode == "update_only"

    def test_invalid_update_mode_rejected(self):
        from tablespec.models.umf import IngestionConfig

        with pytest.raises(ValidationError):
            IngestionConfig(update_mode="insert_only")


class TestEffectivePrimaryKey:
    """Test UMF.effective_primary_key default merge key."""

    def test_explicit_primary_key(self):
        umf = UMF(
            version="1.0",
            table_name="t",
            columns=[UMFColumn(name="id", data_type="INTEGER")],
            primary_key=["id"],
        )
        assert umf.effective_primary_key == ["id"]

    def test_defaults_to_meta_checksum(self):
        from tablespec.models.umf import DEFAULT_PRIMARY_KEY

        umf = UMF(
            version="1.0",
            table_name="t",
            columns=[UMFColumn(name="id", data_type="INTEGER")],
        )
        assert umf.effective_primary_key == DEFAULT_PRIMARY_KEY
        assert umf.effective_primary_key == ["meta_checksum"]


class TestValidationRulesMisclassificationWarning:
    """Test ValidationRules warns on ingested-stage expectations."""

    def test_warns_on_ingested_stage_expectation(self):
        from tablespec.models.umf import ValidationRules

        with pytest.warns(UserWarning, match="ingested-stage expectations"):
            ValidationRules(
                expectations=[{"type": "expect_column_values_to_be_between"}]
            )

    def test_no_warning_for_raw_expectations(self):
        import warnings as _warnings

        from tablespec.models.umf import ValidationRules

        with _warnings.catch_warnings():
            _warnings.simplefilter("error", UserWarning)
            ValidationRules(
                expectations=[{"type": "expect_column_values_to_match_regex"}]
            )

    def test_no_warning_when_expectations_absent(self):
        import warnings as _warnings

        from tablespec.models.umf import ValidationRules

        with _warnings.catch_warnings():
            _warnings.simplefilter("error", UserWarning)
            ValidationRules(table_level=None, column_level=None)


class TestReportSheet:
    """Test UMFColumn.report_sheet workbook tab assignment."""

    def test_report_sheet_defaults_to_none(self):
        col = UMFColumn(name="test_col", data_type="VARCHAR")
        assert col.report_sheet is None

    def test_report_sheet_accepts_valid_name(self):
        col = UMFColumn(name="test_col", data_type="VARCHAR", report_sheet="Summary")
        assert col.report_sheet == "Summary"

    def test_report_sheet_rejects_out_of_range_lengths(self):
        with pytest.raises(ValidationError):
            UMFColumn(name="test_col", data_type="VARCHAR", report_sheet="")
        with pytest.raises(ValidationError):
            UMFColumn(name="test_col", data_type="VARCHAR", report_sheet="x" * 32)
