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
            "--tag",
            "v1.2.3",
            "--releases-json",
            str(releases_json),
        ],
        check=True,
        cwd=ROOT,
    )

    assert (out_dir / "index.html").is_file()
    assert (out_dir / ".nojekyll").is_file()
    assert (out_dir / "simple" / "index.html").is_file()

    package_index = (out_dir / "simple" / "tablespec" / "index.html")
    assert package_index.is_file()
    html = package_index.read_text(encoding="utf-8")

    assert "tablespec-1.2.3-py3-none-any.whl" in html
    assert "tablespec-1.2.3.tar.gz" in html
    assert "../../../releases/download/v1.2.3/" in html
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
    assert "scripts/build_pages_artifact.py" in workflow
    assert "/simple/tablespec/index.html" in workflow
