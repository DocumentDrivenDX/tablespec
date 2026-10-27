"""The published distribution name is distinct from the Python import name."""

import tarfile
import tomllib
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from scripts.verify_release_artifacts import distribution_files

ROOT = Path(__file__).resolve().parents[2]


def _write_artifacts(directory: Path, name: str = "umf-tablespec") -> None:
    metadata = f"Metadata-Version: 2.3\nName: {name}\nVersion: 1.2.3\n\n"
    wheel = directory / "umf_tablespec-1.2.3-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("umf_tablespec-1.2.3.dist-info/METADATA", metadata)

    sdist = directory / "umf_tablespec-1.2.3.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        raw = metadata.encode()
        info = tarfile.TarInfo("umf_tablespec-1.2.3/PKG-INFO")
        info.size = len(raw)
        archive.addfile(info, BytesIO(raw))


def test_release_verifier_requires_umf_distribution_name(tmp_path):
    _write_artifacts(tmp_path)
    assert len(distribution_files(tmp_path, "umf-tablespec", "1.2.3")) == 2

    with pytest.raises(ValueError, match="distribution identity mismatch"):
        distribution_files(tmp_path, "tablespec", "1.2.3")


def test_release_verifier_accepts_only_the_generated_uv_gitignore(tmp_path):
    _write_artifacts(tmp_path)
    (tmp_path / ".gitignore").write_text("*")

    assert len(distribution_files(tmp_path, "umf-tablespec", "1.2.3")) == 2


def test_release_verifier_rejects_unexpected_gitignore_contents(tmp_path):
    _write_artifacts(tmp_path)
    (tmp_path / ".gitignore").write_text("**")

    with pytest.raises(ValueError, match=r"unexpected dist/\.gitignore"):
        distribution_files(tmp_path, "umf-tablespec", "1.2.3")


def test_release_verifier_rejects_unexpected_visible_files(tmp_path):
    _write_artifacts(tmp_path)
    (tmp_path / "README.txt").write_text("not a release artifact\n")

    with pytest.raises(ValueError, match="README.txt"):
        distribution_files(tmp_path, "umf-tablespec", "1.2.3")


def test_project_keeps_tablespec_import_and_cli_names():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    project = config["project"]
    assert project["name"] == "umf-tablespec"
    assert project["scripts"]["tablespec"] == "tablespec.cli:app"
    assert config["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "src/tablespec"
    ]
    package_init = (ROOT / "src/tablespec/__init__.py").read_text()
    assert '__version__ = _get_version("umf-tablespec")' in package_init


def test_release_workflows_bind_both_package_identities():
    release = (ROOT / ".github/workflows/release.yml").read_text()
    publish = (ROOT / ".github/workflows/publish-pypi.yml").read_text()
    assert "--package umf-tablespec" in release
    assert "--package umf-tablespec" in publish
    assert "workflow_dispatch:" in release
    assert "ref: ${{ inputs.release_tag || github.ref }}" in release
    assert 'git rev-parse "refs/tags/$RELEASE_TAG^{commit}"' in release
    assert '--source-commit "$(git rev-parse HEAD)"' in release
