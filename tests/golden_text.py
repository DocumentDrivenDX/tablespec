# SPDX-License-Identifier: MIT OR Apache-2.0
"""Read golden files the way generators emit them.

Repository fixtures carry an SPDX license header (dual-licensing, 6eb4572);
generators do not emit one. Exact golden comparisons read through
:func:`read_golden` so the fixture's license metadata is not part of the
expected output.
"""

from __future__ import annotations

from pathlib import Path

LICENSE_HEADER = "SPDX-License-Identifier: MIT OR Apache-2.0\n"


def read_golden(path: Path) -> str:
    """Return *path*'s text without a leading SQL/shell-comment license header."""
    text = path.read_text()
    for prefix in ("-- ", "# "):
        text = text.removeprefix(prefix + LICENSE_HEADER)
    return text
