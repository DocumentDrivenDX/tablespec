#!/usr/bin/env python3
"""Build the combined GitHub Pages artifact.

The Pages site serves two contracts:

- `/` is the Hugo product microsite.
- `/simple/` is the PEP 503 package index used by pip/uv installs.

Release jobs pass the current `dist/` directory and may also ask this script to
read historical GitHub Release assets so docs deployment never truncates older
package links.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class PackageLink:
    name: str
    href: str
    tag: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_site(site_dir: Path, out_dir: Path) -> None:
    if not site_dir.is_dir():
        raise SystemExit(f"site directory does not exist: {site_dir}")

    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(site_dir, out_dir)
    (out_dir / ".nojekyll").touch()


def _current_dist_links(dist_dir: Path, tag: str) -> list[PackageLink]:
    if not tag:
        raise SystemExit("--tag is required when --dist-dir is provided")
    if not dist_dir.is_dir():
        raise SystemExit(f"dist directory does not exist: {dist_dir}")

    links: list[PackageLink] = []
    for artifact in sorted(path for path in dist_dir.iterdir() if path.is_file()):
        digest = _sha256(artifact)
        name = artifact.name
        href = f"../../../releases/download/{tag}/{name}#sha256={digest}"
        links.append(PackageLink(name=name, href=href, tag=tag))
    return links


def _links_from_release_payload(payload: object) -> list[PackageLink]:
    if not isinstance(payload, list):
        raise SystemExit("release payload must be a JSON list")

    links: list[PackageLink] = []
    for release in payload:
        if not isinstance(release, dict):
            continue
        tag = str(release.get("tag_name") or "")
        assets = release.get("assets") or []
        if not tag or not isinstance(assets, list):
            continue
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name") or "")
            url = str(asset.get("browser_download_url") or "")
            if not name or not url:
                continue
            if not (name.endswith(".whl") or name.endswith(".tar.gz")):
                continue
            links.append(PackageLink(name=name, href=url, tag=tag))
    return links


def _fetch_github_releases(repo: str, token: str | None) -> list[PackageLink]:
    links: list[PackageLink] = []
    page = 1
    while True:
        url = f"https://api.github.com/repos/{repo}/releases?per_page=100&page={page}"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "tablespec-pages-builder",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as exc:
            raise SystemExit(
                f"failed to fetch GitHub releases for {repo}: {exc}"
            ) from exc

        page_links = _links_from_release_payload(payload)
        links.extend(page_links)
        if not isinstance(payload, list) or len(payload) < 100:
            break
        page += 1
    return links


def _dedupe_links(links: list[PackageLink]) -> list[PackageLink]:
    # Current-release local artifacts are passed first and should win over any
    # same file returned by the Releases API while the release job is racing.
    seen: set[tuple[str, str]] = set()
    deduped: list[PackageLink] = []
    for link in links:
        key = (link.tag, link.name)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(link)
    return sorted(deduped, key=lambda item: (item.name, item.href))


def _write_simple_index(out_dir: Path, links: list[PackageLink]) -> None:
    simple_dir = out_dir / "simple"
    package_dir = simple_dir / "tablespec"
    package_dir.mkdir(parents=True, exist_ok=True)

    (simple_dir / "index.html").write_text(
        "\n".join(
            [
                "<!DOCTYPE html>",
                "<html>",
                "<head><title>Simple Index</title></head>",
                "<body>",
                "  <h1>Simple Index</h1>",
                '  <a href="tablespec/">tablespec</a><br/>',
                "</body>",
                "</html>",
                "",
            ]
        ),
        encoding="utf-8",
    )

    rows = [
        "<!DOCTYPE html>",
        "<html>",
        "<head><title>Links for tablespec</title></head>",
        "<body>",
        "  <h1>Links for tablespec</h1>",
    ]
    for link in _dedupe_links(links):
        rows.append(
            f'  <a href="{html.escape(link.href, quote=True)}">'
            f"{html.escape(link.name)}</a><br/>"
        )
    rows.extend(["</body>", "</html>", ""])
    (package_dir / "index.html").write_text("\n".join(rows), encoding="utf-8")


def _check_artifact(out_dir: Path) -> None:
    required = [
        out_dir / "index.html",
        out_dir / "simple" / "index.html",
        out_dir / "simple" / "tablespec" / "index.html",
    ]
    missing = [path for path in required if not path.is_file()]
    if missing:
        formatted = ", ".join(str(path) for path in missing)
        raise SystemExit(f"Pages artifact missing required paths: {formatted}")


def build_pages_artifact(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)
    _copy_site(Path(args.site_dir), out_dir)

    links: list[PackageLink] = []
    if args.dist_dir:
        links.extend(_current_dist_links(Path(args.dist_dir), args.tag))
    if args.releases_json:
        payload = json.loads(Path(args.releases_json).read_text(encoding="utf-8"))
        links.extend(_links_from_release_payload(payload))
    if args.include_github_releases:
        token = args.github_token or os.environ.get("GITHUB_TOKEN")
        links.extend(_fetch_github_releases(args.repo, token))

    _write_simple_index(out_dir, links)
    _check_artifact(out_dir)

    for path in [
        out_dir / "index.html",
        out_dir / "simple" / "index.html",
        out_dir / "simple" / "tablespec" / "index.html",
    ]:
        print(f"ok {path}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--dist-dir")
    parser.add_argument("--repo", default="easel/tablespec")
    parser.add_argument("--tag", default="")
    parser.add_argument("--releases-json")
    parser.add_argument("--include-github-releases", action="store_true")
    parser.add_argument("--github-token")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    build_pages_artifact(parse_args(argv or sys.argv[1:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
