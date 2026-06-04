#!/usr/bin/env python3
"""Resolve a PySpark-compatible JAVA_HOME for the test/check environment.

PySpark 4.0 runs on a JVM but does NOT work on every JDK: recent JDKs (e.g.
JDK 24+/26) break Spark's use of ``javax.security.auth.Subject`` and crash with
``getSubject is not supported``. Spark 4.0 is supported on JDK 17 and JDK 21.

This script finds a compatible JDK without requiring any network access when one
is already present on the machine, and only falls back to the Coursier/Zulu path
(``scripts/setup_spark.py``) when nothing suitable is installed.

Resolution order:
  1. ``$TABLESPEC_JAVA_HOME`` if set and compatible (explicit override).
  2. ``$JAVA_HOME`` if already set and compatible.
  3. Common installed JDK locations (Homebrew/Linuxbrew openjdk@21, openjdk@17,
     system locations, ``JAVA_HOME_17/21`` env hints).
  4. A Coursier-provisioned JDK under ``.local/share/java`` (from setup_spark.py),
     checked last so an already-installed openjdk@17/@21 is preferred.
  5. Any ``java`` on ``PATH`` whose major version is compatible.
  6. As a fallback, provision Zulu JDK 21 via Coursier (setup_spark.py), unless
     ``--no-fallback`` is given.

Usage:
    # Print the resolved JAVA_HOME (nothing else on stdout):
    python scripts/setup_test_env.py

    # Print an eval-able export line:
    python scripts/setup_test_env.py --export

    # Print only the major version that was selected (diagnostics):
    python scripts/setup_test_env.py --version

Exit code is non-zero (and a diagnostic is written to stderr) when no compatible
JDK can be found and the Coursier fallback is unavailable.
"""

from __future__ import annotations

import argparse
import contextlib
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

# Spark 4.0 supported JDK major versions. JDK 17 and 21 are the Spark-blessed
# LTS releases; newer JDKs (24/25/26) currently break Spark's security-manager
# usage ("getSubject is not supported").
COMPATIBLE_MAJORS = (17, 21)

_EXE = ".exe" if platform.system().lower() == "windows" else ""


def _java_major(java_home: Path) -> int | None:
    """Return the JDK major version for ``java_home``, or None if unusable."""
    java_bin = java_home / "bin" / f"java{_EXE}"
    if not java_bin.exists():
        return None
    try:
        result = subprocess.run(
            [str(java_bin), "-version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    # ``java -version`` prints to stderr, e.g. ``openjdk version "17.0.19"``.
    text = (result.stderr or "") + (result.stdout or "")
    match = re.search(r'version "(\d+)(?:\.(\d+))?', text)
    if not match:
        return None
    major = int(match.group(1))
    # Legacy ``1.8`` style: the real major is the second component.
    if major == 1 and match.group(2):
        major = int(match.group(2))
    return major


def _is_compatible(java_home: Path | None) -> bool:
    if java_home is None:
        return False
    major = _java_major(java_home)
    return major in COMPATIBLE_MAJORS


def _candidate_dirs() -> list[Path]:
    """Return ordered candidate JAVA_HOME directories that may exist locally."""
    project_root = Path(__file__).resolve().parent.parent
    candidates: list[Path] = []

    # Explicit per-version hints some CI systems export.
    for var in ("JAVA_HOME_21", "JAVA_HOME_17"):
        val = os.environ.get(var)
        if val:
            candidates.append(Path(val))

    # Homebrew / Linuxbrew opt paths (macOS and Linux).
    brew_prefixes = [
        Path("/home/linuxbrew/.linuxbrew/opt"),
        Path("/opt/homebrew/opt"),
        Path("/usr/local/opt"),
    ]
    brew = shutil.which("brew")
    if brew:
        try:
            prefix = subprocess.run(
                [brew, "--prefix"],
                capture_output=True,
                text=True,
                check=True,
                timeout=15,
            ).stdout.strip()
            if prefix:
                brew_prefixes.insert(0, Path(prefix) / "opt")
        except (OSError, subprocess.SubprocessError):
            pass
    for prefix in brew_prefixes:
        # Prefer 21, then 17, to match the documented Spark 4.0 target.
        for name in ("openjdk@21", "openjdk@17"):
            candidates.append(prefix / name)
            # Some brew openjdk formulae nest the home under libexec.
            candidates.append(
                prefix / name / "libexec" / "openjdk.jdk" / "Contents" / "Home"
            )

    # macOS system JVMs.
    if platform.system().lower() == "darwin":
        jvm_root = Path("/Library/Java/JavaVirtualMachines")
        if jvm_root.exists():
            for jdk in sorted(jvm_root.glob("*/Contents/Home")):
                candidates.append(jdk)

    # Linux distro JDK locations.
    for base in (Path("/usr/lib/jvm"), Path("/usr/java")):
        if base.exists():
            for jdk in sorted(base.glob("*")):
                candidates.append(jdk)

    # Coursier-provisioned JDK (scripts/setup_spark.py installs/symlinks here).
    # Checked last so an already-installed openjdk@17/@21 is preferred over the
    # Coursier fallback dir, per the documented resolution policy.
    candidates.append(project_root / ".local" / "share" / "java")

    return candidates


def _from_path() -> Path | None:
    """Resolve JAVA_HOME from a compatible ``java`` on PATH."""
    java = shutil.which("java")
    if not java:
        return None
    # JAVA_HOME is two levels up from .../bin/java (resolve symlinks first).
    java_home = Path(java).resolve().parent.parent
    if _is_compatible(java_home):
        return java_home
    return None


def resolve_java_home() -> Path | None:
    """Find a Spark-compatible JAVA_HOME, or None if none is available."""
    # 1. Explicit override.
    override = os.environ.get("TABLESPEC_JAVA_HOME")
    if override and _is_compatible(Path(override)):
        return Path(override)

    # 2. Already-set, compatible JAVA_HOME.
    current = os.environ.get("JAVA_HOME")
    if current and _is_compatible(Path(current)):
        return Path(current)

    # 3 & 4. Known candidate directories.
    seen: set[Path] = set()
    for cand in _candidate_dirs():
        try:
            resolved = cand.resolve()
        except OSError:
            resolved = cand
        if resolved in seen:
            continue
        seen.add(resolved)
        if _is_compatible(cand):
            return cand

    # 5. Anything compatible on PATH.
    return _from_path()


def _try_coursier_fallback() -> Path | None:
    """Run scripts/setup_spark.py's Coursier path to provision a JDK 21."""
    project_root = Path(__file__).resolve().parent.parent
    java_home = project_root / ".local" / "share" / "java"
    print(
        "No compatible JDK found; attempting Coursier (zulu:21) fallback via "
        "setup_spark.py ...",
        file=sys.stderr,
    )
    try:
        sys.path.insert(0, str(project_root / "scripts"))
        import setup_spark  # type: ignore[import-not-found]

        bin_dir = project_root / ".local" / "bin"
        share_dir = project_root / ".local" / "share"
        bin_dir.mkdir(parents=True, exist_ok=True)
        share_dir.mkdir(parents=True, exist_ok=True)
        # setup_spark prints progress to stdout; redirect to stderr so the only
        # thing on our stdout remains the resolved JAVA_HOME path (the Makefile
        # captures stdout into the JAVA_HOME variable).
        with contextlib.redirect_stdout(sys.stderr):
            setup_spark.setup_coursier(bin_dir)
            setup_spark.setup_jdk(bin_dir, share_dir)
    except SystemExit:
        return None
    except Exception as exc:  # noqa: BLE001 - fallback is best-effort
        print(f"Coursier fallback failed: {exc}", file=sys.stderr)
        return None
    if _is_compatible(java_home):
        return java_home
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--export",
        action="store_true",
        help="Print an eval-able 'export JAVA_HOME=...' line instead of the bare path.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the selected JDK major version (diagnostic) to stderr.",
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="Do not attempt the network Coursier fallback if no JDK is found.",
    )
    args = parser.parse_args(argv)

    java_home = resolve_java_home()
    if java_home is None and not args.no_fallback:
        java_home = _try_coursier_fallback()

    if java_home is None:
        print(
            "ERROR: No Spark-compatible JDK (major in "
            f"{COMPATIBLE_MAJORS}) could be found.\n"
            "Install openjdk@17 or openjdk@21, set TABLESPEC_JAVA_HOME, or run "
            "'uv run python scripts/setup_spark.py' to provision one via Coursier.",
            file=sys.stderr,
        )
        return 1

    if args.version:
        print(f"Selected JDK major: {_java_major(java_home)}", file=sys.stderr)

    if args.export:
        print(f'export JAVA_HOME="{java_home}"')
    else:
        print(str(java_home))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
