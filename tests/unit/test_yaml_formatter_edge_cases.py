"""Edge case tests for YAML formatter - file operations, sort_recursive, prepare_for_yaml.

Covers format_yaml_file, format_yaml_files, sort_recursive with CommentedMap/CommentedSeq,
prepare_for_yaml with control characters, and other edge cases not in test_yaml_formatter.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import LiteralScalarString, SingleQuotedScalarString

from tablespec.formatting.yaml_formatter import (
    YAMLFormatError,
    format_yaml_dict,
    format_yaml_file,
    format_yaml_files,
    format_yaml_string,
    prepare_for_yaml,
    sort_recursive,
)

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


# --- sort_recursive Tests ---


class TestSortRecursive:
    """Test sort_recursive function with various data types."""

    def test_plain_dict_sorted(self):
        result = sort_recursive({"z": 1, "a": 2, "m": 3})
        assert list(result.keys()) == ["a", "m", "z"]

    def test_nested_dict_sorted(self):
        result = sort_recursive({"z": {"b": 1, "a": 2}, "a": 3})
        assert list(result.keys()) == ["a", "z"]
        assert list(result["z"].keys()) == ["a", "b"]

    def test_list_order_preserved(self):
        result = sort_recursive([3, 1, 2])
        assert result == [3, 1, 2]

    def test_list_of_dicts_sorted_keys_preserved_order(self):
        result = sort_recursive([{"z": 1, "a": 2}, {"y": 3, "b": 4}])
        assert list(result[0].keys()) == ["a", "z"]
        assert list(result[1].keys()) == ["b", "y"]

    def test_commented_map_sorted(self):
        cm = CommentedMap()
        cm["z"] = 1
        cm["a"] = 2
        cm["m"] = 3
        result = sort_recursive(cm)
        assert isinstance(result, CommentedMap)
        assert list(result.keys()) == ["a", "m", "z"]

    def test_commented_seq_preserved(self):
        cs = CommentedSeq([3, 1, 2])
        result = sort_recursive(cs)
        assert isinstance(result, CommentedSeq)
        assert list(result) == [3, 1, 2]

    def test_non_collection_passthrough(self):
        assert sort_recursive(42) == 42
        assert sort_recursive("hello") == "hello"
        assert sort_recursive(None) is None
        assert sort_recursive(True) is True

    def test_empty_dict(self):
        assert sort_recursive({}) == {}

    def test_empty_list(self):
        assert sort_recursive([]) == []

    def test_commented_map_with_comments(self):
        cm = CommentedMap()
        cm["b"] = "val_b"
        cm["a"] = "val_a"
        cm.yaml_set_comment_before_after_key("b", before="comment on b")
        result = sort_recursive(cm)
        assert list(result.keys()) == ["a", "b"]

    def test_deeply_nested_mixed(self):
        data = {
            "z": [{"c": 1, "a": 2}],
            "a": {"d": [1, 2], "b": "text"},
        }
        result = sort_recursive(data)
        assert list(result.keys()) == ["a", "z"]
        assert list(result["a"].keys()) == ["b", "d"]
        assert list(result["z"][0].keys()) == ["a", "c"]


# --- prepare_for_yaml Tests ---


class TestPrepareForYaml:
    """Test prepare_for_yaml function."""

    def test_multiline_string_becomes_literal(self):
        result = prepare_for_yaml("line1\nline2\nline3")
        assert isinstance(result, LiteralScalarString)

    def test_single_line_string_unchanged(self):
        result = prepare_for_yaml("simple text")
        assert result == "simple text"
        assert not isinstance(result, LiteralScalarString)

    def test_boolean_string_quoted(self):
        for val in [
            "true",
            "True",
            "TRUE",
            "false",
            "False",
            "FALSE",
            "yes",
            "Yes",
            "YES",
            "no",
            "No",
            "NO",
            "on",
            "On",
            "ON",
            "off",
            "Off",
            "OFF",
        ]:
            result = prepare_for_yaml(val)
            assert isinstance(result, SingleQuotedScalarString), f"{val} not quoted"

    def test_null_string_quoted(self):
        for val in ["null", "Null", "NULL", "~"]:
            result = prepare_for_yaml(val)
            assert isinstance(result, SingleQuotedScalarString), f"{val} not quoted"

    def test_control_chars_not_literal(self):
        # String with bell character (0x07) should not become literal block
        result = prepare_for_yaml("hello\x07world")
        assert not isinstance(result, LiteralScalarString)
        assert result == "hello\x07world"

    def test_del_char_not_literal(self):
        result = prepare_for_yaml("data\x7fmore")
        assert not isinstance(result, LiteralScalarString)

    def test_c1_control_chars_not_literal(self):
        result = prepare_for_yaml("text\x85more")
        assert not isinstance(result, LiteralScalarString)

    def test_leading_whitespace_not_literal(self):
        result = prepare_for_yaml("  leading spaces")
        assert not isinstance(result, LiteralScalarString)

    def test_trailing_whitespace_not_literal(self):
        result = prepare_for_yaml("trailing spaces  ")
        assert not isinstance(result, LiteralScalarString)

    def test_tab_in_string_allowed_literal(self):
        # Tab is allowed in literal blocks
        result = prepare_for_yaml("line1\n\tindented")
        assert isinstance(result, LiteralScalarString)

    def test_non_string_passthrough(self):
        assert prepare_for_yaml(42) == 42
        assert prepare_for_yaml(3.14) == 3.14
        assert prepare_for_yaml(True) is True
        assert prepare_for_yaml(None) is None

    def test_dict_recursion(self):
        result = prepare_for_yaml({"key": "line1\nline2"})
        assert isinstance(result["key"], LiteralScalarString)

    def test_list_recursion(self):
        result = prepare_for_yaml(["true", "normal"])
        assert isinstance(result[0], SingleQuotedScalarString)
        assert result[1] == "normal"

    def test_commented_map_recursion(self):
        cm = CommentedMap()
        cm["key"] = "true"
        result = prepare_for_yaml(cm)
        assert isinstance(result, CommentedMap)
        assert isinstance(result["key"], SingleQuotedScalarString)

    def test_commented_seq_recursion(self):
        cs = CommentedSeq(["false", "regular"])
        result = prepare_for_yaml(cs)
        assert isinstance(result, CommentedSeq)
        assert isinstance(result[0], SingleQuotedScalarString)

    def test_empty_string(self):
        # Empty string has no leading/trailing whitespace issue
        result = prepare_for_yaml("")
        assert result == ""


# --- format_yaml_file Tests ---


class TestFormatYamlFile:
    """Test format_yaml_file function."""

    def test_format_file(self, tmp_path: Path):
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("z: 1\na: 2\n", encoding="utf-8")
        changed = format_yaml_file(yaml_file)
        assert changed is True
        content = yaml_file.read_text(encoding="utf-8")
        assert content.index("a:") < content.index("z:")

    def test_no_change_when_already_formatted(self, tmp_path: Path):
        yaml_file = tmp_path / "sorted.yaml"
        yaml_file.write_text("a: 1\nz: 2\n", encoding="utf-8")
        changed = format_yaml_file(yaml_file)
        assert changed is False

    def test_check_only_mode(self, tmp_path: Path):
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("z: 1\na: 2\n", encoding="utf-8")
        changed = format_yaml_file(yaml_file, check_only=True)
        assert changed is True
        # File should not be modified
        content = yaml_file.read_text(encoding="utf-8")
        assert content == "z: 1\na: 2\n"

    def test_check_only_no_change(self, tmp_path: Path):
        yaml_file = tmp_path / "sorted.yaml"
        yaml_file.write_text("a: 1\nz: 2\n", encoding="utf-8")
        changed = format_yaml_file(yaml_file, check_only=True)
        assert changed is False

    def test_nonexistent_file_raises(self, tmp_path: Path):
        with pytest.raises(YAMLFormatError, match="File not found"):
            format_yaml_file(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml_raises(self, tmp_path: Path):
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("{{invalid: yaml [", encoding="utf-8")
        with pytest.raises(YAMLFormatError):
            format_yaml_file(bad_file)


# --- format_yaml_files Tests ---


class TestFormatYamlFiles:
    """Test format_yaml_files function."""

    def test_format_multiple_files(self, tmp_path: Path):
        f1 = tmp_path / "a.yaml"
        f2 = tmp_path / "b.yaml"
        f1.write_text("z: 1\na: 2\n", encoding="utf-8")
        f2.write_text("y: 3\nb: 4\n", encoding="utf-8")
        changed, errors, messages = format_yaml_files([f1, f2])
        assert changed == 2
        assert errors == 0
        assert messages == []

    def test_some_already_formatted(self, tmp_path: Path):
        f1 = tmp_path / "sorted.yaml"
        f2 = tmp_path / "unsorted.yaml"
        f1.write_text("a: 1\nz: 2\n", encoding="utf-8")
        f2.write_text("z: 1\na: 2\n", encoding="utf-8")
        changed, errors, messages = format_yaml_files([f1, f2])
        assert changed == 1
        assert errors == 0

    def test_error_handling(self, tmp_path: Path):
        good = tmp_path / "good.yaml"
        bad = tmp_path / "bad.yaml"
        good.write_text("a: 1\n", encoding="utf-8")
        bad.write_text("{{invalid yaml", encoding="utf-8")
        changed, errors, messages = format_yaml_files([good, bad])
        assert errors == 1
        assert len(messages) == 1

    def test_check_only_mode(self, tmp_path: Path):
        f1 = tmp_path / "test.yaml"
        f1.write_text("z: 1\na: 2\n", encoding="utf-8")
        changed, errors, messages = format_yaml_files([f1], check_only=True)
        assert changed == 1
        # File unchanged
        assert f1.read_text() == "z: 1\na: 2\n"

    def test_empty_file_list(self):
        changed, errors, messages = format_yaml_files([])
        assert changed == 0
        assert errors == 0
        assert messages == []


# --- format_yaml_string Edge Cases ---


class TestFormatYamlStringEdgeCases:
    """Additional edge cases for format_yaml_string."""

    def test_empty_yaml_returns_original(self):
        result = format_yaml_string("")
        assert result == ""

    def test_document_start_marker_stripped(self):
        result = format_yaml_string("---\na: 1\n")
        assert not result.startswith("---")
        assert "a: 1" in result

    def test_document_start_without_newline(self):
        result = format_yaml_string("---a: 1\n")
        assert "a: 1" in result

    def test_top_level_list_raises(self):
        with pytest.raises(YAMLFormatError, match="Top-level lists"):
            format_yaml_string("- item1\n- item2\n")

    def test_none_yaml_returns_original(self):
        # YAML that parses to None
        result = format_yaml_string("---\n")
        assert result == "---\n"


# --- format_yaml_dict Edge Cases ---


class TestFormatYamlDictEdgeCases:
    """Additional edge cases for format_yaml_dict."""

    def test_non_dict_raises(self):
        with pytest.raises(YAMLFormatError, match="Expected dict"):
            format_yaml_dict([1, 2, 3])  # type: ignore[arg-type]

    def test_empty_dict(self):
        result = format_yaml_dict({})
        assert result.strip() == "{}"

    def test_nested_multiline_in_dict(self):
        data = {"desc": "line1\nline2"}
        result = format_yaml_dict(data)
        assert "|-" in result or "|\n" in result

    def test_numeric_values_preserved(self):
        import yaml

        data = {"count": 42, "rate": 3.14, "flag": True}
        result = format_yaml_dict(data)
        parsed = yaml.safe_load(result)
        assert parsed["count"] == 42
        assert parsed["rate"] == pytest.approx(3.14)
        assert parsed["flag"] is True
