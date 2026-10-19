# SPDX-License-Identifier: MIT OR Apache-2.0
"""Composable Hypothesis strategies for generating valid UMF data.

Provides strategies for property-based testing of UMF models,
schema generators, and any code that consumes UMF structures.
"""

from hypothesis import strategies as st
from hypothesis.strategies import composite


# Valid UMF data types (from UMFColumn.data_type pattern)
UMF_DATA_TYPES = [
    "VARCHAR",
    "CHAR",
    "TEXT",
    "INTEGER",
    "DECIMAL",
    "FLOAT",
    "DATE",
    "DATETIME",
    "TIMESTAMP",
    "BOOLEAN",
]

# Types that take a length parameter
_LENGTH_TYPES = {"VARCHAR", "CHAR"}

# Types that take precision/scale parameters
_PRECISION_TYPES = {"DECIMAL"}


@composite
def column_name(draw) -> str:
    """Generate valid column names: lowercase letters and underscores, 1-30 chars.

    Must match pattern ^[A-Za-z][A-Za-z0-9_]*$ and be at most 128 chars.
    We keep them short (1-30) for readability and uniqueness.
    """
    first = draw(st.sampled_from("abcdefghijklmnopqrstuvwxyz"))
    rest = draw(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789_",
            min_size=0,
            max_size=29,
        )
    )
    return first + rest


@composite
def table_name(draw) -> str:
    """Generate valid table names.

    Must match pattern ^[A-Za-z][A-Za-z0-9_]*$ and be at most 128 chars.
    """
    first = draw(st.sampled_from("abcdefghijklmnopqrstuvwxyz"))
    rest = draw(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789_",
            min_size=0,
            max_size=29,
        )
    )
    return first + rest


@composite
def nullable_value(draw):
    """Generate valid nullable values: None or dict with context keys.

    Returns None (no nullable config) or a dict of context keys mapped to bools,
    which Pydantic will parse as a Nullable model with extra fields.
    """
    kind = draw(st.sampled_from(["none", "empty_dict", "context_dict"]))

    if kind == "none":
        return None

    if kind == "empty_dict":
        return {}

    # Dict with 1-4 arbitrary context keys
    keys = draw(
        st.lists(
            st.sampled_from(["MD", "MP", "ME", "US", "EU", "production", "staging"]),
            min_size=1,
            max_size=4,
            unique=True,
        )
    )
    return {k: draw(st.booleans()) for k in keys}


@composite
def umf_column(draw) -> dict:
    """Generate a valid UMF column dict.

    VARCHAR/CHAR gets length (1-4000). DECIMAL gets precision (1-38) and
    scale (0-precision). Other types get no size params.
    """
    name = draw(column_name())
    data_type = draw(st.sampled_from(UMF_DATA_TYPES))

    col: dict = {
        "name": name,
        "data_type": data_type,
    }

    # Add length for string types
    if data_type in _LENGTH_TYPES:
        col["length"] = draw(st.integers(min_value=1, max_value=4000))

    # Add precision and scale for decimal
    if data_type in _PRECISION_TYPES:
        precision = draw(st.integers(min_value=1, max_value=38))
        scale = draw(st.integers(min_value=0, max_value=precision))
        col["precision"] = precision
        col["scale"] = scale

    # Optionally add nullable
    if draw(st.booleans()):
        col["nullable"] = draw(nullable_value())

    # Optionally add description
    if draw(st.booleans()):
        col["description"] = draw(
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("L", "N", "Z"),
                ),
                min_size=1,
                max_size=100,
            )
        )

    return col


@composite
def umf_dict(draw) -> dict:
    """Generate a valid UMF dict (for schema generators).

    1-10 columns with unique names, version, and table_name.
    """
    num_columns = draw(st.integers(min_value=1, max_value=10))

    # Generate unique column names first, then build columns
    names = draw(
        st.lists(
            column_name(),
            min_size=num_columns,
            max_size=num_columns,
            unique=True,
        )
    )

    columns = []
    for name in names:
        col = draw(umf_column())
        col["name"] = name  # Override with guaranteed-unique name
        columns.append(col)

    major = draw(st.integers(min_value=1, max_value=9))
    minor = draw(st.integers(min_value=0, max_value=9))

    return {
        "version": f"{major}.{minor}",
        "table_name": draw(table_name()),
        "columns": columns,
    }


@composite
def umf_object(draw):
    """Generate a valid UMF Pydantic object.

    Uses umf_dict() and constructs via UMF(**d).
    """
    from tablespec.models.umf import UMF

    d = draw(umf_dict())
    return UMF(**d)
