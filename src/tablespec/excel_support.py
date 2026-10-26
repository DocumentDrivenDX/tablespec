# SPDX-License-Identifier: MIT OR Apache-2.0
"""Gate for the optional Excel round-trip (``tablespec[excel]``).

The UMF <-> workbook converters need openpyxl, which is not a core
dependency: most consumers never touch spreadsheets. Callers resolve the
converters through :func:`excel_converters` so a missing extra surfaces as
one actionable error instead of an ImportError at ``import tablespec``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tablespec.excel_converter import ExcelToUMFConverter, UMFToExcelConverter

INSTALL_HINT = (
    "Excel import/export needs the optional extra: pip install 'tablespec[excel]'"
)


def excel_available() -> bool:
    """True when openpyxl (the ``excel`` extra) is installed."""
    try:
        import openpyxl  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True


def excel_converters() -> tuple[type[UMFToExcelConverter], type[ExcelToUMFConverter]]:
    """Return ``(UMFToExcelConverter, ExcelToUMFConverter)`` or raise with the install hint."""
    try:
        from tablespec.excel_converter import (  # noqa: PLC0415
            ExcelToUMFConverter,
            UMFToExcelConverter,
        )
    except ImportError as exc:
        raise ImportError(INSTALL_HINT) from exc
    return UMFToExcelConverter, ExcelToUMFConverter
