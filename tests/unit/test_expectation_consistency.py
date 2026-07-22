"""Test consistency between expectation schemas, categories, and parameters.

This test module ensures that:
1. All expectation types referenced in categories exist in the GX schema
2. All expectation types documented in parameters exist in the GX schema
3. No invalid expectation types are referenced anywhere
4. All categories are mutually exclusive (no duplicates)
5. All LLM-generatable types have parameter documentation
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


class TestExpectationConsistency:
    """Test consistency across expectation configuration files."""

    @pytest.fixture
    def schemas_dir(self) -> Path:
        """Path to schemas directory."""
        return Path(__file__).parent.parent.parent / "src" / "tablespec" / "schemas"

    @pytest.fixture
    def gx_schema(self, schemas_dir: Path) -> dict:
        """Load GX expectation suite schema."""
        schema_path = schemas_dir / "gx_expectation_suite.schema.json"
        with schema_path.open() as f:
            return json.load(f)

    @pytest.fixture
    def valid_expectation_types(self, gx_schema: dict) -> set[str]:
        """Extract set of valid expectation types from GX schema."""
        return set(
            gx_schema["properties"]["expectations"]["items"]["properties"]["type"][
                "enum"
            ]
        )

    @pytest.fixture
    def expectation_categories(self, schemas_dir: Path) -> dict:
        """Load expectation categories."""
        categories_path = schemas_dir / "expectation_categories.json"
        with categories_path.open() as f:
            return json.load(f)

    @pytest.fixture
    def expectation_parameters(self, schemas_dir: Path) -> dict:
        """Load expectation parameters."""
        parameters_path = schemas_dir / "expectation_parameters.json"
        with parameters_path.open() as f:
            return json.load(f)

    def test_all_categories_in_schema(
        self, expectation_categories: dict, valid_expectation_types: set[str]
    ):
        """Test that every expectation type in categories exists in GX schema."""
        invalid_types = []

        for category_name, category_data in expectation_categories.items():
            if isinstance(category_data, dict) and "expectations" in category_data:
                for exp_type in category_data["expectations"]:
                    if exp_type not in valid_expectation_types:
                        invalid_types.append(
                            {
                                "category": category_name,
                                "type": exp_type,
                                "file": "expectation_categories.json",
                            }
                        )

        if invalid_types:
            print("\n❌ Invalid expectation types found in categories:")
            for item in invalid_types:
                print(f"  Category '{item['category']}': {item['type']}")

        assert len(invalid_types) == 0, (
            f"Found {len(invalid_types)} invalid expectation types in categories (not in GX schema)"
        )

    def test_all_parameters_in_schema(
        self, expectation_parameters: dict, valid_expectation_types: set[str]
    ):
        """Test that every expectation type in parameters exists in GX schema."""
        invalid_types = []

        # Only check sections that contain expectation type definitions
        expectation_sections = [
            "table_level_expectations",
            "column_level_expectations",
            "pending_fallback",
        ]

        for param_category in expectation_sections:
            if param_category not in expectation_parameters:
                continue

            expectations = expectation_parameters[param_category]
            for exp_type in expectations:
                if exp_type not in valid_expectation_types:
                    invalid_types.append(
                        {
                            "parameter_category": param_category,
                            "type": exp_type,
                            "file": "expectation_parameters.json",
                        }
                    )

        if invalid_types:
            print("\n❌ Invalid expectation types found in parameters:")
            for item in invalid_types:
                print(f"  Category '{item['parameter_category']}': {item['type']}")

        assert len(invalid_types) == 0, (
            f"Found {len(invalid_types)} invalid expectation types in parameters (not in GX schema)"
        )

    def test_no_invalid_types_in_categories(self, expectation_categories: dict):
        """Test that known invalid expectation types are not in categories.

        This test explicitly checks for expectation types that are commonly
        confused or have been deprecated.
        """
        known_invalid_types = [
            "expect_multicolumn_values_to_be_unique",  # Should use expect_compound_columns_to_be_unique
        ]

        found_invalid = []

        for category_name, category_data in expectation_categories.items():
            if isinstance(category_data, dict) and "expectations" in category_data:
                for exp_type in category_data["expectations"]:
                    if exp_type in known_invalid_types:
                        found_invalid.append(
                            {"category": category_name, "type": exp_type}
                        )

        if found_invalid:
            print("\n❌ Known invalid expectation types found in categories:")
            for item in found_invalid:
                print(f"  Category '{item['category']}': {item['type']}")
            print(
                "\nNote: expect_multicolumn_values_to_be_unique should be "
                "expect_compound_columns_to_be_unique"
            )

        assert len(found_invalid) == 0, (
            f"Found {len(found_invalid)} known invalid expectation types in categories"
        )

    def test_llm_generatable_types_valid(self, valid_expectation_types: set[str]):
        """Test that all types from get_llm_generatable_expectations() are valid."""
        from tablespec.prompts.expectation_guide import get_llm_generatable_expectations

        invalid_types = []

        # Test table-level expectations
        table_expectations = get_llm_generatable_expectations(context="table")
        for exp_type in table_expectations:
            if exp_type not in valid_expectation_types:
                invalid_types.append({"context": "table", "type": exp_type})

        # Test column-level expectations
        column_expectations = get_llm_generatable_expectations(context="column")
        for exp_type in column_expectations:
            if exp_type not in valid_expectation_types:
                invalid_types.append({"context": "column", "type": exp_type})

        if invalid_types:
            print(
                "\n❌ Invalid expectation types from get_llm_generatable_expectations():"
            )
            for item in invalid_types:
                print(f"  Context '{item['context']}': {item['type']}")

        assert len(invalid_types) == 0, (
            f"Found {len(invalid_types)} invalid expectation types "
            f"from get_llm_generatable_expectations()"
        )

    def test_baseline_types_valid(self, valid_expectation_types: set[str]):
        """Test that all types from get_baseline_only_expectations() are valid."""
        from tablespec.prompts.expectation_guide import get_baseline_only_expectations

        baseline_expectations = get_baseline_only_expectations()
        invalid_types = []

        for exp_type in baseline_expectations:
            if exp_type not in valid_expectation_types:
                invalid_types.append(exp_type)

        if invalid_types:
            print(
                "\n❌ Invalid expectation types from get_baseline_only_expectations():"
            )
            for exp_type in invalid_types:
                print(f"  {exp_type}")

        assert len(invalid_types) == 0, (
            f"Found {len(invalid_types)} invalid expectation types "
            f"from get_baseline_only_expectations()"
        )

    def test_no_duplicate_types_across_categories(self, expectation_categories: dict):
        """Test that expectation types only appear in one category."""
        type_to_categories = {}

        for category_name, category_data in expectation_categories.items():
            if isinstance(category_data, dict) and "expectations" in category_data:
                for exp_type in category_data["expectations"]:
                    if exp_type not in type_to_categories:
                        type_to_categories[exp_type] = []
                    type_to_categories[exp_type].append(category_name)

        # Find duplicates
        duplicates = {
            exp_type: categories
            for exp_type, categories in type_to_categories.items()
            if len(categories) > 1
        }

        if duplicates:
            print("\n❌ Expectation types appearing in multiple categories:")
            for exp_type, categories in duplicates.items():
                print(f"  {exp_type}: {', '.join(categories)}")

        assert len(duplicates) == 0, (
            f"Found {len(duplicates)} expectation types in multiple categories"
        )

    def test_parameter_docs_complete(
        self, expectation_categories: dict, expectation_parameters: dict
    ):
        """Test that every LLM-generatable type has parameter documentation."""
        # Get all LLM-generatable expectations
        llm_types = set()
        for category_name in ["llm_table_level", "llm_column_level"]:
            if category_name in expectation_categories:
                llm_types.update(expectation_categories[category_name]["expectations"])

        # Get all documented parameter types (only from expectation sections)
        documented_types = set()
        expectation_sections = [
            "table_level_expectations",
            "column_level_expectations",
            "pending_fallback",
        ]
        for param_category in expectation_sections:
            if param_category in expectation_parameters:
                documented_types.update(expectation_parameters[param_category].keys())

        # Find missing documentation
        missing_docs = llm_types - documented_types

        if missing_docs:
            print("\n❌ LLM-generatable types missing parameter documentation:")
            for exp_type in sorted(missing_docs):
                print(f"  {exp_type}")

        assert len(missing_docs) == 0, (
            f"Found {len(missing_docs)} LLM-generatable expectation types "
            f"without parameter documentation"
        )

    def test_schema_has_all_documented_types(
        self, valid_expectation_types: set[str], expectation_parameters: dict
    ):
        """Test that GX schema includes all types with parameter documentation.

        This is the inverse check - ensures we haven't documented parameters
        for expectations that don't exist in the schema.
        """
        documented_types = set()

        # Only check sections that contain expectation type definitions
        expectation_sections = [
            "table_level_expectations",
            "column_level_expectations",
            "pending_fallback",
        ]

        for param_category in expectation_sections:
            if param_category in expectation_parameters:
                documented_types.update(expectation_parameters[param_category].keys())

        # Find types documented but not in schema
        extra_docs = documented_types - valid_expectation_types

        if extra_docs:
            print("\n❌ Parameter documentation for types not in GX schema:")
            for exp_type in sorted(extra_docs):
                print(f"  {exp_type}")
            print(
                "\nThese types should either be added to the schema or removed from parameters."
            )

        assert len(extra_docs) == 0, (
            f"Found {len(extra_docs)} documented expectation types that are not in the GX schema"
        )
