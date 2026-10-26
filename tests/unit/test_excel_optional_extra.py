# SPDX-License-Identifier: MIT OR Apache-2.0
"""openpyxl is the opt-in ``tablespec[excel]`` extra: the package, its CLI and
the validator must import without it, and Excel entry points must fail with
the install hint rather than a bare ImportError."""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.fast

# A meta-path finder that makes openpyxl unimportable in a fresh interpreter.
_BLOCK_OPENPYXL = textwrap.dedent(
    """
    import importlib.abc, sys

    class _Block(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name == "openpyxl" or name.startswith("openpyxl."):
                raise ImportError(f"blocked: {name}")
            return None

    sys.meta_path.insert(0, _Block())
    """
)


def _run_without_openpyxl(body: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _BLOCK_OPENPYXL + textwrap.dedent(body)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_package_cli_and_validator_import_without_openpyxl():
    result = _run_without_openpyxl(
        """
        import tablespec, tablespec.cli, tablespec.validator
        assert "UMFToExcelConverter" not in tablespec.__all__
        from tablespec.excel_support import excel_available
        assert not excel_available()
        """
    )
    assert result.returncode == 0, result.stderr


def test_excel_entry_point_names_the_extra():
    result = _run_without_openpyxl(
        """
        from tablespec.excel_support import INSTALL_HINT, excel_converters
        try:
            excel_converters()
        except ImportError as exc:
            assert str(exc) == INSTALL_HINT
        else:
            raise SystemExit("expected ImportError")
        """
    )
    assert result.returncode == 0, result.stderr


def test_converters_exported_when_extra_installed():
    pytest.importorskip("openpyxl")
    import tablespec
    from tablespec.excel_support import excel_available, excel_converters

    assert excel_available()
    assert {"UMFToExcelConverter", "ExcelToUMFConverter"} <= set(tablespec.__all__)
    to_excel, from_excel = excel_converters()
    assert (to_excel.__name__, from_excel.__name__) == (
        "UMFToExcelConverter",
        "ExcelToUMFConverter",
    )
