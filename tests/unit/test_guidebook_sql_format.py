"""Tests for the guidebook SQL formatter wrapper."""

from tablespec.guidebook.sql_format import format_sql


def test_empty_string_returned_unchanged():
    assert format_sql("") == ""


def test_whitespace_only_returned_unchanged():
    assert format_sql("   \n  ") == "   \n  "


def test_simple_select_uppercases_keywords():
    out = format_sql("select foo from bar where baz = 1")
    assert "SELECT" in out
    assert "FROM" in out
    assert "WHERE" in out


def test_case_statement_gets_reindented():
    raw = "CASE WHEN a IS NULL THEN 'x' WHEN b > 0 THEN 'y' ELSE 'z' END"
    out = format_sql(raw)
    # Reindented output spans multiple lines.
    assert out.count("\n") >= 2
    assert "CASE" in out
    assert "WHEN" in out
    assert "END" in out


def test_unparseable_input_returned_as_is(monkeypatch):
    """If sqlparse raises, we fall back to the original text."""

    def boom(*_args: object, **_kwargs: object) -> str:
        msg = "synthetic sqlparse failure"
        raise RuntimeError(msg)

    monkeypatch.setattr("tablespec.guidebook.sql_format.sqlparse.format", boom)
    raw = "this is not really sql"
    assert format_sql(raw) == raw
