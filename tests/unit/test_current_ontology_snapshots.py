# SPDX-License-Identifier: MIT OR Apache-2.0
"""Official UMF snapshots in examples stay parseable and current."""

import json
from pathlib import Path

import pytest
from umf import Document, validate_document

ROOT = Path(__file__).parents[2]
ONTOLOGIES = sorted((ROOT / "examples").rglob("ontology.json"))

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


def test_all_example_ontology_snapshots_use_current_official_umf():
    """Every checked-in ontology snapshot preserves its full official document."""
    assert len(ONTOLOGIES) == 18

    for path in ONTOLOGIES:
        original = json.loads(path.read_text(encoding="utf-8"))
        assert original["umf"] == "0.10.0", path.relative_to(ROOT)

        document = Document.model_validate(original)
        assert document.to_dict() == original, path.relative_to(ROOT)

        validation = validate_document(document)
        assert validation.valid, (path.relative_to(ROOT), validation.diagnostics)
        assert validation.complete, (path.relative_to(ROOT), validation.diagnostics)
