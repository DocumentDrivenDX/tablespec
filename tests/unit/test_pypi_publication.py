from __future__ import annotations

import json

import pytest

from scripts import verify_pypi_release


def test_pypi_verifier_accepts_exact_public_manifest_hashes(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = {
        "umf_tablespec-0.0.13-py3-none-any.whl": "a" * 64,
        "umf_tablespec-0.0.13.tar.gz": "b" * 64,
    }
    manifest = tmp_path / "release-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "package": "umf-tablespec",
                "version": "0.0.13",
                "artifacts": [
                    {"name": name, "sha256": digest}
                    for name, digest in expected.items()
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        verify_pypi_release,
        "fetch_public_release",
        lambda package, version, attempts: expected,
    )

    assert verify_pypi_release.verify(manifest) == expected


def test_pypi_verifier_rejects_different_public_bytes(tmp_path, monkeypatch) -> None:
    manifest = tmp_path / "release-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "package": "umf-tablespec",
                "version": "0.0.13",
                "artifacts": [
                    {"name": "wheel.whl", "sha256": "a" * 64},
                    {"name": "source.tar.gz", "sha256": "b" * 64},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        verify_pypi_release,
        "fetch_public_release",
        lambda package, version, attempts: {
            "wheel.whl": "c" * 64,
            "source.tar.gz": "b" * 64,
        },
    )

    with pytest.raises(ValueError, match="differ from the release manifest"):
        verify_pypi_release.verify(manifest)
