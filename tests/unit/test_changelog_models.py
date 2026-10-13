"""Unit tests for changelog models: ChangeType, ChangeDetail, ChangeEntry."""

# @covers US-014-AC1
# @covers US-014-AC2
# @covers US-014-AC3
# @covers US-014-AC4

from datetime import datetime

import pytest

from tablespec.models.changelog import ChangeDetail, ChangeEntry, ChangeType

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


class TestChangeType:
    """Test ChangeType enum."""

    def test_all_change_types_exist(self):
        assert ChangeType.COLUMN_ADDED == "column_added"
        assert ChangeType.COLUMN_REMOVED == "column_removed"
        assert ChangeType.COLUMN_MODIFIED == "column_modified"
        assert ChangeType.VALIDATION_ADDED == "validation_added"
        assert ChangeType.VALIDATION_REMOVED == "validation_removed"
        assert ChangeType.VALIDATION_MODIFIED == "validation_modified"
        assert ChangeType.RELATIONSHIP_ADDED == "relationship_added"
        assert ChangeType.RELATIONSHIP_REMOVED == "relationship_removed"
        assert ChangeType.RELATIONSHIP_MODIFIED == "relationship_modified"
        assert ChangeType.METADATA_CHANGED == "metadata_changed"
        assert ChangeType.FILE_FORMAT_CHANGED == "file_format_changed"
        assert ChangeType.OTHER == "other"

    def test_change_type_is_str_enum(self):
        assert isinstance(ChangeType.COLUMN_ADDED, str)
        assert ChangeType.COLUMN_ADDED == "column_added"

    def test_change_type_from_value(self):
        assert ChangeType("column_added") is ChangeType.COLUMN_ADDED

    def test_invalid_change_type_raises(self):
        with pytest.raises(ValueError):
            ChangeType("nonexistent")


class TestChangeDetail:
    """Test ChangeDetail dataclass."""

    def test_minimal_change_detail(self):
        detail = ChangeDetail(
            change_type=ChangeType.COLUMN_ADDED,
            description="Added new column",
        )
        assert detail.change_type == ChangeType.COLUMN_ADDED
        assert detail.description == "Added new column"
        assert detail.affected_item is None
        assert detail.old_value is None
        assert detail.new_value is None
        assert detail.file_path is None

    def test_full_change_detail(self):
        detail = ChangeDetail(
            change_type=ChangeType.COLUMN_MODIFIED,
            description="Changed type of col1",
            affected_item="col1",
            old_value="VARCHAR",
            new_value="INTEGER",
            file_path="tables/test.umf.yaml",
        )
        assert detail.affected_item == "col1"
        assert detail.old_value == "VARCHAR"
        assert detail.new_value == "INTEGER"
        assert detail.file_path == "tables/test.umf.yaml"


class TestChangeEntry:
    """Test ChangeEntry dataclass."""

    @pytest.fixture()
    def sample_entry(self):
        return ChangeEntry(
            commit_hash="abc1234",
            commit_date=datetime(2025, 1, 15, 10, 30, 0),
            author_name="Test User",
            author_email="test@example.com",
            commit_message="Add new column for tracking\n\nThis adds birth_date column.",
            review_note="Approved by team lead",
            files_changed=["tables/test.umf.yaml"],
            changes=[
                ChangeDetail(
                    change_type=ChangeType.COLUMN_ADDED,
                    description="Added birth_date column",
                    affected_item="birth_date",
                ),
            ],
            table_name="test_table",
        )

    def test_basic_attributes(self, sample_entry):
        assert sample_entry.commit_hash == "abc1234"
        assert sample_entry.author_name == "Test User"
        assert sample_entry.author_email == "test@example.com"
        assert sample_entry.table_name == "test_table"
        assert len(sample_entry.files_changed) == 1
        assert len(sample_entry.changes) == 1

    def test_summary_returns_first_line(self, sample_entry):
        assert sample_entry.summary == "Add new column for tracking"

    def test_body_returns_rest(self, sample_entry):
        assert sample_entry.body == "This adds birth_date column."

    def test_summary_single_line_message(self):
        entry = ChangeEntry(
            commit_hash="def5678",
            commit_date=datetime(2025, 1, 16),
            author_name="Author",
            author_email="a@b.com",
            commit_message="Single line commit",
            review_note=None,
            files_changed=[],
            changes=[],
        )
        assert entry.summary == "Single line commit"
        assert entry.body == ""

    def test_table_name_defaults_to_none(self):
        entry = ChangeEntry(
            commit_hash="x",
            commit_date=datetime(2025, 1, 1),
            author_name="A",
            author_email="a@b.com",
            commit_message="msg",
            review_note=None,
            files_changed=[],
            changes=[],
        )
        assert entry.table_name is None

    def test_body_with_multiline_message(self):
        entry = ChangeEntry(
            commit_hash="x",
            commit_date=datetime(2025, 1, 1),
            author_name="A",
            author_email="a@b.com",
            commit_message="Summary\n\nLine 1\nLine 2",
            review_note=None,
            files_changed=[],
            changes=[],
        )
        assert entry.summary == "Summary"
        assert entry.body == "Line 1\nLine 2"
