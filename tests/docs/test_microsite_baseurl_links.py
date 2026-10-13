"""Guard: Hextra card links must not drop Hugo baseURL (/tablespec/).

Root-absolute card links like ``link="/demos/"`` render as ``href=/demos`` and
404 on GitHub Pages (site lives at ``/tablespec/``). Markdown ``[](/path/)`` is
rewritten correctly; only the card shortcode was wrong. Use relative links.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WEBSITE = ROOT / "website"

# Root-absolute path that is NOT under /tablespec (the Pages project base).
_BAD_HREF = re.compile(
    r"""href=(?P<q>["']?)(?P<path>/(?!tablespec(?:/|$)|#)[^"'>\s]+)"""
)


@pytest.mark.skipif(shutil.which("hugo") is None, reason="hugo not installed")
def test_built_site_has_no_root_absolute_links_outside_baseurl(tmp_path: Path) -> None:
    out = tmp_path / "site"
    subprocess.run(
        ["hugo", "--gc", "--minify", "-d", str(out)],
        cwd=WEBSITE,
        check=True,
        capture_output=True,
        text=True,
    )

    demos = out / "demos" / "index.html"
    assert demos.is_file(), "demos page must exist in the Hugo output"

    offenders: list[str] = []
    for html in out.rglob("*.html"):
        text = html.read_text(encoding="utf-8", errors="replace")
        for match in _BAD_HREF.finditer(text):
            path = match.group("path")
            # External-ish or protocol-relative are not expected here.
            if path.startswith("//"):
                continue
            offenders.append(f"{html.relative_to(out)}: {path}")

    assert not offenders, (
        "Root-absolute hrefs miss baseURL /tablespec/ and 404 on GitHub Pages:\n"
        + "\n".join(offenders[:20])
    )

    # Spot-check: card on Getting Started must reach demos under baseURL or
    # via a relative path that resolves under the site tree.
    gs = (out / "getting-started" / "index.html").read_text(encoding="utf-8")
    assert "hextra-card" in gs
    assert re.search(r"href=[^>\s]*demos", gs), "Getting Started must link to demos"
    assert not re.search(r'href=(["\']?)/demos/?\1?(?:[\s>]|$)', gs), (
        "Getting Started must not use root-absolute /demos"
    )
