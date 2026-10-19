# SPDX-License-Identifier: MIT OR Apache-2.0
"""Tests for Hypothesis strategies producing valid UMF data.

Verifies that the composable strategies in tests/strategies.py
always generate data that passes Pydantic validation.
"""

import pytest
from hypothesis import given, settings

from tests.strategies import umf_column, umf_dict, umf_object

pytestmark = pytest.mark.fast


@pytest.mark.no_spark
class TestStrategiesProduceValidUMF:
    @given(umf_object())
    @settings(max_examples=200, deadline=None)
    def test_umf_object_always_valid(self, umf):
        """Every generated UMF passes Pydantic validation."""
        assert umf.model_dump()  # doesn't throw
        assert len(umf.columns) >= 1
        assert umf.table_name

    @given(umf_dict())
    @settings(max_examples=200, deadline=None)
    def test_umf_dict_constructs_valid_model(self, d):
        """Every generated dict constructs a valid UMF."""
        from tablespec.models.umf import UMF

        umf = UMF(**d)
        assert len(umf.columns) >= 1

    @given(umf_column())
    @settings(max_examples=500, deadline=None)
    def test_column_always_valid(self, col):
        """Every generated column passes UMFColumn validation."""
        from tablespec.models.umf import UMFColumn

        UMFColumn(**col)

    def test_unique_column_names(self):
        """umf_dict always produces unique column names."""

        @given(umf_dict())
        @settings(max_examples=200, deadline=None)
        def check(d):
            names = [c["name"] for c in d["columns"]]
            assert len(names) == len(set(names))

        check()
