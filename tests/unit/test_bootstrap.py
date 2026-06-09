"""Tests for the public bootstrap facade."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import sentinel


def test_bootstrap_from_tables_reflects_profiles_and_compiles(monkeypatch, tmp_path):
    from tablespec.bootstrap import bootstrap_from_tables

    seen: dict[str, object] = {}

    def fake_umfs_from_tables(  # noqa: ANN001
        spark,
        table_names,
        *,
        profile,
        infer_key_candidates,
        key_candidates_out,
    ):
        seen["umfs"] = (
            spark,
            table_names,
            profile,
            infer_key_candidates,
            key_candidates_out,
        )
        return ["umf-member"], {"member": [{"type": "profiled"}]}

    def fake_compile_umfs(umfs, out_dir, **kwargs):  # noqa: ANN001
        seen["compile"] = (umfs, Path(out_dir), kwargs)
        return sentinel.compiled

    monkeypatch.setattr("tablespec.bootstrap.umfs_from_tables", fake_umfs_from_tables)
    monkeypatch.setattr("tablespec.bootstrap.compile_umfs", fake_compile_umfs)

    result = bootstrap_from_tables(
        "spark-session",
        "member",
        tmp_path / "out",
        profile=True,
        dialect="spark",
        gold_targets=("claim_enriched",),
    )

    assert result is sentinel.compiled
    spark, tables, profile, infer_keys, key_candidates_out = seen["umfs"]
    assert (spark, tables, profile, infer_keys) == (
        "spark-session",
        ["member"],
        True,
        False,
    )
    assert key_candidates_out == {}

    umfs, out_dir, kwargs = seen["compile"]
    assert umfs == ["umf-member"]
    assert out_dir == tmp_path / "out"
    assert kwargs["source"] == "tables"
    assert kwargs["profile_enriched"] is True
    assert kwargs["dialect"] == "spark"
    assert kwargs["gold_targets"] == ["claim_enriched"]
    assert kwargs["suites"] == {"member": [{"type": "profiled"}]}
    assert kwargs["infer_keys"] == "none"
    assert kwargs["key_candidates"] == {}


def test_bootstrap_from_tables_schema_only_disables_profile_enrichment(
    monkeypatch, tmp_path
):
    from tablespec.bootstrap import bootstrap_from_tables

    def fake_umfs_from_tables(  # noqa: ANN001
        spark,
        table_names,
        *,
        profile,
        infer_key_candidates,
        key_candidates_out,
    ):
        assert spark == "spark-session"
        assert table_names == ["member"]
        assert profile is False
        assert infer_key_candidates is False
        assert key_candidates_out == {}
        return ["umf-member"], {}

    def fake_compile_umfs(umfs, out_dir, **kwargs):  # noqa: ANN001
        assert umfs == ["umf-member"]
        assert Path(out_dir) == tmp_path / "out"
        assert kwargs["profile_enriched"] is False
        assert kwargs["suites"] is None
        return sentinel.compiled

    monkeypatch.setattr("tablespec.bootstrap.umfs_from_tables", fake_umfs_from_tables)
    monkeypatch.setattr("tablespec.bootstrap.compile_umfs", fake_compile_umfs)

    result = bootstrap_from_tables(
        "spark-session",
        ["member"],
        tmp_path / "out",
        profile=False,
    )

    assert result is sentinel.compiled
