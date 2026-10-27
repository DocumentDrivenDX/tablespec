#!/usr/bin/env python3
"""Verify public PyPI files match the release's hash-bound manifest."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def fetch_public_release(package: str, version: str, attempts: int) -> dict[str, str]:
    url = f"https://pypi.org/pypi/{package}/{version}/json"
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = Request(
                url, headers={"User-Agent": "umf-tablespec-release-check"}
            )
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
            releases = payload.get("urls")
            if not isinstance(releases, list):
                raise ValueError("PyPI response has no release file list")
            return {
                item["filename"]: item["digests"]["sha256"]
                for item in releases
                if isinstance(item, dict)
                and isinstance(item.get("filename"), str)
                and isinstance(item.get("digests"), dict)
                and isinstance(item["digests"].get("sha256"), str)
            }
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(10)
    raise RuntimeError(f"PyPI release did not become verifiable: {last_error}")


def verify(manifest_path: Path, attempts: int = 12) -> dict[str, str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    package = manifest.get("package")
    version = manifest.get("version")
    artifacts = manifest.get("artifacts")
    if (
        not isinstance(package, str)
        or not isinstance(version, str)
        or not isinstance(artifacts, list)
    ):
        raise ValueError("release manifest has incomplete package identity")
    expected = {
        item["name"]: item["sha256"]
        for item in artifacts
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and isinstance(item.get("sha256"), str)
    }
    if len(expected) != len(artifacts) or len(expected) != 2:
        raise ValueError("manifest must identify exactly the wheel and sdist")
    actual = fetch_public_release(package, version, attempts)
    if actual != expected:
        raise ValueError(
            f"public PyPI files differ from the release manifest: "
            f"expected={sorted(expected)}, actual={sorted(actual)}"
        )
    return actual


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--attempts", type=int, default=12)
    args = parser.parse_args()
    print(json.dumps(verify(args.manifest, args.attempts), sort_keys=True))


if __name__ == "__main__":
    main()
