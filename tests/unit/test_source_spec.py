"""Tests for the discriminated ``source:`` block (FEAT-031 SRC-01..05, JDBC-01).

Covers: jdbc source validation with secret-ref credentials, the file_format
back-compat alias resolved via ``UMF.effective_source()`` (never by mutating
the document), plaintext-password rejection, and discriminator behavior.
"""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from tablespec.models.umf import (
    UMF,
    DelimitedSource,
    JdbcSource,
    ParquetSource,
    load_umf_from_yaml,
    save_umf_to_yaml,
)

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


def _base(**extra) -> dict:
    return {
        "version": "1.0",
        "table_name": "members",
        "columns": [{"name": "member_id", "data_type": "INTEGER"}],
        **extra,
    }


class TestJdbcSource:
    def test_jdbc_source_validates_with_secret_ref(self):
        umf = UMF(
            **_base(
                source={
                    "kind": "jdbc",
                    "url": "jdbc:sqlserver://host:1433;databaseName=db",
                    "dbtable": "dbo.members",
                    "user": "svc_reader",
                    "password_secret_ref": "scope/jdbc-password",
                }
            )
        )
        assert isinstance(umf.source, JdbcSource)
        assert umf.source.kind == "jdbc"
        assert umf.source.password_secret_ref == "scope/jdbc-password"
        assert umf.effective_source() is umf.source

    def test_jdbc_source_with_query_instead_of_dbtable(self):
        spec = JdbcSource(
            kind="jdbc", url="jdbc:postgresql://h/db", query="SELECT 1 AS x"
        )
        assert spec.query == "SELECT 1 AS x"

    def test_plaintext_password_raises(self):
        with pytest.raises(ValidationError):
            UMF(
                **_base(
                    source={
                        "kind": "jdbc",
                        "url": "jdbc:sqlserver://host",
                        "dbtable": "dbo.members",
                        "password": "hunter2",
                    }
                )
            )

    def test_dbtable_and_query_mutually_exclusive(self):
        with pytest.raises(ValidationError, match="exactly one"):
            JdbcSource(
                kind="jdbc",
                url="jdbc:x",
                dbtable="dbo.t",
                query="SELECT 1",
            )

    def test_one_of_dbtable_or_query_required(self):
        with pytest.raises(ValidationError, match="exactly one"):
            JdbcSource(kind="jdbc", url="jdbc:x")

    def test_url_required(self):
        with pytest.raises(ValidationError):
            JdbcSource(kind="jdbc", dbtable="dbo.t")  # type: ignore[call-arg]


class TestDiscriminator:
    def test_unknown_kind_rejected(self):
        with pytest.raises(ValidationError):
            UMF(**_base(source={"kind": "carrier_pigeon"}))

    def test_kind_required_to_discriminate(self):
        with pytest.raises(ValidationError):
            UMF(**_base(source={"delimiter": ","}))

    def test_parquet_stub_validates(self):
        umf = UMF(**_base(source={"kind": "parquet", "path": "/data/members"}))
        assert isinstance(umf.source, ParquetSource)


class TestFileFormatAlias:
    def test_absent_source_resolves_to_delimited_defaults(self):
        umf = UMF(**_base())
        spec = umf.effective_source()
        assert isinstance(spec, DelimitedSource)
        assert spec.kind == "delimited"
        assert spec.delimiter == "|"
        assert umf.source is None  # accessor never mutates the document

    def test_file_format_derives_delimited_source(self):
        umf = UMF(**_base(file_format={"delimiter": ",", "encoding": "latin-1"}))
        spec = umf.effective_source()
        assert isinstance(spec, DelimitedSource)
        assert spec.delimiter == ","
        assert spec.encoding == "latin-1"
        # The alias is derived, never written back onto the model:
        assert umf.source is None
        assert "source" not in umf.model_dump(exclude_none=True)

    def test_declared_source_wins_over_file_format(self):
        umf = UMF(
            **_base(
                file_format={"delimiter": ","},
                source={"kind": "delimited", "delimiter": "\t"},
            )
        )
        assert umf.effective_source().delimiter == "\t"

    def test_legacy_umf_round_trip_is_byte_identical(self, tmp_path):
        """A UMF declaring only file_format never grows a source: block on save."""
        umf = UMF(**_base(file_format={"delimiter": ",", "header": True}))
        first = tmp_path / "first.yaml"
        second = tmp_path / "second.yaml"
        save_umf_to_yaml(umf, first)
        save_umf_to_yaml(load_umf_from_yaml(first), second)
        assert first.read_bytes() == second.read_bytes()
        assert "source:" not in first.read_text()

    def test_source_round_trips_through_yaml(self, tmp_path):
        umf = UMF(
            **_base(
                source={
                    "kind": "jdbc",
                    "url": "jdbc:sqlserver://host",
                    "dbtable": "dbo.members",
                    "password_secret_ref": "scope/key",
                }
            )
        )
        path = tmp_path / "umf.yaml"
        save_umf_to_yaml(umf, path)
        loaded = load_umf_from_yaml(path)
        assert isinstance(loaded.source, JdbcSource)
        assert loaded.source == umf.source
