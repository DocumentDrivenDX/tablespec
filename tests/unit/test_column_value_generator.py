"""Unit tests for column_value_generator module."""

import pytest

from tablespec.sample_data.column_value_generator import ColumnValueGenerator
from tablespec.sample_data.config import GenerationConfig

pytestmark = pytest.mark.fast


class TestColumnValueGeneratorInstantiation:
    """Test that ColumnValueGenerator can be instantiated with mocked dependencies."""

    @pytest.fixture
    def mock_dependencies(self, mocker):
        """Create mocked dependencies for ColumnValueGenerator."""
        from tablespec import GXConstraintExtractor
        from tablespec.inference.domain_types import DomainTypeRegistry
        from tablespec.sample_data.constraint_handlers import ConstraintHandlers
        from tablespec.sample_data.generators import HealthcareDataGenerators
        from tablespec.sample_data.registry import KeyRegistry

        # Mock GXConstraintExtractor
        gx_extractor = mocker.Mock(spec=GXConstraintExtractor)
        gx_extractor.is_column_not_null.return_value = False
        gx_extractor.get_max_length_for_column.return_value = None
        gx_extractor.get_strftime_format_for_column.return_value = None
        gx_extractor.get_constraints_for_column.return_value = None
        gx_extractor.get_regex_for_column.return_value = None

        # Mock DomainTypeRegistry
        domain_type_registry = mocker.Mock(spec=DomainTypeRegistry)
        domain_type_registry.get_sample_generator_method.return_value = None

        # Create real GenerationConfig
        config = GenerationConfig()

        # Create real KeyRegistry (needs config)
        key_registry = KeyRegistry(config=config)

        # Create real HealthcareDataGenerators (needs config and key_registry)
        generators = HealthcareDataGenerators(config=config, key_registry=key_registry)

        # Create real ConstraintHandlers (lightweight)
        constraint_handlers = ConstraintHandlers()

        # Debug tracking set
        debug_logged_columns = set()

        return {
            "gx_extractor": gx_extractor,
            "domain_type_registry": domain_type_registry,
            "generators": generators,
            "key_registry": key_registry,
            "constraint_handlers": constraint_handlers,
            "config": config,
            "debug_logged_columns": debug_logged_columns,
        }

    def test_can_instantiate_generator(self, mock_dependencies):
        """Test that ColumnValueGenerator can be instantiated."""
        generator = ColumnValueGenerator(**mock_dependencies)
        assert generator is not None
        assert generator.gx_extractor is not None
        assert generator.domain_type_registry is not None
        assert generator.generators is not None
        assert generator.key_registry is not None
        assert generator.constraint_handlers is not None
        assert generator.config is not None

    def test_generator_has_required_methods(self, mock_dependencies):
        """Test that ColumnValueGenerator has the expected public methods."""
        generator = ColumnValueGenerator(**mock_dependencies)
        assert hasattr(generator, "generate_column_value")
        assert callable(generator.generate_column_value)

    def test_generate_simple_string_column(self, mock_dependencies):
        """Test generating a simple string column value."""
        generator = ColumnValueGenerator(**mock_dependencies)

        col = {"name": "test_col", "key_type": None, "source": "data"}
        col_type = "STRING"
        sample_values = []
        umf_data = {"validation_rules": {"expectations": []}}
        unique_value_trackers = {}
        record = {}
        column_equality_constraints = {}
        unique_within_record_constraints = []
        filename_column_values = {}
        gx_expectations_cache = {}

        value = generator.generate_column_value(
            table_name="test_table",
            col=col,
            col_type=col_type,
            sample_values=sample_values,
            umf_data=umf_data,
            unique_value_trackers=unique_value_trackers,
            record=record,
            column_equality_constraints=column_equality_constraints,
            unique_within_record_constraints=unique_within_record_constraints,
            filename_column_values=filename_column_values,
            gx_expectations_cache=gx_expectations_cache,
            should_apply_equality_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=mock_dependencies[
                "constraint_handlers"
            ].ensure_distinct_from_columns,
        )

        # Should generate some value
        assert value is not None
        assert isinstance(value, str)

    def test_generate_integer_column(self, mock_dependencies):
        """Test generating an integer column value."""
        generator = ColumnValueGenerator(**mock_dependencies)

        col = {"name": "age", "key_type": None, "source": "data"}
        col_type = "INTEGER"
        sample_values = []
        umf_data = {"validation_rules": {"expectations": []}}

        value = generator.generate_column_value(
            table_name="test_table",
            col=col,
            col_type=col_type,
            sample_values=sample_values,
            umf_data=umf_data,
            unique_value_trackers={},
            record={},
            column_equality_constraints={},
            unique_within_record_constraints=[],
            filename_column_values={},
            gx_expectations_cache={},
            should_apply_equality_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=mock_dependencies[
                "constraint_handlers"
            ].ensure_distinct_from_columns,
        )

        assert value is not None
        assert isinstance(value, int)

    def test_generate_with_sample_values(self, mock_dependencies):
        """Test that sample_values are used when provided."""
        generator = ColumnValueGenerator(**mock_dependencies)

        col = {"name": "status", "key_type": None, "source": "data"}
        col_type = "STRING"
        sample_values = ["ACTIVE", "INACTIVE", "PENDING"]
        umf_data = {"validation_rules": {"expectations": []}}

        value = generator.generate_column_value(
            table_name="test_table",
            col=col,
            col_type=col_type,
            sample_values=sample_values,
            umf_data=umf_data,
            unique_value_trackers={},
            record={},
            column_equality_constraints={},
            unique_within_record_constraints=[],
            filename_column_values={},
            gx_expectations_cache={},
            should_apply_equality_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=mock_dependencies[
                "constraint_handlers"
            ].ensure_distinct_from_columns,
        )

        # Should be one of the sample values
        assert value in sample_values

    def test_generate_filename_sourced_column(self, mock_dependencies):
        """Test generating a column with source='filename'."""
        generator = ColumnValueGenerator(**mock_dependencies)

        col = {"name": "rundate", "key_type": None, "source": "filename"}
        col_type = "STRING"
        sample_values = []
        umf_data = {"validation_rules": {"expectations": []}}
        filename_column_values = {"rundate": "2024-10-15"}

        value = generator.generate_column_value(
            table_name="test_table",
            col=col,
            col_type=col_type,
            sample_values=sample_values,
            umf_data=umf_data,
            unique_value_trackers={},
            record={},
            column_equality_constraints={},
            unique_within_record_constraints=[],
            filename_column_values=filename_column_values,
            gx_expectations_cache={},
            should_apply_equality_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=mock_dependencies[
                "constraint_handlers"
            ].ensure_distinct_from_columns,
        )

        # Should use pre-selected filename value
        assert value == "2024-10-15"

    def test_generate_with_gx_constraints(self, mock_dependencies):
        """Test that generator can work with GX constraints (smoke test)."""
        generator = ColumnValueGenerator(**mock_dependencies)

        # Mock GX extractor to return constraints
        mock_dependencies["gx_extractor"].get_constraints_for_column.return_value = [
            "VALUE_A",
            "VALUE_B",
            "VALUE_C",
        ]

        col = {"name": "some_column", "key_type": None, "source": "data"}
        col_type = "STRING"
        sample_values = []
        umf_data = {"validation_rules": {"expectations": []}}
        gx_expectations_cache = {"test_table": {}}

        value = generator.generate_column_value(
            table_name="test_table",
            col=col,
            col_type=col_type,
            sample_values=sample_values,
            umf_data=umf_data,
            unique_value_trackers={},
            record={},
            column_equality_constraints={},
            unique_within_record_constraints=[],
            filename_column_values={},
            gx_expectations_cache=gx_expectations_cache,
            should_apply_equality_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=mock_dependencies[
                "constraint_handlers"
            ].ensure_distinct_from_columns,
        )

        # Should generate some value (GX constraints are available but may not be used due to priority cascade)
        assert value is not None
        assert isinstance(value, str)

    def test_generate_primary_key_enforces_uniqueness(self, mock_dependencies):
        """Test that primary key columns enforce uniqueness."""
        generator = ColumnValueGenerator(**mock_dependencies)

        col = {"name": "id", "key_type": "primary", "source": "data"}
        col_type = "STRING"
        sample_values = ["ID123"]
        umf_data = {"validation_rules": {"expectations": []}}
        unique_value_trackers = {"id": {"ID123"}}  # ID123 already used

        value = generator.generate_column_value(
            table_name="test_table",
            col=col,
            col_type=col_type,
            sample_values=sample_values,
            umf_data=umf_data,
            unique_value_trackers=unique_value_trackers,
            record={},
            column_equality_constraints={},
            unique_within_record_constraints=[],
            filename_column_values={},
            gx_expectations_cache={},
            should_apply_equality_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=mock_dependencies[
                "constraint_handlers"
            ].ensure_distinct_from_columns,
        )

        # Should generate unique value (not ID123)
        assert value != "ID123"
        assert value is not None

    def test_generate_with_column_equality_constraint(self, mock_dependencies):
        """Test column equality constraint (col_a must equal col_b)."""
        generator = ColumnValueGenerator(**mock_dependencies)

        # col_b already generated with value "MATCHING_VALUE"
        record = {"col_b": "MATCHING_VALUE"}

        col = {"name": "col_a", "key_type": None, "source": "data"}
        col_type = "STRING"
        sample_values = []
        umf_data = {"validation_rules": {"expectations": []}}
        column_equality_constraints = {"col_a": [{"column_B": "col_b", "ignore_row_if": "never"}]}

        value = generator.generate_column_value(
            table_name="test_table",
            col=col,
            col_type=col_type,
            sample_values=sample_values,
            umf_data=umf_data,
            unique_value_trackers={},
            record=record,
            column_equality_constraints=column_equality_constraints,
            unique_within_record_constraints=[],
            filename_column_values={},
            gx_expectations_cache={},
            should_apply_equality_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=mock_dependencies[
                "constraint_handlers"
            ].ensure_distinct_from_columns,
        )

        # Should match col_b value
        assert value == "MATCHING_VALUE"

    def test_generate_handles_not_null_constraint(self, mock_dependencies):
        """Test that not-null constraint prevents None values."""
        generator = ColumnValueGenerator(**mock_dependencies)

        # Mock GX to indicate not-null constraint
        mock_dependencies["gx_extractor"].is_column_not_null.return_value = True

        col = {"name": "required_col", "key_type": None, "source": "data"}
        col_type = "STRING"
        sample_values = []
        umf_data = {"validation_rules": {"expectations": []}}
        gx_expectations_cache = {"test_table": {}}

        value = generator.generate_column_value(
            table_name="test_table",
            col=col,
            col_type=col_type,
            sample_values=sample_values,
            umf_data=umf_data,
            unique_value_trackers={},
            record={},
            column_equality_constraints={},
            unique_within_record_constraints=[],
            filename_column_values={},
            gx_expectations_cache=gx_expectations_cache,
            should_apply_equality_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=mock_dependencies[
                "constraint_handlers"
            ].ensure_distinct_from_columns,
        )

        # Should not be None
        assert value is not None

    def test_generate_with_max_length_metadata(self, mock_dependencies):
        """Test that generator handles max_length metadata (smoke test)."""
        generator = ColumnValueGenerator(**mock_dependencies)

        # Mock GX to return max_length
        mock_dependencies["gx_extractor"].get_max_length_for_column.return_value = 5

        col = {"name": "short_col", "key_type": None, "source": "data"}
        col_type = "STRING"
        sample_values = []  # No sample values to avoid priority issues
        umf_data = {"validation_rules": {"expectations": []}}
        gx_expectations_cache = {"test_table": {}}

        value = generator.generate_column_value(
            table_name="test_table",
            col=col,
            col_type=col_type,
            sample_values=sample_values,
            umf_data=umf_data,
            unique_value_trackers={},
            record={},
            column_equality_constraints={},
            unique_within_record_constraints=[],
            filename_column_values={},
            gx_expectations_cache=gx_expectations_cache,
            should_apply_equality_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=mock_dependencies[
                "constraint_handlers"
            ].ensure_distinct_from_columns,
        )

        # Should generate a value (actual max_length enforcement is complex)
        assert value is not None
        assert isinstance(value, str)

    def test_generate_with_domain_type(self, mock_dependencies):
        """Test generation using domain_type."""
        generator = ColumnValueGenerator(**mock_dependencies)

        # Mock domain type registry to return generator method
        mock_dependencies[
            "domain_type_registry"
        ].get_sample_generator_method.return_value = "generate_email"

        col = {"name": "email", "key_type": None, "source": "data", "domain_type": "email"}
        col_type = "STRING"
        sample_values = []
        umf_data = {"validation_rules": {"expectations": []}}

        value = generator.generate_column_value(
            table_name="test_table",
            col=col,
            col_type=col_type,
            sample_values=sample_values,
            umf_data=umf_data,
            unique_value_trackers={},
            record={},
            column_equality_constraints={},
            unique_within_record_constraints=[],
            filename_column_values={},
            gx_expectations_cache={},
            should_apply_equality_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=mock_dependencies[
                "constraint_handlers"
            ].ensure_distinct_from_columns,
        )

        # Should generate email-like value
        assert value is not None
        assert "@" in value  # Email should contain @

    def test_generate_boolean_column(self, mock_dependencies):
        """Test generating boolean column value."""
        generator = ColumnValueGenerator(**mock_dependencies)

        col = {"name": "is_active", "key_type": None, "source": "data"}
        col_type = "BOOLEAN"
        sample_values = []
        umf_data = {"validation_rules": {"expectations": []}}

        value = generator.generate_column_value(
            table_name="test_table",
            col=col,
            col_type=col_type,
            sample_values=sample_values,
            umf_data=umf_data,
            unique_value_trackers={},
            record={},
            column_equality_constraints={},
            unique_within_record_constraints=[],
            filename_column_values={},
            gx_expectations_cache={},
            should_apply_equality_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=mock_dependencies[
                "constraint_handlers"
            ].ensure_distinct_from_columns,
        )

        # Should be True or False
        assert isinstance(value, bool)

    def test_generate_embedding_column(self, mock_dependencies):
        """Test generating embedding column value."""
        generator = ColumnValueGenerator(**mock_dependencies)

        col = {
            "name": "embedding",
            "key_type": None,
            "source": "data",
            "dimension": 8,
        }
        col_type = "EMBEDDING"
        sample_values = []
        umf_data = {"validation_rules": {"expectations": []}}

        value = generator.generate_column_value(
            table_name="test_table",
            col=col,
            col_type=col_type,
            sample_values=sample_values,
            umf_data=umf_data,
            unique_value_trackers={},
            record={},
            column_equality_constraints={},
            unique_within_record_constraints=[],
            filename_column_values={},
            gx_expectations_cache={},
            should_apply_equality_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=mock_dependencies[
                "constraint_handlers"
            ].ensure_distinct_from_columns,
        )

        assert isinstance(value, list)
        assert len(value) == 8
        assert all(isinstance(v, float) for v in value)
        assert value == generator.generate_column_value(
            table_name="test_table",
            col=col,
            col_type=col_type,
            sample_values=sample_values,
            umf_data=umf_data,
            unique_value_trackers={},
            record={},
            column_equality_constraints={},
            unique_within_record_constraints=[],
            filename_column_values={},
            gx_expectations_cache={},
            should_apply_equality_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=mock_dependencies[
                "constraint_handlers"
            ].ensure_distinct_from_columns,
        )

    def test_generate_decimal_column(self, mock_dependencies):
        """Test generating decimal column value."""
        generator = ColumnValueGenerator(**mock_dependencies)

        col = {"name": "amount", "key_type": None, "source": "data"}
        col_type = "DECIMAL(10,2)"
        sample_values = []
        umf_data = {"validation_rules": {"expectations": []}}

        value = generator.generate_column_value(
            table_name="test_table",
            col=col,
            col_type=col_type,
            sample_values=sample_values,
            umf_data=umf_data,
            unique_value_trackers={},
            record={},
            column_equality_constraints={},
            unique_within_record_constraints=[],
            filename_column_values={},
            gx_expectations_cache={},
            should_apply_equality_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=mock_dependencies[
                "constraint_handlers"
            ].should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=mock_dependencies[
                "constraint_handlers"
            ].ensure_distinct_from_columns,
        )

        # Should be a float
        assert isinstance(value, float)


class TestGenerateByType:
    """Test _generate_by_type paths via generate_column_value for various type names."""

    @pytest.fixture
    def mock_deps(self, mocker):
        from tablespec import GXConstraintExtractor
        from tablespec.inference.domain_types import DomainTypeRegistry
        from tablespec.sample_data.constraint_handlers import ConstraintHandlers
        from tablespec.sample_data.generators import HealthcareDataGenerators
        from tablespec.sample_data.registry import KeyRegistry

        gx_extractor = mocker.Mock(spec=GXConstraintExtractor)
        gx_extractor.is_column_not_null.return_value = False
        gx_extractor.get_max_length_for_column.return_value = None
        gx_extractor.get_strftime_format_for_column.return_value = None
        gx_extractor.get_constraints_for_column.return_value = None
        gx_extractor.get_regex_for_column.return_value = None

        domain_type_registry = mocker.Mock(spec=DomainTypeRegistry)
        domain_type_registry.get_sample_generator_method.return_value = None

        config = GenerationConfig()
        key_registry = KeyRegistry(config=config)
        generators = HealthcareDataGenerators(config=config, key_registry=key_registry)
        constraint_handlers = ConstraintHandlers()

        return {
            "gx_extractor": gx_extractor,
            "domain_type_registry": domain_type_registry,
            "generators": generators,
            "key_registry": key_registry,
            "constraint_handlers": constraint_handlers,
            "config": config,
            "debug_logged_columns": set(),
        }

    def _generate(self, mock_deps, col, col_type, **kwargs):
        generator = ColumnValueGenerator(**mock_deps)
        defaults = dict(
            table_name="test_table",
            col=col,
            col_type=col_type,
            sample_values=[],
            umf_data={"validation_rules": {"expectations": []}},
            unique_value_trackers={},
            record={},
            column_equality_constraints={},
            unique_within_record_constraints=[],
            filename_column_values={},
            gx_expectations_cache={},
            should_apply_equality_constraint_fn=mock_deps[
                "constraint_handlers"
            ].should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=mock_deps[
                "constraint_handlers"
            ].should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=mock_deps[
                "constraint_handlers"
            ].ensure_distinct_from_columns,
        )
        defaults.update(kwargs)
        return generator.generate_column_value(**defaults)

    def test_generate_double_type(self, mock_deps):
        col = {"name": "weight", "key_type": None, "source": "data"}
        value = self._generate(mock_deps, col, "DOUBLE")
        assert isinstance(value, float)

    def test_generate_float_type(self, mock_deps):
        col = {"name": "score", "key_type": None, "source": "data"}
        value = self._generate(mock_deps, col, "FLOAT")
        assert isinstance(value, float)

    def test_generate_date_type(self, mock_deps):
        col = {"name": "event_date", "key_type": None, "source": "data"}
        value = self._generate(mock_deps, col, "DATE")
        assert value is not None
        assert isinstance(value, str)

    def test_generate_timestamp_type(self, mock_deps):
        col = {"name": "created_at", "key_type": None, "source": "data"}
        value = self._generate(mock_deps, col, "TIMESTAMP")
        assert value is not None
        assert isinstance(value, str)

    def test_generate_long_type(self, mock_deps):
        col = {"name": "big_number", "key_type": None, "source": "data"}
        value = self._generate(mock_deps, col, "LONG")
        assert isinstance(value, int)

    def test_generate_status_column_name(self, mock_deps):
        """Columns ending in 'status' get status-like values."""
        col = {"name": "claim_status", "key_type": None, "source": "data"}
        value = self._generate(mock_deps, col, "STRING")
        assert value in ["ACTIVE", "INACTIVE", "PENDING", "COMPLETED", "CANCELLED", "SUSPENDED"]

    def test_generate_type_column_name(self, mock_deps):
        """Columns ending in 'type' get type-like values."""
        col = {"name": "member_type", "key_type": None, "source": "data"}
        value = self._generate(mock_deps, col, "STRING")
        assert value in ["TYPE_A", "TYPE_B", "TYPE_C", "DEFAULT", "STANDARD", "CUSTOM"]

    def test_generate_code_column_name(self, mock_deps):
        """Columns ending in 'code' get code-like values."""
        col = {"name": "billing_code", "key_type": None, "source": "data"}
        value = self._generate(mock_deps, col, "STRING")
        assert isinstance(value, str)
        assert len(value) == 4  # One letter + 3 digits

    def test_generate_flag_column_name(self, mock_deps):
        """Columns with 'flag' get flag-like values."""
        col = {"name": "active_flag", "key_type": None, "source": "data"}
        value = self._generate(mock_deps, col, "STRING")
        assert value in ["Y", "N", "YES", "NO", "1", "0", "TRUE", "FALSE"]

    def test_generate_reason_column_name(self, mock_deps):
        """Columns with 'reason' get reason-like values."""
        col = {"name": "denial_reason", "key_type": None, "source": "data"}
        value = self._generate(mock_deps, col, "STRING")
        assert value in ["MEDICAL", "ADMINISTRATIVE", "CLINICAL", "OPERATIONAL", "OTHER", "NOT_SPECIFIED"]

    def test_generate_category_column_name(self, mock_deps):
        col = {"name": "claim_category", "key_type": None, "source": "data"}
        value = self._generate(mock_deps, col, "STRING")
        assert value in ["CATEGORY_1", "CATEGORY_2", "CATEGORY_3", "PRIMARY", "SECONDARY", "TERTIARY"]

    def test_generate_result_column_name(self, mock_deps):
        col = {"name": "test_result", "key_type": None, "source": "data"}
        value = self._generate(mock_deps, col, "STRING")
        assert value in ["POSITIVE", "NEGATIVE", "NORMAL", "ABNORMAL", "PENDING", "INCONCLUSIVE"]

    def test_generate_description_column_name(self, mock_deps):
        col = {"name": "description", "key_type": None, "source": "data"}
        value = self._generate(mock_deps, col, "STRING")
        assert isinstance(value, str)
        assert value.startswith("Description for item")

    def test_generate_id_column_name(self, mock_deps):
        col = {"name": "claim_id", "key_type": None, "source": "data"}
        value = self._generate(mock_deps, col, "STRING")
        assert isinstance(value, str)
        assert value.startswith("ID")

    def test_generate_name_column(self, mock_deps):
        col = {"name": "entity_name", "key_type": None, "source": "data"}
        value = self._generate(mock_deps, col, "STRING")
        assert isinstance(value, str)
        assert value.startswith("Entity_")

    def test_generate_fallback_val(self, mock_deps):
        """Columns with no pattern match get VAL_ prefix."""
        col = {"name": "misc_data", "key_type": None, "source": "data"}
        value = self._generate(mock_deps, col, "STRING")
        assert isinstance(value, str)
        assert value.startswith("VAL_")


class TestFilenameSourcedColumnFallbacks:
    """Test filename column fallback patterns."""

    @pytest.fixture
    def mock_deps(self, mocker):
        from tablespec import GXConstraintExtractor
        from tablespec.inference.domain_types import DomainTypeRegistry
        from tablespec.sample_data.constraint_handlers import ConstraintHandlers
        from tablespec.sample_data.generators import HealthcareDataGenerators
        from tablespec.sample_data.registry import KeyRegistry

        gx_extractor = mocker.Mock(spec=GXConstraintExtractor)
        gx_extractor.is_column_not_null.return_value = False
        gx_extractor.get_max_length_for_column.return_value = None
        gx_extractor.get_strftime_format_for_column.return_value = None
        gx_extractor.get_constraints_for_column.return_value = None
        gx_extractor.get_regex_for_column.return_value = None

        domain_type_registry = mocker.Mock(spec=DomainTypeRegistry)
        domain_type_registry.get_sample_generator_method.return_value = None

        config = GenerationConfig()
        key_registry = KeyRegistry(config=config)
        generators = HealthcareDataGenerators(config=config, key_registry=key_registry)
        constraint_handlers = ConstraintHandlers()

        return {
            "gx_extractor": gx_extractor,
            "domain_type_registry": domain_type_registry,
            "generators": generators,
            "key_registry": key_registry,
            "constraint_handlers": constraint_handlers,
            "config": config,
            "debug_logged_columns": set(),
        }

    def _generate(self, mock_deps, col_name, source="filename"):
        generator = ColumnValueGenerator(**mock_deps)
        col = {"name": col_name, "key_type": None, "source": source}
        return generator.generate_column_value(
            table_name="test_table",
            col=col,
            col_type="STRING",
            sample_values=[],
            umf_data={"validation_rules": {"expectations": []}},
            unique_value_trackers={},
            record={},
            column_equality_constraints={},
            unique_within_record_constraints=[],
            filename_column_values={},
            gx_expectations_cache={},
            should_apply_equality_constraint_fn=mock_deps[
                "constraint_handlers"
            ].should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=mock_deps[
                "constraint_handlers"
            ].should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=mock_deps[
                "constraint_handlers"
            ].ensure_distinct_from_columns,
        )

    def test_filename_rundate(self, mock_deps):
        assert self._generate(mock_deps, "rundate") == "2024-10-15"

    def test_filename_run_date(self, mock_deps):
        assert self._generate(mock_deps, "run_date") == "2024-10-15"

    def test_filename_state(self, mock_deps):
        assert self._generate(mock_deps, "state") == "IL"

    def test_filename_program(self, mock_deps):
        assert self._generate(mock_deps, "program") == "MEDICAID"

    def test_filename_lob(self, mock_deps):
        assert self._generate(mock_deps, "lob") == "MEDICAID"

    def test_filename_date_mmddyyyy(self, mock_deps):
        assert self._generate(mock_deps, "mmddyyyy_date") == "10152024"

    def test_filename_date_yyyymmdd(self, mock_deps):
        assert self._generate(mock_deps, "yyyymmdd_date") == "20241015"

    def test_filename_date_ddmmyyyy(self, mock_deps):
        assert self._generate(mock_deps, "ddmmyyyy_date") == "15102024"

    def test_filename_date_generic(self, mock_deps):
        assert self._generate(mock_deps, "file_date") == "20241015"

    def test_filename_time(self, mock_deps):
        assert self._generate(mock_deps, "file_time") == "1234"

    def test_filename_project(self, mock_deps):
        assert self._generate(mock_deps, "project_id") in ["1001", "1002", "2024", "2025"]

    def test_filename_claim(self, mock_deps):
        assert self._generate(mock_deps, "claim_file") in ["Claims_File", "Data_File", "Source_File"]

    def test_filename_generic_fallback(self, mock_deps):
        assert self._generate(mock_deps, "unknown_xyz_col") == "GENERIC_FILE"


class TestNotNullFallback:
    """Test not-null fallback generation for various types."""

    @pytest.fixture
    def mock_deps(self, mocker):
        from tablespec import GXConstraintExtractor
        from tablespec.inference.domain_types import DomainTypeRegistry
        from tablespec.sample_data.constraint_handlers import ConstraintHandlers
        from tablespec.sample_data.generators import HealthcareDataGenerators
        from tablespec.sample_data.registry import KeyRegistry

        gx_extractor = mocker.Mock(spec=GXConstraintExtractor)
        gx_extractor.is_column_not_null.return_value = True
        gx_extractor.get_max_length_for_column.return_value = None
        gx_extractor.get_strftime_format_for_column.return_value = None
        gx_extractor.get_constraints_for_column.return_value = None
        gx_extractor.get_regex_for_column.return_value = None

        domain_type_registry = mocker.Mock(spec=DomainTypeRegistry)
        domain_type_registry.get_sample_generator_method.return_value = None

        config = GenerationConfig()
        key_registry = KeyRegistry(config=config)
        generators = HealthcareDataGenerators(config=config, key_registry=key_registry)
        constraint_handlers = ConstraintHandlers()

        return {
            "gx_extractor": gx_extractor,
            "domain_type_registry": domain_type_registry,
            "generators": generators,
            "key_registry": key_registry,
            "constraint_handlers": constraint_handlers,
            "config": config,
            "debug_logged_columns": set(),
        }

    def _generate(self, mock_deps, col_name, col_type):
        generator = ColumnValueGenerator(**mock_deps)
        col = {"name": col_name, "key_type": None, "source": "data"}
        return generator.generate_column_value(
            table_name="test_table",
            col=col,
            col_type=col_type,
            sample_values=[],
            umf_data={"validation_rules": {"expectations": []}},
            unique_value_trackers={},
            record={},
            column_equality_constraints={},
            unique_within_record_constraints=[],
            filename_column_values={},
            gx_expectations_cache={"test_table": {"name": "suite", "expectations": []}},
            should_apply_equality_constraint_fn=mock_deps[
                "constraint_handlers"
            ].should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=mock_deps[
                "constraint_handlers"
            ].should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=mock_deps[
                "constraint_handlers"
            ].ensure_distinct_from_columns,
        )

    def test_not_null_string_always_produces_value(self, mock_deps):
        value = self._generate(mock_deps, "misc_data", "STRING")
        assert value is not None

    def test_not_null_integer_always_produces_value(self, mock_deps):
        value = self._generate(mock_deps, "count_val", "INTEGER")
        assert value is not None
        assert isinstance(value, int)

    def test_not_null_boolean_always_produces_value(self, mock_deps):
        value = self._generate(mock_deps, "is_active", "BOOLEAN")
        assert value is not None
        assert isinstance(value, bool)


class TestMaxLengthTrimming:
    """Test that max_length trims generated values."""

    @pytest.fixture
    def mock_deps(self, mocker):
        from tablespec import GXConstraintExtractor
        from tablespec.inference.domain_types import DomainTypeRegistry
        from tablespec.sample_data.constraint_handlers import ConstraintHandlers
        from tablespec.sample_data.generators import HealthcareDataGenerators
        from tablespec.sample_data.registry import KeyRegistry

        gx_extractor = mocker.Mock(spec=GXConstraintExtractor)
        gx_extractor.is_column_not_null.return_value = False
        gx_extractor.get_max_length_for_column.return_value = 3
        gx_extractor.get_strftime_format_for_column.return_value = None
        gx_extractor.get_constraints_for_column.return_value = None
        gx_extractor.get_regex_for_column.return_value = None

        domain_type_registry = mocker.Mock(spec=DomainTypeRegistry)
        domain_type_registry.get_sample_generator_method.return_value = None

        config = GenerationConfig()
        key_registry = KeyRegistry(config=config)
        generators = HealthcareDataGenerators(config=config, key_registry=key_registry)
        constraint_handlers = ConstraintHandlers()

        return {
            "gx_extractor": gx_extractor,
            "domain_type_registry": domain_type_registry,
            "generators": generators,
            "key_registry": key_registry,
            "constraint_handlers": constraint_handlers,
            "config": config,
            "debug_logged_columns": set(),
        }

    def test_max_length_trims_string(self, mock_deps):
        generator = ColumnValueGenerator(**mock_deps)
        col = {"name": "short_col", "key_type": None, "source": "data"}
        value = generator.generate_column_value(
            table_name="test_table",
            col=col,
            col_type="STRING",
            sample_values=["ABCDEF"],
            umf_data={"validation_rules": {"expectations": []}},
            unique_value_trackers={},
            record={},
            column_equality_constraints={},
            unique_within_record_constraints=[],
            filename_column_values={},
            gx_expectations_cache={"test_table": {"name": "suite", "expectations": []}},
            should_apply_equality_constraint_fn=mock_deps[
                "constraint_handlers"
            ].should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=mock_deps[
                "constraint_handlers"
            ].should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=mock_deps[
                "constraint_handlers"
            ].ensure_distinct_from_columns,
        )
        assert isinstance(value, str)
        assert len(value) <= 3


class TestDomainSpecificPatterns:
    """Test domain-specific pattern generation (email, NPI, ZIP, etc.)."""

    @pytest.fixture
    def mock_deps(self, mocker):
        from tablespec import GXConstraintExtractor
        from tablespec.inference.domain_types import DomainTypeRegistry
        from tablespec.sample_data.constraint_handlers import ConstraintHandlers
        from tablespec.sample_data.generators import HealthcareDataGenerators
        from tablespec.sample_data.registry import KeyRegistry

        gx_extractor = mocker.Mock(spec=GXConstraintExtractor)
        gx_extractor.is_column_not_null.return_value = False
        gx_extractor.get_max_length_for_column.return_value = None
        gx_extractor.get_strftime_format_for_column.return_value = None
        gx_extractor.get_constraints_for_column.return_value = None
        gx_extractor.get_regex_for_column.return_value = None

        domain_type_registry = mocker.Mock(spec=DomainTypeRegistry)
        domain_type_registry.get_sample_generator_method.return_value = None

        config = GenerationConfig()
        key_registry = KeyRegistry(config=config)
        generators = HealthcareDataGenerators(config=config, key_registry=key_registry)
        constraint_handlers = ConstraintHandlers()

        return {
            "gx_extractor": gx_extractor,
            "domain_type_registry": domain_type_registry,
            "generators": generators,
            "key_registry": key_registry,
            "constraint_handlers": constraint_handlers,
            "config": config,
            "debug_logged_columns": set(),
        }

    def _generate(self, mock_deps, col_name, col_type="STRING"):
        generator = ColumnValueGenerator(**mock_deps)
        col = {"name": col_name, "key_type": None, "source": "data"}
        return generator.generate_column_value(
            table_name="test_table",
            col=col,
            col_type=col_type,
            sample_values=[],
            umf_data={"validation_rules": {"expectations": []}},
            unique_value_trackers={},
            record={},
            column_equality_constraints={},
            unique_within_record_constraints=[],
            filename_column_values={},
            gx_expectations_cache={},
            should_apply_equality_constraint_fn=mock_deps[
                "constraint_handlers"
            ].should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=mock_deps[
                "constraint_handlers"
            ].should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=mock_deps[
                "constraint_handlers"
            ].ensure_distinct_from_columns,
        )

    def test_email_pattern(self, mock_deps):
        value = self._generate(mock_deps, "email_address")
        assert "@" in value

    def test_npi_pattern(self, mock_deps):
        value = self._generate(mock_deps, "provider_npi")
        assert value is not None

    def test_zip_pattern(self, mock_deps):
        value = self._generate(mock_deps, "member_zip")
        assert value is not None

    def test_govtid_pattern(self, mock_deps):
        value = self._generate(mock_deps, "govtid")
        assert value is not None

    def test_service_type_pattern(self, mock_deps):
        value = self._generate(mock_deps, "service_type")
        assert value is not None

    def test_gender_pattern(self, mock_deps):
        value = self._generate(mock_deps, "gender")
        assert value is not None

    def test_state_pattern(self, mock_deps):
        value = self._generate(mock_deps, "source_state")
        assert value is not None

    def test_phone_pattern(self, mock_deps):
        value = self._generate(mock_deps, "home_phone")
        assert "-" in value

    def test_firstname_pattern(self, mock_deps):
        value = self._generate(mock_deps, "first_name")
        assert isinstance(value, str)

    def test_lastname_pattern(self, mock_deps):
        value = self._generate(mock_deps, "last_name")
        assert isinstance(value, str)

    def test_city_pattern(self, mock_deps):
        value = self._generate(mock_deps, "member_city")
        assert isinstance(value, str)

    def test_addr1_pattern(self, mock_deps):
        value = self._generate(mock_deps, "mbraddr1_1")
        assert isinstance(value, str)

    def test_addr2_pattern(self, mock_deps):
        value = self._generate(mock_deps, "mbraddr2_1")
        assert isinstance(value, str)

    def test_county_pattern(self, mock_deps):
        value = self._generate(mock_deps, "member_county")
        assert isinstance(value, str)

    def test_date_type_column(self, mock_deps):
        """Date type columns with date name patterns use date generators."""
        value = self._generate(mock_deps, "birth_date", col_type="DATE")
        assert value is not None
        assert isinstance(value, str)

    def test_vendor_pattern(self, mock_deps):
        value = self._generate(mock_deps, "vendor_name")
        assert isinstance(value, str)

    def test_plan_code_pattern(self, mock_deps):
        value = self._generate(mock_deps, "plan_code")
        assert isinstance(value, str)

    def test_procedure_code_pattern(self, mock_deps):
        value = self._generate(mock_deps, "procedurecode")
        assert isinstance(value, str)

    def test_diagnosis_code_pattern(self, mock_deps):
        value = self._generate(mock_deps, "diag_code")
        assert isinstance(value, str)


class TestSampleValuePatterns:
    """Test sample value pattern matching for single-value cases."""

    @pytest.fixture
    def mock_deps(self, mocker):
        from tablespec import GXConstraintExtractor
        from tablespec.inference.domain_types import DomainTypeRegistry
        from tablespec.sample_data.constraint_handlers import ConstraintHandlers
        from tablespec.sample_data.generators import HealthcareDataGenerators
        from tablespec.sample_data.registry import KeyRegistry

        gx_extractor = mocker.Mock(spec=GXConstraintExtractor)
        gx_extractor.is_column_not_null.return_value = False
        gx_extractor.get_max_length_for_column.return_value = None
        gx_extractor.get_strftime_format_for_column.return_value = None
        gx_extractor.get_constraints_for_column.return_value = None
        gx_extractor.get_regex_for_column.return_value = None

        domain_type_registry = mocker.Mock(spec=DomainTypeRegistry)
        domain_type_registry.get_sample_generator_method.return_value = None

        config = GenerationConfig()
        key_registry = KeyRegistry(config=config)
        generators = HealthcareDataGenerators(config=config, key_registry=key_registry)
        constraint_handlers = ConstraintHandlers()

        return {
            "gx_extractor": gx_extractor,
            "domain_type_registry": domain_type_registry,
            "generators": generators,
            "key_registry": key_registry,
            "constraint_handlers": constraint_handlers,
            "config": config,
            "debug_logged_columns": set(),
        }

    def _generate(self, mock_deps, col_name, sample_values):
        generator = ColumnValueGenerator(**mock_deps)
        col = {"name": col_name, "key_type": None, "source": "data"}
        return generator.generate_column_value(
            table_name="test_table",
            col=col,
            col_type="STRING",
            sample_values=sample_values,
            umf_data={"validation_rules": {"expectations": []}},
            unique_value_trackers={},
            record={},
            column_equality_constraints={},
            unique_within_record_constraints=[],
            filename_column_values={},
            gx_expectations_cache={},
            should_apply_equality_constraint_fn=mock_deps[
                "constraint_handlers"
            ].should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=mock_deps[
                "constraint_handlers"
            ].should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=mock_deps[
                "constraint_handlers"
            ].ensure_distinct_from_columns,
        )

    def test_single_alphanumeric_pattern(self, mock_deps):
        """Single alphanumeric value like 'H1234' generates similar pattern."""
        value = self._generate(mock_deps, "code_col", ["H1234"])
        assert isinstance(value, str)
        assert len(value) == 5

    def test_single_date_slash_pattern(self, mock_deps):
        """Single date value with slashes generates a date."""
        value = self._generate(mock_deps, "some_date", ["09/18/2024"])
        assert isinstance(value, str)
        assert "/" in value

    def test_single_date_dash_pattern(self, mock_deps):
        """Single date value with dashes generates a date."""
        value = self._generate(mock_deps, "some_date", ["2023-11-14"])
        assert isinstance(value, str)
        assert "-" in value

    def test_single_constant_value(self, mock_deps):
        """Single constant value without pattern is returned as-is."""
        value = self._generate(mock_deps, "static_col", ["FIXED_VALUE"])
        assert value == "FIXED_VALUE"

    def test_filters_out_description_values(self, mock_deps):
        """Sample values containing 'sample', 'example', etc. are filtered."""
        value = self._generate(mock_deps, "col", ["sample value", "n/a", "REAL_VALUE"])
        assert value == "REAL_VALUE"


class TestForeignKeyRelationship:
    """Test foreign key relationship paths."""

    @pytest.fixture
    def mock_deps(self, mocker):
        from tablespec import GXConstraintExtractor
        from tablespec.inference.domain_types import DomainTypeRegistry
        from tablespec.sample_data.constraint_handlers import ConstraintHandlers
        from tablespec.sample_data.generators import HealthcareDataGenerators
        from tablespec.sample_data.registry import KeyRegistry

        gx_extractor = mocker.Mock(spec=GXConstraintExtractor)
        gx_extractor.is_column_not_null.return_value = False
        gx_extractor.get_max_length_for_column.return_value = None
        gx_extractor.get_strftime_format_for_column.return_value = None
        gx_extractor.get_constraints_for_column.return_value = None
        gx_extractor.get_regex_for_column.return_value = None

        domain_type_registry = mocker.Mock(spec=DomainTypeRegistry)
        domain_type_registry.get_sample_generator_method.return_value = None

        config = GenerationConfig()
        key_registry = KeyRegistry(config=config)
        generators = HealthcareDataGenerators(config=config, key_registry=key_registry)
        constraint_handlers = ConstraintHandlers()

        return {
            "gx_extractor": gx_extractor,
            "domain_type_registry": domain_type_registry,
            "generators": generators,
            "key_registry": key_registry,
            "constraint_handlers": constraint_handlers,
            "config": config,
            "debug_logged_columns": set(),
        }

    def test_foreign_key_type_uses_registered_pks(self, mock_deps):
        """Foreign key columns should use registered primary keys."""
        mock_deps["key_registry"].primary_keys["parent_table"] = ["PK1", "PK2", "PK3"]

        generator = ColumnValueGenerator(**mock_deps)
        col = {"name": "parent_id", "key_type": "foreign_one_to_many", "source": "data"}
        value = generator.generate_column_value(
            table_name="child_table",
            col=col,
            col_type="STRING",
            sample_values=[],
            umf_data={"validation_rules": {"expectations": []}},
            unique_value_trackers={},
            record={},
            column_equality_constraints={},
            unique_within_record_constraints=[],
            filename_column_values={},
            gx_expectations_cache={},
            should_apply_equality_constraint_fn=mock_deps[
                "constraint_handlers"
            ].should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=mock_deps[
                "constraint_handlers"
            ].should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=mock_deps[
                "constraint_handlers"
            ].ensure_distinct_from_columns,
        )
        assert value in ["PK1", "PK2", "PK3"]

    def test_unique_constraint_enforcement(self, mock_deps):
        """Values in unique constraints should be tracked and enforced unique."""
        generator = ColumnValueGenerator(**mock_deps)
        col = {"name": "uniq_col", "key_type": None, "source": "data"}
        unique_trackers = {}
        umf_data = {
            "validation_rules": {"expectations": []},
            "unique_constraints": [["uniq_col", "other_col"]],
        }

        values = set()
        for _ in range(5):
            value = generator.generate_column_value(
                table_name="test_table",
                col=col,
                col_type="STRING",
                sample_values=["SAME"],
                umf_data=umf_data,
                unique_value_trackers=unique_trackers,
                record={},
                column_equality_constraints={},
                unique_within_record_constraints=[],
                filename_column_values={},
                gx_expectations_cache={},
                should_apply_equality_constraint_fn=mock_deps[
                    "constraint_handlers"
                ].should_apply_equality_constraint,
                should_apply_unique_within_record_constraint_fn=mock_deps[
                    "constraint_handlers"
                ].should_apply_unique_within_record_constraint,
                ensure_distinct_from_columns_fn=mock_deps[
                    "constraint_handlers"
                ].ensure_distinct_from_columns,
            )
            values.add(value)
        # All 5 values should be unique
        assert len(values) == 5


class TestGXStrftimeFormat:
    """Test GX strftime date format path."""

    @pytest.fixture
    def mock_deps(self, mocker):
        from tablespec import GXConstraintExtractor
        from tablespec.inference.domain_types import DomainTypeRegistry
        from tablespec.sample_data.constraint_handlers import ConstraintHandlers
        from tablespec.sample_data.generators import HealthcareDataGenerators
        from tablespec.sample_data.registry import KeyRegistry

        gx_extractor = mocker.Mock(spec=GXConstraintExtractor)
        gx_extractor.is_column_not_null.return_value = False
        gx_extractor.get_max_length_for_column.return_value = None
        gx_extractor.get_strftime_format_for_column.return_value = "%Y-%m-%d"
        gx_extractor.get_constraints_for_column.return_value = None
        gx_extractor.get_regex_for_column.return_value = None

        domain_type_registry = mocker.Mock(spec=DomainTypeRegistry)
        domain_type_registry.get_sample_generator_method.return_value = None

        config = GenerationConfig()
        key_registry = KeyRegistry(config=config)
        generators = HealthcareDataGenerators(config=config, key_registry=key_registry)
        constraint_handlers = ConstraintHandlers()

        return {
            "gx_extractor": gx_extractor,
            "domain_type_registry": domain_type_registry,
            "generators": generators,
            "key_registry": key_registry,
            "constraint_handlers": constraint_handlers,
            "config": config,
            "debug_logged_columns": set(),
        }

    def test_gx_strftime_date_format(self, mock_deps):
        generator = ColumnValueGenerator(**mock_deps)
        col = {"name": "event_date", "key_type": None, "source": "data"}
        value = generator.generate_column_value(
            table_name="test_table",
            col=col,
            col_type="STRING",
            sample_values=[],
            umf_data={"validation_rules": {"expectations": []}},
            unique_value_trackers={},
            record={},
            column_equality_constraints={},
            unique_within_record_constraints=[],
            filename_column_values={},
            gx_expectations_cache={"test_table": {"name": "suite", "expectations": []}},
            should_apply_equality_constraint_fn=mock_deps[
                "constraint_handlers"
            ].should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=mock_deps[
                "constraint_handlers"
            ].should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=mock_deps[
                "constraint_handlers"
            ].ensure_distinct_from_columns,
        )
        assert value is not None
        # Should match YYYY-MM-DD pattern
        parts = value.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4

    def test_gx_strftime_birth_date(self, mock_deps):
        generator = ColumnValueGenerator(**mock_deps)
        col = {"name": "dob", "key_type": None, "source": "data"}
        value = generator.generate_column_value(
            table_name="test_table",
            col=col,
            col_type="STRING",
            sample_values=[],
            umf_data={"validation_rules": {"expectations": []}},
            unique_value_trackers={},
            record={},
            column_equality_constraints={},
            unique_within_record_constraints=[],
            filename_column_values={},
            gx_expectations_cache={"test_table": {"name": "suite", "expectations": []}},
            should_apply_equality_constraint_fn=mock_deps[
                "constraint_handlers"
            ].should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=mock_deps[
                "constraint_handlers"
            ].should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=mock_deps[
                "constraint_handlers"
            ].ensure_distinct_from_columns,
        )
        assert value is not None
        assert isinstance(value, str)


class TestDomainTypeWithDateFormat:
    """Test domain type generation with date_format parameter."""

    @pytest.fixture
    def mock_deps(self, mocker):
        from tablespec import GXConstraintExtractor
        from tablespec.inference.domain_types import DomainTypeRegistry
        from tablespec.sample_data.constraint_handlers import ConstraintHandlers
        from tablespec.sample_data.generators import HealthcareDataGenerators
        from tablespec.sample_data.registry import KeyRegistry

        gx_extractor = mocker.Mock(spec=GXConstraintExtractor)
        gx_extractor.is_column_not_null.return_value = False
        gx_extractor.get_max_length_for_column.return_value = None
        gx_extractor.get_strftime_format_for_column.return_value = None
        gx_extractor.get_constraints_for_column.return_value = None
        gx_extractor.get_regex_for_column.return_value = None

        domain_type_registry = mocker.Mock(spec=DomainTypeRegistry)
        domain_type_registry.get_sample_generator_method.return_value = "generate_date_in_range"

        config = GenerationConfig()
        key_registry = KeyRegistry(config=config)
        generators = HealthcareDataGenerators(config=config, key_registry=key_registry)
        constraint_handlers = ConstraintHandlers()

        return {
            "gx_extractor": gx_extractor,
            "domain_type_registry": domain_type_registry,
            "generators": generators,
            "key_registry": key_registry,
            "constraint_handlers": constraint_handlers,
            "config": config,
            "debug_logged_columns": set(),
        }

    def test_domain_type_with_date_format(self, mock_deps):
        generator = ColumnValueGenerator(**mock_deps)
        col = {
            "name": "service_date",
            "key_type": None,
            "source": "data",
            "domain_type": "service_date",
            "format": "YYYY-MM-DD",
        }
        value = generator.generate_column_value(
            table_name="test_table",
            col=col,
            col_type="STRING",
            sample_values=[],
            umf_data={"validation_rules": {"expectations": []}},
            unique_value_trackers={},
            record={},
            column_equality_constraints={},
            unique_within_record_constraints=[],
            filename_column_values={},
            gx_expectations_cache={},
            should_apply_equality_constraint_fn=mock_deps[
                "constraint_handlers"
            ].should_apply_equality_constraint,
            should_apply_unique_within_record_constraint_fn=mock_deps[
                "constraint_handlers"
            ].should_apply_unique_within_record_constraint,
            ensure_distinct_from_columns_fn=mock_deps[
                "constraint_handlers"
            ].ensure_distinct_from_columns,
        )
        assert value is not None
        assert isinstance(value, str)
