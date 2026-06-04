"""Property-based roundtrip test: any valid UMF survives save then load through split format."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tablespec.models.umf import UMF, UMFColumn
from tablespec.umf_loader import UMFLoader

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]

# -- Hypothesis strategies for minimal UMF objects --

_DATA_TYPES = st.sampled_from(
    ["VARCHAR", "INTEGER", "DECIMAL", "DATE", "DATETIME", "BOOLEAN", "TEXT", "CHAR", "FLOAT"]
)

_IDENTIFIER = st.from_regex(r"[A-Za-z][A-Za-z0-9_]{0,20}", fullmatch=True)

_VERSION = st.from_regex(r"[0-9]{1,3}\.[0-9]{1,3}", fullmatch=True)


@st.composite
def umf_column(draw):
    name = draw(_IDENTIFIER)
    data_type = draw(_DATA_TYPES)
    kwargs = {"name": name, "data_type": data_type}
    if data_type == "VARCHAR":
        kwargs["length"] = draw(st.integers(min_value=1, max_value=9999))
    if data_type == "DECIMAL":
        kwargs["precision"] = draw(st.integers(min_value=1, max_value=38))
        kwargs["scale"] = draw(st.integers(min_value=0, max_value=18))
    return UMFColumn(**kwargs)


@st.composite
def umf_object(draw):
    table_name = draw(_IDENTIFIER)
    version = draw(_VERSION)
    # Generate 1-5 columns with unique names
    columns = draw(
        st.lists(umf_column(), min_size=1, max_size=5, unique_by=lambda c: c.name.lower())
    )
    return UMF(version=version, table_name=table_name, columns=columns)


class TestSplitFormatRoundtrip:
    @given(umf=umf_object())
    @settings(max_examples=50, deadline=None)
    def test_roundtrip_preserves_structure(self, umf, tmp_path_factory):
        """Any valid UMF survives save then load through split format."""
        tmp_path = tmp_path_factory.mktemp("roundtrip")
        loader = UMFLoader()
        loader.save(umf, tmp_path / "test_table")
        loaded = loader.load(tmp_path / "test_table")
        assert loaded.table_name == umf.table_name
        assert loaded.version == umf.version
        assert len(loaded.columns) == len(umf.columns)
        # Column order may change (split format sorts by filename), so compare by name
        orig_by_name = {c.name: c for c in umf.columns}
        loaded_by_name = {c.name: c for c in loaded.columns}
        assert set(orig_by_name.keys()) == set(loaded_by_name.keys())
        for name in orig_by_name:
            assert loaded_by_name[name].data_type == orig_by_name[name].data_type
