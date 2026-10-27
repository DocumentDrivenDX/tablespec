# SPDX-License-Identifier: MIT OR Apache-2.0
# @covers US-038-AC2
# @covers US-038-AC4
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_pages_artifact.py"


def test_pages_artifact_combines_hugo_site_and_package_index(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    dist_dir = tmp_path / "dist"
    out_dir = tmp_path / "pages"
    releases_json = tmp_path / "releases.json"

    site_dir.mkdir()
    (site_dir / "index.html").write_text("<h1>tablespec</h1>", encoding="utf-8")
    (site_dir / "docs").mkdir()
    (site_dir / "docs" / "index.html").write_text("docs", encoding="utf-8")

    dist_dir.mkdir()
    wheel = dist_dir / "tablespec-1.2.3-py3-none-any.whl"
    sdist = dist_dir / "tablespec-1.2.3.tar.gz"
    wheel.write_bytes(b"wheel-content")
    sdist.write_bytes(b"sdist-content")

    releases_json.write_text(
        json.dumps(
            [
                {
                    "tag_name": "v1.1.0",
                    "assets": [
                        {
                            "name": "tablespec-1.1.0-py3-none-any.whl",
                            "browser_download_url": (
                                "https://github.com/easel/tablespec/releases/"
                                "download/v1.1.0/tablespec-1.1.0-py3-none-any.whl"
                            ),
                        },
                        {
                            "name": "notes.txt",
                            "browser_download_url": "https://example.invalid/notes.txt",
                        },
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--site-dir",
            str(site_dir),
            "--dist-dir",
            str(dist_dir),
            "--out-dir",
            str(out_dir),
            "--repo",
            "DocumentDrivenDX/tablespec",
            "--tag",
            "v1.2.3",
            "--package",
            "umf-tablespec",
            "--releases-json",
            str(releases_json),
        ],
        check=True,
        cwd=ROOT,
    )

    assert (out_dir / "index.html").is_file()
    assert (out_dir / ".nojekyll").is_file()
    assert (out_dir / "simple" / "index.html").is_file()

    package_index = out_dir / "simple" / "tablespec" / "index.html"
    current_package_index = out_dir / "simple" / "umf-tablespec" / "index.html"
    assert package_index.is_file()
    assert current_package_index.is_file()
    html = package_index.read_text(encoding="utf-8")
    current_html = current_package_index.read_text(encoding="utf-8")

    assert "tablespec-1.2.3-py3-none-any.whl" in html
    assert "tablespec-1.2.3-py3-none-any.whl" in current_html
    assert "tablespec-1.2.3.tar.gz" in html
    assert (
        "https://github.com/DocumentDrivenDX/tablespec/releases/download/v1.2.3/"
        in html
    )
    assert "../../../releases/" not in html
    assert "#sha256=" in html
    assert "tablespec-1.1.0-py3-none-any.whl" in html
    assert "notes.txt" not in html


def test_release_workflow_builds_combined_pages_artifact() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    assert "fetch-depth: 0" in workflow
    assert "hugo-version: '0.160.0'" in workflow
    assert "hugo --gc --minify" in workflow
    assert "python scripts/build_pages_artifact.py" in workflow
    assert "--package umf-tablespec" in workflow
    assert "/simple/tablespec/index.html" in workflow
    assert "/simple/umf-tablespec/index.html" in workflow
    install_commands = [
        line.strip()
        for line in workflow.splitlines()
        if "pip install " in line and "--extra-index-url" in line
    ]
    assert len(install_commands) == 2
    assert all(
        "--extra-index-url https://pypi.org/simple" in line for line in install_commands
    )


def test_microsite_workflow_rebuilds_pages_without_dist_artifacts() -> None:
    workflow = (ROOT / ".github" / "workflows" / "publish-microsite.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch:" in workflow
    assert "website/**" in workflow
    assert "hugo --gc --minify" in workflow
    assert "python scripts/build_pages_artifact.py" in workflow
    assert "--package umf-tablespec" in workflow
    assert "--include-github-releases" in workflow
    assert "/simple/umf-tablespec/index.html" in workflow
    assert "--dist-dir" not in workflow


def test_publication_workflow_verifies_local_build_then_public_pypi() -> None:
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    publish = (ROOT / ".github" / "workflows" / "publish-pypi.yml").read_text(
        encoding="utf-8"
    )

    assert "Verify GitHub Pages index and install built wheel" in release
    assert 'python -m pip install "$WHEEL"' in release
    assert '"umf-tablespec==$VERSION"' not in release
    assert "Verify public PyPI artifact hashes" in publish
    assert "verify_pypi_release.py --manifest dist/release-manifest.json" in publish
    assert (
        "python -m pip install --no-cache-dir --index-url https://pypi.org/simple"
        in publish
    )
