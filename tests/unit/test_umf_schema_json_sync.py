"""The checked-in UMF JSON schema must match the Pydantic model.

``src/tablespec/schemas/umf.schema.json`` is a generated artifact that nothing
at runtime reads (``validator.py`` and ``umf_validator.py`` both call
``UMF.model_json_schema()``), so it drifts silently whenever a model field is
added. This test turns that drift into a failing check. Regenerate with::

    uv run python -c "import json,pathlib; from tablespec.models.umf import UMF; \
      pathlib.Path('src/tablespec/schemas/umf.schema.json').write_text(\
      json.dumps(UMF.model_json_schema(), indent=2) + '\\n')"
"""

from __future__ import annotations

import json
from pathlib import Path

from tablespec.models.umf import UMF

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "src/tablespec/schemas/umf.schema.json"
)


def test_checked_in_schema_matches_model() -> None:
    on_disk = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert on_disk == UMF.model_json_schema(), (
        "umf.schema.json is stale; regenerate it (see module docstring)"
    )


def test_checked_in_schema_declares_domain_fields() -> None:
    on_disk = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    fk_props = on_disk["$defs"]["ForeignKey"]["properties"]
    assert "references_domain" in fk_props
    assert "integration" in fk_props
    assert "term" in on_disk["properties"]
    assert "term" in on_disk["$defs"]["UMFColumn"]["properties"]
