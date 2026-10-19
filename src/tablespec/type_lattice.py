# SPDX-License-Identifier: MIT OR Apache-2.0
"""Type widening/narrowing rules for UMF schema evolution.

Defines the lattice of safe (lossless) type promotions so that
``compatibility.check_compatibility`` can distinguish breaking type changes
from safe widenings.
"""

# Lossless type widenings: (old_type, new_type) -> human-readable reason
SAFE_WIDENINGS: dict[tuple[str, str], str] = {
    ("INTEGER", "DECIMAL"): "Integer values are representable as decimals",
    ("INTEGER", "FLOAT"): "Integer values are representable as floats",
    ("CHAR", "VARCHAR"): "Fixed-length is a subset of variable-length",
    ("CHAR", "TEXT"): "Fixed-length is a subset of unbounded text",
    ("VARCHAR", "TEXT"): "Bounded string is a subset of unbounded text",
    ("DATE", "DATETIME"): "Date is representable as datetime",
    ("DATE", "TIMESTAMP"): "Date is representable as timestamp",
    ("DATETIME", "TIMESTAMP"): "Datetime is equivalent to timestamp in UMF",
}


def is_safe_widening(old_type: str, new_type: str) -> tuple[bool, str]:
    """Check if changing from *old_type* to *new_type* is a safe (lossless) widening.

    Returns:
        ``(True, reason)`` when the promotion is safe, ``(False, "")`` otherwise.
    """
    if old_type == new_type:
        return True, "Types are identical"
    key = (old_type.upper(), new_type.upper())
    reason = SAFE_WIDENINGS.get(key, "")
    return (bool(reason), reason)


def is_length_compatible(old_length: int | None, new_length: int | None) -> bool:
    """Check if a VARCHAR length change is compatible (non-breaking).

    ``None`` means unbounded.  Widening (or keeping the same) is compatible;
    narrowing is not.
    """
    # Both unbounded → compatible
    if old_length is None and new_length is None:
        return True
    # Old bounded, new unbounded → widening → compatible
    if old_length is not None and new_length is None:
        return True
    # Old unbounded, new bounded → narrowing → incompatible
    if old_length is None and new_length is not None:
        return False
    # Both bounded
    assert old_length is not None and new_length is not None
    return new_length >= old_length


def is_precision_compatible(
    old_prec: int | None,
    old_scale: int | None,
    new_prec: int | None,
    new_scale: int | None,
) -> bool:
    """Check DECIMAL precision/scale compatibility.

    A widening (equal-or-larger precision *and* equal-or-larger scale) is
    compatible.  Any narrowing is incompatible.  ``None`` is treated as
    "unspecified" and is considered compatible with anything (no constraint).
    """
    # Precision check
    if old_prec is not None and new_prec is not None:
        if new_prec < old_prec:
            return False
    elif old_prec is not None and new_prec is None:
        # Old had precision, new doesn't → unbounded, compatible
        pass
    elif old_prec is None and new_prec is not None:
        # Old was unspecified, new adds constraint → narrowing
        return False

    # Scale check
    if old_scale is not None and new_scale is not None:
        if new_scale < old_scale:
            return False
    elif old_scale is not None and new_scale is None:
        pass
    elif old_scale is None and new_scale is not None:
        return False

    return True
