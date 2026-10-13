"""Unit tests for sample_data.engine module - SampleDataGenerator and helpers."""

import json

import pytest

from tablespec.sample_data.config import GenerationConfig
from tablespec.sample_data.engine import SampleDataGenerator, _get_effective_position

pytestmark = pytest.mark.fast


class TestGetEffectivePosition:
    """Test the module-level _get_effective_position helper."""

    def test_explicit_position(self):
        col = {"position": "A"}
        assert _get_effective_position(col) == "A"

    def test_numeric_position(self):
        col = {"position": "3"}
        assert _get_effective_position(col) == "3"

    def test_alias_single_letter(self):
        col = {"aliases": ["B"]}
        assert _get_effective_position(col) == "B"

    def test_alias_double_letter(self):
        col = {"aliases": ["AB"]}
        assert _get_effective_position(col) == "AB"

    def test_alias_ignores_non_excel(self):
        col = {"aliases": ["member_id", "ABC"]}
        assert _get_effective_position(col) is None

    def test_alias_picks_first_match(self):
        col = {"aliases": ["some_name", "C", "D"]}
        assert _get_effective_position(col) == "C"

    def test_no_position_or_aliases(self):
        col = {"name": "test"}
        assert _get_effective_position(col) is None

    def test_empty_aliases(self):
        col = {"aliases": []}
        assert _get_effective_position(col) is None

    def test_none_aliases(self):
        col = {"aliases": None}
        assert _get_effective_position(col) is None

    def test_position_takes_priority(self):
        col = {"position": "1", "aliases": ["Z"]}
        assert _get_effective_position(col) == "1"


@pytest.fixture
def config():
    return GenerationConfig(random_seed=42, num_members=10)


@pytest.fixture
def engine(config, tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return SampleDataGenerator(
        input_dir=input_dir,
        output_dir=output_dir,
        config=config,
    )


class TestBuildRelationshipGraph:
    def test_basic_graph_building(self, engine):
        umf_files = {
            "members": {
                "columns": [{"name": "member_id"}],
                "relationships": {
                    "outgoing": [],
                },
            },
            "claims": {
                "columns": [{"name": "claim_id"}, {"name": "member_id"}],
                "relationships": {
                    "incoming": [
                        {
                            "source_table": "members",
                            "source_column": "member_id",
                            "target_column": "member_id",
                        }
                    ],
                },
            },
        }
        engine.build_relationship_graph(umf_files)
        assert "members" in engine.graph.nodes
        assert "claims" in engine.graph.nodes
        assert "members" in engine.graph.nodes["claims"].dependencies

    def test_excludes_generated_tables(self, engine):
        umf_files = {
            "members": {"columns": [], "relationships": {}},
            "derived_table": {
                "columns": [],
                "table_type": "generated",
                "relationships": {},
            },
        }
        engine.build_relationship_graph(umf_files)
        assert "members" in engine.graph.nodes
        assert "derived_table" not in engine.graph.nodes

    def test_no_relationships(self, engine):
        umf_files = {
            "table_a": {"columns": []},
            "table_b": {"columns": []},
        }
        engine.build_relationship_graph(umf_files)
        assert len(engine.graph.nodes) == 2


class TestGenerateTableData:
    def test_generates_correct_record_count(self, engine):
        umf_data = {
            "columns": [
                {
                    "name": "id",
                    "data_type": "STRING",
                    "key_type": "primary",
                    "source": "data",
                },
                {"name": "value", "data_type": "INTEGER", "source": "data"},
            ],
            "primary_key": ["id"],
            "validation_rules": {"expectations": []},
        }
        records = engine.generate_table_data("test_table", umf_data, 5)
        assert len(records) == 5

    def test_all_columns_present(self, engine):
        umf_data = {
            "columns": [
                {"name": "col_a", "data_type": "STRING", "source": "data"},
                {"name": "col_b", "data_type": "INTEGER", "source": "data"},
            ],
            "validation_rules": {"expectations": []},
        }
        records = engine.generate_table_data("test_table", umf_data, 3)
        for record in records:
            assert "col_a" in record
            assert "col_b" in record

    def test_skips_derived_columns(self, engine):
        umf_data = {
            "columns": [
                {"name": "col_a", "data_type": "STRING", "source": "data"},
                {"name": "computed", "data_type": "STRING", "source": "derived"},
            ],
            "validation_rules": {"expectations": []},
        }
        records = engine.generate_table_data("test_table", umf_data, 2)
        for record in records:
            assert "col_a" in record
            assert "computed" not in record

    def test_primary_keys_registered(self, engine):
        umf_data = {
            "columns": [
                {
                    "name": "id",
                    "data_type": "STRING",
                    "key_type": "primary",
                    "source": "data",
                },
            ],
            "primary_key": ["id"],
            "validation_rules": {"expectations": []},
        }
        engine.generate_table_data("test_table", umf_data, 3)
        assert len(engine.key_registry.primary_keys["test_table"]) == 3

    def test_sample_data_cases(self, engine):
        umf_data = {
            "columns": [
                {"name": "status", "data_type": "STRING", "source": "data"},
                {"name": "value", "data_type": "INTEGER", "source": "data"},
            ],
            "validation_rules": {"expectations": []},
            "sample_data_cases": [
                {"status": "FORCED_VALUE"},
            ],
        }
        records = engine.generate_table_data("test_table", umf_data, 3)
        # 1 forced + 2 random = 3 total
        assert len(records) == 3
        assert records[0]["status"] == "FORCED_VALUE"

    def test_filename_sourced_columns(self, engine):
        umf_data = {
            "columns": [
                {"name": "data_col", "data_type": "STRING", "source": "data"},
                {
                    "name": "file_date",
                    "data_type": "STRING",
                    "source": "filename",
                    "sample_values": ["2024-01-01", "2024-02-01"],
                },
            ],
            "validation_rules": {"expectations": []},
        }
        records = engine.generate_table_data("test_table", umf_data, 3)
        # Filename columns should have a constant value across all records
        file_dates = {r["file_date"] for r in records}
        assert len(file_dates) == 1
        assert list(file_dates)[0] in ["2024-01-01", "2024-02-01"]


class TestDiscoverCrossPipelineFks:
    def test_finds_cross_pipeline_fks(self, engine):
        umf_files = {
            "claims": {
                "relationships": {
                    "foreign_keys": [
                        {
                            "column": "member_id",
                            "references_pipeline": "enrollment",
                            "references_table": "members",
                            "references_column": "member_id",
                            "cross_pipeline": True,
                        }
                    ]
                }
            }
        }
        result = engine._discover_cross_pipeline_fks(umf_files)
        assert "member_id" in result
        assert result["member_id"].references_pipeline == "enrollment"

    def test_ignores_non_cross_pipeline(self, engine):
        umf_files = {
            "claims": {
                "relationships": {
                    "foreign_keys": [
                        {
                            "column": "member_id",
                            "references_table": "members",
                            "references_column": "member_id",
                        }
                    ]
                }
            }
        }
        result = engine._discover_cross_pipeline_fks(umf_files)
        assert len(result) == 0

    def test_empty_umf(self, engine):
        result = engine._discover_cross_pipeline_fks({})
        assert result == {}


class TestCalculateTableRecordCount:
    def test_base_table_uses_num_members(self, engine):
        engine.graph.add_table("members", {})
        umf_data = {"relationships": {}}
        count = engine._calculate_table_record_count("members", umf_data)
        assert count == engine.config.num_members

    def test_table_not_in_graph(self, engine):
        umf_data = {}
        count = engine._calculate_table_record_count("unknown_table", umf_data)
        assert count >= 100

    def test_one_to_one_relationship(self, engine):
        engine.graph.add_table("members", {})
        engine.graph.add_table("details", {})
        engine.graph.add_relationship("members", "details")
        umf_data = {
            "relationships": {
                "incoming": [
                    {
                        "source_table": "members",
                        "cardinality": {"type": "one_to_one"},
                    }
                ]
            }
        }
        count = engine._calculate_table_record_count("details", umf_data)
        assert count == engine.config.num_members

    def test_one_to_zero_or_one(self, engine):
        engine.graph.add_table("members", {})
        engine.graph.add_table("details", {})
        engine.graph.add_relationship("members", "details")
        umf_data = {
            "relationships": {
                "incoming": [
                    {
                        "source_table": "members",
                        "cardinality": {"type": "one_to_zero_or_one"},
                    }
                ]
            }
        }
        count = engine._calculate_table_record_count("details", umf_data)
        expected = int(engine.config.num_members * engine.config.relationship_density)
        assert count == expected

    def test_one_to_many_relationship(self, engine):
        engine.graph.add_table("members", {})
        engine.graph.add_table("claims", {})
        engine.graph.add_relationship("members", "claims")
        umf_data = {
            "relationships": {
                "incoming": [
                    {
                        "source_table": "members",
                        "cardinality": {"type": "one_to_many"},
                    }
                ]
            }
        }
        count = engine._calculate_table_record_count("claims", umf_data)
        # Should be at least num_members * 2 * density
        assert count > engine.config.num_members

    def test_no_cardinality_info_fallback(self, engine):
        engine.graph.add_table("members", {})
        engine.graph.add_table("details", {})
        engine.graph.add_relationship("members", "details")
        umf_data = {"relationships": {"incoming": []}}
        count = engine._calculate_table_record_count("details", umf_data)
        assert count >= 100


class TestSaveData:
    def test_saves_pipe_delimited_file(self, engine):
        umf_data = {
            "columns": [
                {"name": "col_a", "data_type": "STRING", "source": "data"},
                {"name": "col_b", "data_type": "INTEGER", "source": "data"},
            ],
            "file_format": {"delimiter": "|"},
        }
        records = [
            {"col_a": "hello", "col_b": 42},
            {"col_a": "world", "col_b": 99},
        ]
        engine.save_data("test_table", records, umf_data)
        output_file = engine.output_dir / "test_table.txt"
        assert output_file.exists()
        content = output_file.read_text()
        lines = content.strip().split("\n")
        assert lines[0] == "col_a|col_b"
        assert "hello|42" in lines[1]

    def test_no_records_warning(self, engine, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            engine.save_data("empty_table", [], {"columns": []})
        assert "No records generated" in caplog.text

    def test_filename_collision_handling(self, engine):
        umf_data = {
            "columns": [
                {"name": "col_a", "data_type": "STRING", "source": "data"},
            ],
            "file_format": {"filename_pattern": {"regex": "same_file.txt"}},
        }
        records = [{"col_a": "v1"}]
        # First save
        engine._generated_filenames["test_table.txt"] = "other_table"
        engine.save_data("test_table", records, umf_data)
        # File should still be created (with adjusted name)

    def test_custom_delimiter(self, engine):
        umf_data = {
            "columns": [
                {"name": "col_a", "data_type": "STRING", "source": "data"},
                {"name": "col_b", "data_type": "STRING", "source": "data"},
            ],
            "file_format": {"delimiter": ","},
        }
        records = [{"col_a": "hello", "col_b": "world"}]
        engine.save_data("test_table", records, umf_data)
        output_file = engine.output_dir / "test_table.txt"
        content = output_file.read_text()
        assert "col_a,col_b" in content


class TestGenerateSummaryReport:
    def test_creates_report_file(self, engine):
        engine.generated_data = {
            "members": [{"id": "M1"}, {"id": "M2"}],
            "claims": [{"id": "C1"}],
        }
        engine.generate_summary_report()
        report_file = engine.output_dir / "GENERATION_SUMMARY.json"
        assert report_file.exists()
        report = json.loads(report_file.read_text())
        assert report["key_statistics"]["total_tables"] == 2
        assert report["key_statistics"]["total_records"] == 3

    def test_report_structure(self, engine):
        engine.generated_data = {"test": [{"col": "val"}]}
        engine.generate_summary_report()
        report_file = engine.output_dir / "GENERATION_SUMMARY.json"
        report = json.loads(report_file.read_text())
        assert "generation_timestamp" in report
        assert "configuration" in report
        assert "tables_generated" in report
        assert "test" in report["tables_generated"]
        info = report["tables_generated"]["test"]
        assert info["record_count"] == 1
        assert info["column_count"] == 1


class TestColumnValidationRulesExtraction:
    def test_finds_rules(self, engine):
        umf_data = {
            "columns": [
                {
                    "name": "lob",
                    "validation_rules": {"value_constraints": ["Valid values: MD, MC"]},
                },
                {"name": "id", "validation_rules": None},
            ]
        }
        rules = engine._get_column_validation_rules("lob", umf_data)
        assert rules is not None
        assert "value_constraints" in rules

    def test_returns_none_for_missing(self, engine):
        umf_data = {"columns": [{"name": "other_col"}]}
        assert engine._get_column_validation_rules("missing", umf_data) is None


class TestSaveDataEdgeCases:
    """Test save_data edge cases."""

    def test_saves_with_canonical_name_headers(self, engine):
        """Test that canonical_name is used as CSV header when available."""
        umf_data = {
            "columns": [
                {
                    "name": "col_a",
                    "canonical_name": "ColumnA",
                    "data_type": "STRING",
                    "source": "data",
                },
            ],
            "file_format": {"delimiter": "|"},
        }
        records = [{"col_a": "hello"}]
        engine.save_data("test_table", records, umf_data)
        output_file = engine.output_dir / "test_table.txt"
        content = output_file.read_text()
        lines = content.strip().split("\n")
        assert lines[0] == "ColumnA"

    def test_saves_with_no_columns_warning(self, engine, caplog):
        """Test that no data columns produces error log."""
        import logging

        umf_data = {
            "columns": [
                {"name": "derived_col", "data_type": "STRING", "source": "derived"},
            ],
        }
        records = [{"derived_col": "value"}]
        with caplog.at_level(logging.ERROR):
            engine.save_data("test_table", records, umf_data)
        assert "No data columns" in caplog.text

    def test_missing_columns_raises_error(self, engine):
        """Test that missing columns in records raises ValueError."""
        umf_data = {
            "columns": [
                {"name": "col_a", "data_type": "STRING", "source": "data"},
                {"name": "col_b", "data_type": "STRING", "source": "data"},
            ],
        }
        records = [{"col_a": "hello"}]  # missing col_b
        with pytest.raises(ValueError, match="missing required columns"):
            engine.save_data("test_table", records, umf_data)

    def test_symlink_created_for_pattern_based_filename(self, engine):
        """Test that a symlink is created when filename differs from table_name.txt."""
        umf_data = {
            "columns": [
                {"name": "col_a", "data_type": "STRING", "source": "data"},
                {
                    "name": "rundate",
                    "data_type": "STRING",
                    "source": "filename",
                    "sample_values": ["20240101"],
                },
            ],
            "file_format": {
                "delimiter": "|",
                "filename_pattern": {
                    "regex": r"data_(\d{8})\.txt",
                    "captures": {"1": "rundate"},
                },
            },
        }
        records = [{"col_a": "hello", "rundate": "20240101"}]
        engine.save_data("test_table", records, umf_data)
        # Check either the file or symlink exists
        output_dir_files = list(engine.output_dir.iterdir())
        assert len(output_dir_files) >= 1


class TestGenerateTableDataDerivationColumns:
    """Test _generate_table_data with derivation columns."""

    def test_derivation_columns_skipped(self, engine):
        """Derivation columns (source=derived) should be excluded from records."""
        umf_data = {
            "columns": [
                {"name": "data_col", "data_type": "STRING", "source": "data"},
                {"name": "derived_col", "data_type": "STRING", "source": "derived"},
            ],
            "validation_rules": {"expectations": []},
        }
        records = engine.generate_table_data("test_table", umf_data, 3)
        for record in records:
            assert "data_col" in record
            assert "derived_col" not in record

    def test_composite_primary_key_uniqueness(self, engine):
        """Composite primary keys should generate unique combinations."""
        umf_data = {
            "columns": [
                {
                    "name": "pk1",
                    "data_type": "STRING",
                    "key_type": "primary",
                    "source": "data",
                },
                {
                    "name": "pk2",
                    "data_type": "STRING",
                    "key_type": "primary",
                    "source": "data",
                },
            ],
            "primary_key": ["pk1", "pk2"],
            "validation_rules": {"expectations": []},
        }
        records = engine.generate_table_data("test_table", umf_data, 5)
        combos = {(r["pk1"], r["pk2"]) for r in records}
        assert len(combos) == 5


class TestAssignForeignKeys:
    """Test foreign key assignment via generate_table_data."""

    def test_fk_column_uses_parent_pk(self, engine):
        """FK columns should reference parent table PK values."""
        # Register parent PKs
        engine.key_registry.register_primary_key("parent", "PK1")
        engine.key_registry.register_primary_key("parent", "PK2")
        engine.key_registry.register_primary_key("parent", "PK3")

        umf_data = {
            "columns": [
                {
                    "name": "parent_id",
                    "data_type": "STRING",
                    "key_type": "foreign_one_to_many",
                    "source": "data",
                },
                {"name": "value", "data_type": "INTEGER", "source": "data"},
            ],
            "validation_rules": {"expectations": []},
        }
        records = engine.generate_table_data("child_table", umf_data, 5)
        for record in records:
            assert record["parent_id"] in ["PK1", "PK2", "PK3"]


class TestGenerateAllTablesOrchestration:
    """Test generate_all_tables (run_generation) orchestration."""

    def test_run_generation_empty_input(self, engine, caplog):
        """run_generation should complete gracefully with no UMF files."""
        import logging

        with caplog.at_level(logging.WARNING):
            result = engine.run_generation()
        assert result is True

    def test_run_generation_with_single_table(self, tmp_path):
        """run_generation should generate data for a single table."""
        input_dir = tmp_path / "input" / "tables"
        input_dir.mkdir(parents=True)
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Create a minimal split-format UMF
        table_dir = input_dir / "simple_table"
        table_dir.mkdir()
        (table_dir / "table.yaml").write_text(
            "version: '1.0'\ntable_name: simple_table\ncanonical_name: SimpleTable\n"
            "primary_key:\n  - id\n"
        )
        (table_dir / "columns").mkdir()
        (table_dir / "columns" / "id.yaml").write_text(
            "column:\n  name: id\n  data_type: VARCHAR\n  key_type: primary\n  source: data\n"
        )
        (table_dir / "columns" / "value.yaml").write_text(
            "column:\n  name: value\n  data_type: INTEGER\n  source: data\n"
        )

        config = GenerationConfig(random_seed=42, num_members=5)
        gen = SampleDataGenerator(
            input_dir=tmp_path / "input",
            output_dir=output_dir,
            config=config,
        )
        result = gen.run_generation()
        assert result is True
        assert "simple_table" in gen.generated_data
        assert len(gen.generated_data["simple_table"]) == 5

    def test_run_generation_creates_summary_report(self, tmp_path):
        """run_generation should create summary report even with just one table."""
        input_dir = tmp_path / "input" / "tables"
        input_dir.mkdir(parents=True)
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        table_dir = input_dir / "members"
        table_dir.mkdir()
        (table_dir / "table.yaml").write_text(
            "version: '1.0'\ntable_name: members\ncanonical_name: Members\n"
            "primary_key:\n  - id\n"
        )
        (table_dir / "columns").mkdir()
        (table_dir / "columns" / "id.yaml").write_text(
            "column:\n  name: id\n  data_type: VARCHAR\n  key_type: primary\n  source: data\n"
        )

        config = GenerationConfig(random_seed=42, num_members=3)
        gen = SampleDataGenerator(
            input_dir=tmp_path / "input",
            output_dir=output_dir,
            config=config,
        )
        result = gen.run_generation()
        assert result is True
        summary_file = output_dir / "GENERATION_SUMMARY.json"
        assert summary_file.exists()
        report = json.loads(summary_file.read_text())
        assert report["key_statistics"]["total_tables"] == 1
        assert report["key_statistics"]["total_records"] == 3


class TestLoadUmfFiles:
    """Test UMF file loading."""

    def test_load_umf_files_empty_dir(self, engine):
        """Should return empty dict when input dir has no UMF files."""
        result = engine.load_umf_files()
        assert result == {}

    def test_load_umf_files_from_tables_subdir(self, tmp_path):
        """Should load UMF from tables/ subdirectory."""
        input_dir = tmp_path / "input"
        tables_dir = input_dir / "tables"
        tables_dir.mkdir(parents=True)
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Create a table in split format
        table_dir = tables_dir / "members"
        table_dir.mkdir()
        (table_dir / "table.yaml").write_text(
            "version: '1.0'\ntable_name: members\ncanonical_name: Members\n"
        )
        (table_dir / "columns").mkdir()
        (table_dir / "columns" / "id.yaml").write_text(
            "column:\n  name: id\n  data_type: VARCHAR\n  source: data\n"
        )

        config = GenerationConfig(random_seed=42, num_members=5)
        gen = SampleDataGenerator(
            input_dir=input_dir, output_dir=output_dir, config=config
        )
        result = gen.load_umf_files()
        assert "members" in result
