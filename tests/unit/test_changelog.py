"""Unit tests for changelog modules: diff_parser, formatter, generator (pure-logic parts)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tablespec.changelog_diff_parser import (
    ColumnChange,
    DerivationChange,
    MetadataChange,
    RelationshipChange,
    ValidationChange,
    YAMLDiffParser,
)
from tablespec.changelog_formatter import (
    _extract_commit_body_changes,
    _get_change_icon,
    format_changelog_json,
    format_changelog_markdown,
)
from tablespec.models.changelog import ChangeDetail, ChangeEntry, ChangeType

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


# ===========================================================================
# YAMLDiffParser tests
# ===========================================================================


class TestYAMLDiffParserValidation:
    """Test parse_validation_changes."""

    @pytest.fixture()
    def parser(self):
        return YAMLDiffParser()

    def test_detect_added_rule(self, parser):
        old = "expectations: []"
        new = """\
expectations:
  - type: expect_column_values_to_not_be_null
    kwargs:
      column: name
    meta:
      description: name not null
      severity: critical
"""
        changes = parser.parse_validation_changes(old, new, table_name="t")
        assert len(changes) >= 1
        added = [c for c in changes if c.change_field == "added"]
        assert len(added) == 1
        assert added[0].column == "name"
        assert added[0].table_name == "t"

    def test_detect_removed_rule(self, parser):
        old = """\
expectations:
  - type: expect_column_values_to_not_be_null
    kwargs:
      column: name
    meta:
      severity: critical
"""
        new = "expectations: []"
        changes = parser.parse_validation_changes(old, new, table_name="t")
        removed = [c for c in changes if c.change_field == "removed"]
        assert len(removed) == 1

    def test_detect_severity_change(self, parser):
        old = """\
expectations:
  - type: expect_column_values_to_not_be_null
    kwargs:
      column: col1
    meta:
      severity: warning
      description: desc
"""
        new = """\
expectations:
  - type: expect_column_values_to_not_be_null
    kwargs:
      column: col1
    meta:
      severity: critical
      description: desc
"""
        changes = parser.parse_validation_changes(old, new, table_name="t")
        severity_changes = [c for c in changes if c.change_field == "severity"]
        assert len(severity_changes) == 1
        assert severity_changes[0].old_value == "warning"
        assert severity_changes[0].new_value == "critical"

    def test_detect_kwargs_change(self, parser):
        old = """\
expectations:
  - type: expect_column_values_to_be_in_set
    kwargs:
      column: status
      value_set: [A, B]
    meta:
      severity: warning
      description: desc
"""
        new = """\
expectations:
  - type: expect_column_values_to_be_in_set
    kwargs:
      column: status
      value_set: [A, B, C]
    meta:
      severity: warning
      description: desc
"""
        changes = parser.parse_validation_changes(old, new, table_name="t")
        kwargs_changes = [c for c in changes if c.change_field.startswith("kwargs.")]
        assert len(kwargs_changes) >= 1
        vs_change = [c for c in kwargs_changes if "value_set" in c.change_field]
        assert len(vs_change) == 1

    def test_empty_old_content(self, parser):
        new = """\
expectations:
  - type: expect_column_to_exist
    kwargs:
      column: id
    meta:
      severity: critical
"""
        changes = parser.parse_validation_changes("", new, table_name="t")
        assert len(changes) >= 1

    def test_empty_new_content(self, parser):
        old = """\
expectations:
  - type: expect_column_to_exist
    kwargs:
      column: id
    meta:
      severity: critical
"""
        changes = parser.parse_validation_changes(old, "", table_name="t")
        assert len(changes) >= 1

    def test_both_empty_no_changes(self, parser):
        changes = parser.parse_validation_changes("", "", table_name="t")
        assert changes == []

    def test_invalid_yaml_returns_empty(self, parser):
        # Use YAML that parses to non-dict (string), which triggers AttributeError
        # caught by the broad except in the parser - but ruamel.yaml may parse
        # some "invalid" strings successfully. Use truly broken YAML:
        changes = parser.parse_validation_changes(
            ":\n  :\n  - :", ":\n  :\n  - :", table_name="t"
        )
        # Even if parsed, without 'expectations' key, no changes should be detected
        assert changes == []

    def test_no_changes_same_content(self, parser):
        content = """\
expectations:
  - type: expect_column_to_exist
    kwargs:
      column: id
    meta:
      severity: critical
      description: id exists
"""
        changes = parser.parse_validation_changes(content, content, table_name="t")
        assert changes == []


class TestYAMLDiffParserColumns:
    """Test parse_column_changes."""

    @pytest.fixture()
    def parser(self):
        return YAMLDiffParser()

    def test_detect_data_type_change(self, parser):
        old = """\
columns:
  - name: age
    data_type: VARCHAR
    length: 10
"""
        new = """\
columns:
  - name: age
    data_type: INTEGER
    length: 10
"""
        changes = parser.parse_column_changes(old, new, table_name="t")
        assert len(changes) == 1
        assert changes[0].column_name == "age"
        assert changes[0].change_field == "data_type"
        assert changes[0].old_value == "VARCHAR"
        assert changes[0].new_value == "INTEGER"

    def test_detect_description_change(self, parser):
        old = """\
columns:
  - name: col1
    description: old desc
"""
        new = """\
columns:
  - name: col1
    description: new desc
"""
        changes = parser.parse_column_changes(old, new)
        desc_changes = [c for c in changes if c.change_field == "description"]
        assert len(desc_changes) == 1
        assert desc_changes[0].old_value == "old desc"
        assert desc_changes[0].new_value == "new desc"

    def test_detect_nullable_change(self, parser):
        old = "columns:\n  - name: col1\n    nullable: true\n"
        new = "columns:\n  - name: col1\n    nullable: false\n"
        changes = parser.parse_column_changes(old, new)
        assert any(c.change_field == "nullable" for c in changes)

    def test_no_changes_identical(self, parser):
        content = "columns:\n  - name: col1\n    data_type: VARCHAR\n"
        changes = parser.parse_column_changes(content, content)
        assert changes == []

    def test_empty_content_returns_empty(self, parser):
        changes = parser.parse_column_changes("", "")
        assert changes == []

    def test_invalid_yaml_returns_empty(self, parser):
        # Use truly unparseable YAML to trigger the exception handler
        changes = parser.parse_column_changes("\t\t:::", "\t\t:::")
        assert changes == []


class TestYAMLDiffParserRelationships:
    """Test parse_relationship_changes."""

    @pytest.fixture()
    def parser(self):
        return YAMLDiffParser()

    def test_detect_added_relationship(self, parser):
        old = "foreign_keys: []"
        new = """\
foreign_keys:
  - column: user_id
    references_table: users
    references_column: id
"""
        changes = parser.parse_relationship_changes(old, new, table_name="t")
        added = [c for c in changes if c.change_field == "added"]
        assert len(added) == 1
        assert added[0].fk_column == "user_id"
        assert "users.id" in added[0].new_value

    def test_detect_removed_relationship(self, parser):
        old = """\
foreign_keys:
  - column: user_id
    references_table: users
    references_column: id
"""
        new = "foreign_keys: []"
        changes = parser.parse_relationship_changes(old, new, table_name="t")
        removed = [c for c in changes if c.change_field == "removed"]
        assert len(removed) == 1

    def test_detect_references_table_change(self, parser):
        old = """\
foreign_keys:
  - column: user_id
    references_table: users
    references_column: id
"""
        new = """\
foreign_keys:
  - column: user_id
    references_table: members
    references_column: id
"""
        changes = parser.parse_relationship_changes(old, new, table_name="t")
        ref_changes = [c for c in changes if c.change_field == "references_table"]
        assert len(ref_changes) == 1
        assert ref_changes[0].old_value == "users"
        assert ref_changes[0].new_value == "members"

    def test_empty_content(self, parser):
        changes = parser.parse_relationship_changes("", "")
        assert changes == []


class TestYAMLDiffParserMetadata:
    """Test parse_metadata_changes."""

    @pytest.fixture()
    def parser(self):
        return YAMLDiffParser()

    def test_detect_table_name_change(self, parser):
        old = "table_name: old_name\n"
        new = "table_name: new_name\n"
        changes = parser.parse_metadata_changes(old, new)
        assert len(changes) >= 1
        name_change = [c for c in changes if c.change_field == "table_name"]
        assert len(name_change) == 1
        assert name_change[0].old_value == "old_name"
        assert name_change[0].new_value == "new_name"

    def test_detect_version_change(self, parser):
        old = "version: '1.0'\n"
        new = "version: '2.0'\n"
        changes = parser.parse_metadata_changes(old, new)
        version_change = [c for c in changes if c.change_field == "version"]
        assert len(version_change) == 1

    def test_detect_description_change(self, parser):
        old = "description: old\n"
        new = "description: new\n"
        changes = parser.parse_metadata_changes(old, new)
        desc_change = [c for c in changes if c.change_field == "description"]
        assert len(desc_change) == 1

    def test_no_changes_identical(self, parser):
        content = "table_name: same\nversion: '1.0'\n"
        changes = parser.parse_metadata_changes(content, content)
        assert changes == []

    def test_empty_content(self, parser):
        changes = parser.parse_metadata_changes("", "")
        assert changes == []


class TestYAMLDiffParserDerivations:
    """Test parse_derivation_changes."""

    @pytest.fixture()
    def parser(self):
        return YAMLDiffParser()

    def test_detect_strategy_change(self, parser):
        old = """\
derivations:
  mappings:
    col1:
      survivorship:
        strategy: highest_priority
      candidates:
        - table: t1
          column: c1
          priority: 1
"""
        new = """\
derivations:
  mappings:
    col1:
      survivorship:
        strategy: most_recent
      candidates:
        - table: t1
          column: c1
          priority: 1
"""
        changes = parser.parse_derivation_changes(old, new, table_name="t")
        strategy_changes = [c for c in changes if c.change_field == "strategy"]
        assert len(strategy_changes) == 1
        assert strategy_changes[0].old_value == "highest_priority"
        assert strategy_changes[0].new_value == "most_recent"

    def test_detect_candidates_change(self, parser):
        old = """\
derivations:
  mappings:
    col1:
      survivorship:
        strategy: highest_priority
      candidates:
        - table: t1
          column: c1
          priority: 1
"""
        new = """\
derivations:
  mappings:
    col1:
      survivorship:
        strategy: highest_priority
      candidates:
        - table: t1
          column: c1
          priority: 1
        - table: t2
          column: c2
          priority: 2
"""
        changes = parser.parse_derivation_changes(old, new, table_name="t")
        cand_changes = [c for c in changes if c.change_field == "candidates"]
        assert len(cand_changes) == 1
        assert cand_changes[0].old_value == 1
        assert cand_changes[0].new_value == 2

    def test_empty_content(self, parser):
        changes = parser.parse_derivation_changes("", "")
        assert changes == []


# ===========================================================================
# Change dataclass format_description tests
# ===========================================================================


class TestValidationChangeFormat:
    """Test ValidationChange.format_description."""

    def test_severity_change(self):
        vc = ValidationChange(
            rule_id="r1",
            column="col1",
            rule_type="not_null",
            rule_index=0,
            change_field="severity",
            old_value="warning",
            new_value="critical",
            table_name="t",
        )
        desc = vc.format_description()
        assert "severity" in desc
        assert "warning" in desc
        assert "critical" in desc

    def test_kwargs_change(self):
        vc = ValidationChange(
            rule_id="r1",
            column="col1",
            rule_type="in_set",
            rule_index=0,
            change_field="kwargs.value_set",
            old_value="[A]",
            new_value="[A, B]",
        )
        desc = vc.format_description()
        assert "value_set" in desc

    def test_added(self):
        vc = ValidationChange(
            rule_id="r1",
            column="col1",
            rule_type="not_null",
            rule_index=0,
            change_field="added",
            old_value=None,
            new_value=None,
            table_name="t",
        )
        desc = vc.format_description()
        assert "Added" in desc

    def test_removed(self):
        vc = ValidationChange(
            rule_id="r1",
            column="col1",
            rule_type="not_null",
            rule_index=0,
            change_field="removed",
            old_value=None,
            new_value=None,
        )
        desc = vc.format_description()
        assert "Removed" in desc

    def test_no_column(self):
        vc = ValidationChange(
            rule_id="r1",
            column=None,
            rule_type="row_count",
            rule_index=None,
            change_field="added",
            old_value=None,
            new_value=None,
            table_name="t",
        )
        desc = vc.format_description()
        assert "t.row_count" in desc

    def test_generic_change(self):
        vc = ValidationChange(
            rule_id="r1",
            column="c",
            rule_type="x",
            rule_index=0,
            change_field="custom_field",
            old_value="a",
            new_value="b",
        )
        desc = vc.format_description()
        assert "custom_field" in desc
        assert "a" in desc
        assert "b" in desc


class TestColumnChangeFormat:
    def test_data_type_change(self):
        cc = ColumnChange(
            column_name="age",
            change_field="data_type",
            old_value="VARCHAR",
            new_value="INTEGER",
        )
        desc = cc.format_description()
        assert "type" in desc
        assert "VARCHAR" in desc
        assert "INTEGER" in desc

    def test_nullable_change(self):
        cc = ColumnChange(
            column_name="name", change_field="nullable", old_value=True, new_value=False
        )
        desc = cc.format_description()
        assert "nullable" in desc

    def test_generic_field(self):
        cc = ColumnChange(
            column_name="c",
            change_field="length",
            old_value=10,
            new_value=20,
            table_name="t",
        )
        desc = cc.format_description()
        assert "t.c" in desc
        assert "length" in desc


class TestRelationshipChangeFormat:
    def test_added(self):
        rc = RelationshipChange(
            fk_column="user_id",
            change_field="added",
            old_value=None,
            new_value="users.id",
            table_name="orders",
        )
        desc = rc.format_description()
        assert "Added" in desc
        assert "users.id" in desc

    def test_removed(self):
        rc = RelationshipChange(
            fk_column="user_id",
            change_field="removed",
            old_value="users.id",
            new_value=None,
        )
        desc = rc.format_description()
        assert "Removed" in desc

    def test_references_table_change(self):
        rc = RelationshipChange(
            fk_column="fk",
            change_field="references_table",
            old_value="t1",
            new_value="t2",
        )
        desc = rc.format_description()
        assert "table" in desc
        assert "t1" in desc
        assert "t2" in desc

    def test_references_column_change(self):
        rc = RelationshipChange(
            fk_column="fk",
            change_field="references_column",
            old_value="c1",
            new_value="c2",
        )
        desc = rc.format_description()
        assert "column" in desc

    def test_generic_change(self):
        rc = RelationshipChange(
            fk_column="fk", change_field="confidence", old_value=0.5, new_value=0.9
        )
        desc = rc.format_description()
        assert "confidence" in desc


class TestMetadataChangeFormat:
    def test_format(self):
        mc = MetadataChange(change_field="version", old_value="1.0", new_value="2.0")
        assert "version" in mc.format_description()
        assert "1.0" in mc.format_description()
        assert "2.0" in mc.format_description()


class TestDerivationChangeFormat:
    def test_strategy_change(self):
        dc = DerivationChange(
            target_column="col1",
            change_field="strategy",
            old_value="highest_priority",
            new_value="most_recent",
            table_name="t",
        )
        desc = dc.format_description()
        assert "strategy" in desc
        assert "highest_priority" in desc
        assert "most_recent" in desc

    def test_candidates_change(self):
        dc = DerivationChange(
            target_column="col1", change_field="candidates", old_value=1, new_value=2
        )
        desc = dc.format_description()
        assert "candidates" in desc

    def test_generic_change(self):
        dc = DerivationChange(
            target_column="col1", change_field="other", old_value="a", new_value="b"
        )
        desc = dc.format_description()
        assert "other" in desc


# ===========================================================================
# Changelog Formatter tests
# ===========================================================================


def _make_entry(**overrides) -> ChangeEntry:
    """Create a sample ChangeEntry for testing."""
    defaults = {
        "commit_hash": "abc12345",
        "commit_date": datetime(2025, 6, 15, 10, 30, 0, tzinfo=UTC),
        "author_name": "Test User",
        "author_email": "test@example.com",
        "commit_message": "Update validation rules\n\nChanges in test_table:\n- Changed severity from warning to critical\n- Added new rule",
        "review_note": "Approved",
        "files_changed": ["tables/test.yaml"],
        "changes": [
            ChangeDetail(
                change_type=ChangeType.VALIDATION_MODIFIED,
                description="Changed severity from warning to critical",
                affected_item="col1",
                old_value="warning",
                new_value="critical",
                file_path="tables/test.yaml",
            ),
        ],
        "table_name": "test_table",
    }
    defaults.update(overrides)
    return ChangeEntry(**defaults)


class TestFormatChangelogMarkdown:
    def test_empty_entries(self):
        result = format_changelog_markdown([])
        assert "No entries found" in result

    def test_single_entry(self):
        entry = _make_entry()
        result = format_changelog_markdown([entry])
        assert "# Changelog" in result
        assert "abc12345" in result
        assert "Test User" in result
        assert "test@example.com" in result
        assert "2025-06-15" in result

    def test_changes_section(self):
        entry = _make_entry()
        result = format_changelog_markdown([entry])
        assert "### Changes" in result
        assert "Changed severity" in result

    def test_files_changed_section(self):
        entry = _make_entry()
        result = format_changelog_markdown([entry])
        assert "### Files Changed" in result
        assert "tables/test.yaml" in result

    def test_affected_item_in_changes(self):
        entry = _make_entry()
        result = format_changelog_markdown([entry])
        assert "`col1`" in result

    def test_multiple_entries(self):
        e1 = _make_entry(commit_hash="aaa11111")
        e2 = _make_entry(commit_hash="bbb22222")
        result = format_changelog_markdown([e1, e2])
        assert "aaa11111" in result
        assert "bbb22222" in result


class TestFormatChangelogJson:
    def test_empty_entries(self):
        result = format_changelog_json([])
        assert "changelog" in result
        assert result["changelog"] == []
        assert "generated_at" in result

    def test_single_entry_structure(self):
        entry = _make_entry()
        result = format_changelog_json([entry])
        assert len(result["changelog"]) == 1
        item = result["changelog"][0]
        assert item["commit_hash"] == "abc12345"
        assert item["author"]["name"] == "Test User"
        assert item["author"]["email"] == "test@example.com"
        assert item["review_note"] == "Approved"
        assert len(item["changes"]) == 1
        assert item["changes"][0]["type"] == "validation_modified"

    def test_change_detail_fields(self):
        entry = _make_entry()
        result = format_changelog_json([entry])
        change = result["changelog"][0]["changes"][0]
        assert change["description"] == "Changed severity from warning to critical"
        assert change["affected_item"] == "col1"
        assert change["old_value"] == "warning"
        assert change["new_value"] == "critical"
        assert change["file_path"] == "tables/test.yaml"


class TestExtractCommitBodyChanges:
    def test_extract_changes(self):
        msg = "Summary\n\nChanges in table:\n- Change 1\n- Change 2\n\nSource: Excel"
        changes = _extract_commit_body_changes(msg)
        assert changes == ["Change 1", "Change 2"]

    def test_no_changes_section(self):
        msg = "Just a simple commit message"
        changes = _extract_commit_body_changes(msg)
        assert changes == []

    def test_empty_message(self):
        changes = _extract_commit_body_changes("")
        assert changes == []

    def test_changes_until_empty_line(self):
        msg = "Summary\n\nChanges in t:\n- A\n- B\n\nOther stuff"
        changes = _extract_commit_body_changes(msg)
        assert changes == ["A", "B"]

    def test_changes_until_source(self):
        msg = "Summary\n\nChanges in t:\n- A\nSource: Excel"
        changes = _extract_commit_body_changes(msg)
        assert changes == ["A"]


class TestGetChangeIcon:
    def test_known_types(self):
        assert _get_change_icon(ChangeType.COLUMN_ADDED) is not None
        assert _get_change_icon(ChangeType.VALIDATION_MODIFIED) is not None
        assert _get_change_icon(ChangeType.OTHER) is not None

    def test_all_change_types_have_icon(self):
        for ct in ChangeType:
            icon = _get_change_icon(ct)
            assert isinstance(icon, str)
            assert len(icon) > 0


# ===========================================================================
# ChangelogGenerator tests (pure-logic parts, no git required)
# ===========================================================================


class TestChangelogGeneratorReviewNote:
    """Test _extract_review_note logic without git."""

    def test_import_and_instantiation_requires_git_repo(self, tmp_path):
        """ChangelogGenerator requires a valid git repo dir."""
        from tablespec.changelog_generator import ChangelogGenerator

        with pytest.raises(ValueError, match="not in a git repository"):
            ChangelogGenerator(tmp_path)

    def test_nonexistent_dir_raises(self, tmp_path):
        from tablespec.changelog_generator import ChangelogGenerator

        with pytest.raises(ValueError, match="not found"):
            ChangelogGenerator(tmp_path / "nonexistent")

    def test_extract_review_note_inline(self, tmp_path):
        """Test _extract_review_note with inline note."""
        # We need a real git repo to instantiate, so create one
        import git

        git.Repo.init(tmp_path)
        table_dir = tmp_path / "table1"
        table_dir.mkdir()

        from tablespec.changelog_generator import ChangelogGenerator

        gen = ChangelogGenerator(table_dir)

        note = gen._extract_review_note(
            "Summary line\n\nReview Note: This was approved\n"
        )
        assert note == "This was approved"

    def test_extract_review_note_multiline(self, tmp_path):
        import git

        git.Repo.init(tmp_path)
        table_dir = tmp_path / "table1"
        table_dir.mkdir()

        from tablespec.changelog_generator import ChangelogGenerator

        gen = ChangelogGenerator(table_dir)

        note = gen._extract_review_note(
            "Summary\n\nReview Note:\nFirst line\nSecond line\nRule ID: something"
        )
        assert note == "First line Second line"

    def test_extract_review_note_absent(self, tmp_path):
        import git

        git.Repo.init(tmp_path)
        table_dir = tmp_path / "table1"
        table_dir.mkdir()

        from tablespec.changelog_generator import ChangelogGenerator

        gen = ChangelogGenerator(table_dir)

        note = gen._extract_review_note("Just a normal commit\n\nWith some body")
        assert note is None


# ===========================================================================
# ExcelImportCommitter tests (pure-logic parts)
# ===========================================================================


class TestChangelogGeneratorGenerate:
    """Test ChangelogGenerator.generate_changelog with a real git repo."""

    def _setup_repo_with_table(self, tmp_path):
        """Create a git repo with a table directory and some commits."""
        import git

        repo = git.Repo.init(tmp_path)
        # Configure git author
        repo.config_writer().set_value("user", "name", "Test").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        table_dir = tmp_path / "tables" / "my_table"
        table_dir.mkdir(parents=True)

        # Initial commit with a columns file
        col_file = table_dir / "columns" / "col1.yaml"
        col_file.parent.mkdir(parents=True)
        col_file.write_text(
            "columns:\n  - name: col1\n    data_type: VARCHAR\n    length: 10\n"
        )
        repo.index.add([str(col_file.relative_to(tmp_path))])
        repo.index.commit("Initial columns setup")

        # Second commit: modify column
        col_file.write_text(
            "columns:\n  - name: col1\n    data_type: INTEGER\n    length: 10\n"
        )
        repo.index.add([str(col_file.relative_to(tmp_path))])
        repo.index.commit(
            "Update col1 type to INTEGER\n\nReview Note: Approved by data team"
        )

        return repo, table_dir

    def test_generate_changelog_returns_entries(self, tmp_path):
        from tablespec.changelog_generator import ChangelogGenerator

        repo, table_dir = self._setup_repo_with_table(tmp_path)
        gen = ChangelogGenerator(table_dir)
        entries = gen.generate_changelog()

        assert len(entries) >= 1

    def test_generate_changelog_with_limit(self, tmp_path):
        from tablespec.changelog_generator import ChangelogGenerator

        repo, table_dir = self._setup_repo_with_table(tmp_path)
        gen = ChangelogGenerator(table_dir)
        entries = gen.generate_changelog(limit=1)

        assert len(entries) <= 1

    def test_generate_changelog_entries_have_correct_fields(self, tmp_path):
        from tablespec.changelog_generator import ChangelogGenerator

        repo, table_dir = self._setup_repo_with_table(tmp_path)
        gen = ChangelogGenerator(table_dir)
        entries = gen.generate_changelog()

        for entry in entries:
            assert entry.commit_hash
            assert entry.author_name
            assert entry.commit_message
            assert entry.table_name == "my_table"

    def test_generate_changelog_extracts_review_note(self, tmp_path):
        from tablespec.changelog_generator import ChangelogGenerator

        repo, table_dir = self._setup_repo_with_table(tmp_path)
        gen = ChangelogGenerator(table_dir)
        entries = gen.generate_changelog()

        # The second commit has a review note
        notes = [e.review_note for e in entries if e.review_note]
        assert any("Approved by data team" in n for n in notes)

    def test_generate_changelog_detects_column_changes(self, tmp_path):
        from tablespec.changelog_generator import ChangelogGenerator

        repo, table_dir = self._setup_repo_with_table(tmp_path)
        gen = ChangelogGenerator(table_dir)
        entries = gen.generate_changelog()

        # At least one entry should have changes
        all_changes = []
        for e in entries:
            all_changes.extend(e.changes)
        assert len(all_changes) >= 1

    def test_generate_changelog_detects_validation_changes(self, tmp_path):
        import git
        from tablespec.changelog_generator import ChangelogGenerator

        repo = git.Repo.init(tmp_path)
        repo.config_writer().set_value("user", "name", "Test").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        table_dir = tmp_path / "tables" / "t1"
        val_dir = table_dir / "validation"
        val_dir.mkdir(parents=True)

        val_file = val_dir / "rules.yaml"
        val_file.write_text("expectations: []\n")
        repo.index.add([str(val_file.relative_to(tmp_path))])
        repo.index.commit("Add empty validation")

        val_file.write_text(
            "expectations:\n  - type: expect_column_to_exist\n    kwargs:\n      column: id\n    meta:\n      severity: critical\n      description: id exists\n"
        )
        repo.index.add([str(val_file.relative_to(tmp_path))])
        repo.index.commit("Add validation rule")

        gen = ChangelogGenerator(table_dir)
        entries = gen.generate_changelog()

        # Should detect validation changes
        val_changes = [
            c
            for e in entries
            for c in e.changes
            if c.change_type == ChangeType.VALIDATION_MODIFIED
        ]
        assert len(val_changes) >= 1

    def test_generate_changelog_detects_metadata_changes(self, tmp_path):
        import git
        from tablespec.changelog_generator import ChangelogGenerator

        repo = git.Repo.init(tmp_path)
        repo.config_writer().set_value("user", "name", "Test").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        table_dir = tmp_path / "tables" / "t1"
        table_dir.mkdir(parents=True)

        meta_file = table_dir / "metadata.yaml"
        meta_file.write_text("table_name: old\nversion: '1.0'\n")
        repo.index.add([str(meta_file.relative_to(tmp_path))])
        repo.index.commit("Add metadata")

        meta_file.write_text("table_name: new\nversion: '2.0'\n")
        repo.index.add([str(meta_file.relative_to(tmp_path))])
        repo.index.commit("Update metadata")

        gen = ChangelogGenerator(table_dir)
        entries = gen.generate_changelog()

        meta_changes = [
            c
            for e in entries
            for c in e.changes
            if c.change_type == ChangeType.METADATA_CHANGED
        ]
        assert len(meta_changes) >= 1

    def test_generate_changelog_detects_file_format_changes(self, tmp_path):
        import git
        from tablespec.changelog_generator import ChangelogGenerator

        repo = git.Repo.init(tmp_path)
        repo.config_writer().set_value("user", "name", "Test").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        table_dir = tmp_path / "tables" / "t1"
        table_dir.mkdir(parents=True)

        ff_file = table_dir / "file_format.yaml"
        ff_file.write_text("delimiter: ','\n")
        repo.index.add([str(ff_file.relative_to(tmp_path))])
        repo.index.commit("Add file format")

        ff_file.write_text("delimiter: '|'\n")
        repo.index.add([str(ff_file.relative_to(tmp_path))])
        repo.index.commit("Change delimiter")

        gen = ChangelogGenerator(table_dir)
        entries = gen.generate_changelog()

        ff_changes = [
            c
            for e in entries
            for c in e.changes
            if c.change_type == ChangeType.FILE_FORMAT_CHANGED
        ]
        assert len(ff_changes) >= 1

    def test_generate_changelog_handles_other_files(self, tmp_path):
        import git
        from tablespec.changelog_generator import ChangelogGenerator

        repo = git.Repo.init(tmp_path)
        repo.config_writer().set_value("user", "name", "Test").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        table_dir = tmp_path / "tables" / "t1"
        table_dir.mkdir(parents=True)

        other_file = table_dir / "some_other.yaml"
        other_file.write_text("data: 1\n")
        repo.index.add([str(other_file.relative_to(tmp_path))])
        repo.index.commit("Add other file")

        other_file.write_text("data: 2\n")
        repo.index.add([str(other_file.relative_to(tmp_path))])
        repo.index.commit("Modify other file")

        gen = ChangelogGenerator(table_dir)
        entries = gen.generate_changelog()

        other_changes = [
            c for e in entries for c in e.changes if c.change_type == ChangeType.OTHER
        ]
        assert len(other_changes) >= 1


class TestChangelogGeneratorGetFileDiff:
    """Test _get_file_diff method."""

    def test_get_file_diff_returns_old_and_new(self, tmp_path):
        import git
        from tablespec.changelog_generator import ChangelogGenerator

        repo = git.Repo.init(tmp_path)
        repo.config_writer().set_value("user", "name", "Test").release()
        repo.config_writer().set_value("user", "email", "test@test.com").release()

        table_dir = tmp_path / "t"
        table_dir.mkdir()
        f = table_dir / "test.yaml"
        f.write_text("old content")
        repo.index.add([str(f.relative_to(tmp_path))])
        repo.index.commit("first")

        f.write_text("new content")
        repo.index.add([str(f.relative_to(tmp_path))])
        c2 = repo.index.commit("second")

        gen = ChangelogGenerator(table_dir)
        old, new = gen._get_file_diff(c2, f.relative_to(tmp_path))
        assert old == "old content"
        assert new == "new content"


class TestChangelogFormatterConsole:
    """Test format_changelog_console function."""

    def test_empty_entries(self):
        from tablespec.changelog_formatter import format_changelog_console

        # Should not raise
        format_changelog_console([])

    def test_with_entries(self):
        from tablespec.changelog_formatter import format_changelog_console

        entry = _make_entry()
        # Should not raise
        format_changelog_console([entry])

    def test_detailed_mode(self):
        from tablespec.changelog_formatter import format_changelog_console

        entry = _make_entry()
        # Should not raise
        format_changelog_console([entry], detailed=True)


class TestChangelogFormatterTable:
    """Test format_changelog_table function."""

    def test_empty_entries(self):
        from tablespec.changelog_formatter import format_changelog_table

        # Should not raise
        format_changelog_table([])

    def test_with_entries(self):
        from tablespec.changelog_formatter import format_changelog_table

        entry = _make_entry()
        format_changelog_table([entry])

    def test_with_limit(self):
        from tablespec.changelog_formatter import format_changelog_table

        entries = [_make_entry(commit_hash=f"hash{i:04d}") for i in range(20)]
        format_changelog_table(entries, limit=5)


class TestExcelImportCommitter:
    """Test ExcelImportCommitter._generate_commit_message."""

    def test_generate_commit_message_with_notes(self, tmp_path):
        import git

        repo = git.Repo.init(tmp_path)
        # Need at least one commit
        (tmp_path / "dummy.txt").write_text("x")
        repo.index.add(["dummy.txt"])
        repo.index.commit("init")

        from tablespec.excel_import_git import ExcelImportCommitter

        committer = ExcelImportCommitter(tmp_path)
        msg = committer._generate_commit_message(
            "Update from Excel",
            {"validation": "Reviewed by team", "columns": None},
        )
        assert "Update from Excel" in msg
        assert "Review Note: Reviewed by team" in msg
        assert "Source: Excel import" in msg

    def test_generate_commit_message_no_notes(self, tmp_path):
        import git

        repo = git.Repo.init(tmp_path)
        (tmp_path / "dummy.txt").write_text("x")
        repo.index.add(["dummy.txt"])
        repo.index.commit("init")

        from tablespec.excel_import_git import ExcelImportCommitter

        committer = ExcelImportCommitter(tmp_path)
        msg = committer._generate_commit_message("Import update", {})
        assert "Import update" in msg
        assert "Review Note" not in msg

    def test_committer_not_in_git_repo_raises(self, tmp_path):
        from tablespec.excel_import_git import ExcelImportCommitter

        with pytest.raises(ValueError, match="not in a git repository"):
            ExcelImportCommitter(tmp_path)

    def test_commit_changes_empty_files_returns_none(self, tmp_path):
        import git

        repo = git.Repo.init(tmp_path)
        (tmp_path / "dummy.txt").write_text("x")
        repo.index.add(["dummy.txt"])
        repo.index.commit("init")

        from tablespec.excel_import_git import ExcelImportCommitter

        committer = ExcelImportCommitter(tmp_path)
        result = committer.commit_changes([], {})
        assert result is None
