"""Native Python document acquisition and offline verified publication."""

from .preservation import fixity_audit, preservation_metadata
from .bagit import export_bag, validate_bag

from .core import LoaderError, load_publication, read_pack, verify_release
from .fetch import fetch_sources
from .publish import (
    DuckDBMetadataSink,
    LocalObjects,
    SparkMetadataSink,
    metadata_schema,
    publish_sources,
    validate_volume,
)

__all__ = [
    "fixity_audit",
    "preservation_metadata",
    "export_bag",
    "validate_bag",
    "DuckDBMetadataSink",
    "LoaderError",
    "LocalObjects",
    "SparkMetadataSink",
    "fetch_sources",
    "load_publication",
    "metadata_schema",
    "publish_sources",
    "read_pack",
    "validate_volume",
    "verify_release",
]
