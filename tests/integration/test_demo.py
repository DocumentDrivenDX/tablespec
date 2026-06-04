"""Acceptance test: run the full demo script and assert it exits cleanly.

The demo script exercises the entire tablespec public API end-to-end,
including PySpark features when available. A non-zero exit code means
something in the package is broken.

On Databricks serverless, the Spark sections (8-11) are gracefully skipped
by the demo itself because the factory (single entrypoint) detects that the
Spark Connect socket is unreachable from a subprocess. The demo still exits 0
and reports all checks passed for the non-Spark sections.
"""

import subprocess
import sys
from pathlib import Path

DEMO_SCRIPT = Path(__file__).resolve().parents[2] / "examples" / "demo.py"


def test_demo_script_runs_successfully():
    """The demo script must exit 0 with all checks passing."""
    result = subprocess.run(
        [sys.executable, str(DEMO_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=120,
    )

    # Print stdout/stderr for debugging on failure
    if result.returncode != 0:
        print("=== STDOUT ===")
        print(result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout)
        print("=== STDERR ===")
        print(result.stderr[-3000:] if len(result.stderr) > 3000 else result.stderr)

    assert result.returncode == 0, f"Demo script failed with exit code {result.returncode}"
    assert "Demo complete! All checks passed." in result.stdout
