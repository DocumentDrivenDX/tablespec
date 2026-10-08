"""Explicit opt-in SQL warehouse qualification; never runs in default CI."""

import os
from uuid import uuid4

import pytest

from tablespec.sample_data.sink import (
    identifier,
    load_dataset,
    target_namespace,
    WarehouseSQLSink,
)
from tablespec.sample_data.verification import verify_loaded
from tests.unit.test_legal_sample_data import dataset

pytestmark = [
    pytest.mark.no_spark,
    pytest.mark.skipif(
        not (
            os.environ.get("TABLESPEC_LIVE_WAREHOUSE_ID")
            and os.environ.get("TABLESPEC_LIVE_PROFILE")
        ),
        reason="Set both TABLESPEC_LIVE_WAREHOUSE_ID and TABLESPEC_LIVE_PROFILE to opt in",
    ),
]


def test_small_legal_warehouse_roundtrip(tmp_path):
    sink = WarehouseSQLSink(
        os.environ["TABLESPEC_LIVE_WAREHOUSE_ID"], os.environ["TABLESPEC_LIVE_PROFILE"]
    )
    catalog = os.environ.get("TABLESPEC_LIVE_CATALOG") or str(
        sink.query("SELECT current_catalog()")[0][0]
    )
    target = catalog + ".tablespec_live_" + uuid4().hex
    namespace = target_namespace(target)
    identifier(catalog)
    data = dataset(tmp_path)
    try:
        load_dataset(data, target, sink)
        verify_loaded(data.specs, data.counts, target, sink, True)
        load_dataset(data, target, sink)
        verify_loaded(data.specs, data.counts, target, sink, True)
    finally:
        try:
            sink.execute(f"DROP SCHEMA IF EXISTS {namespace} CASCADE")
        finally:
            data.close()
