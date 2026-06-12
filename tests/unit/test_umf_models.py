"""Unit tests for UMF Pydantic models."""

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
        candidate = DerivationCandidate(table="outreach_list", column="birth_date", priority=1)
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
            strategy="highest_priority", explanation="Use value from highest priority source"
        )
        assert survivorship.strategy == "highest_priority"
        assert survivorship.explanation == "Use value from highest priority source"

    def test_allows_none_description(self):
        """Test explanation is required."""
        survivorship = Survivorship(strategy="most_recent", explanation="Use most recent value")
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
                    DerivationCandidate(table="outreach_list", column="birth_date", priority=1),
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
            UMFColumn(name="test", data_type="VARCHAR", provenance_policy="invalid_policy")

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

        with pytest.warns(DeprecationWarning, match="UMF.validation_rules is deprecated"):
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
