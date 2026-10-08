---
ddx:
  id: CONTRACT-001
  authoring:
    home: repo
  links:
    - id: FEAT-001
      kind: informed_by
    - id: architecture
      kind: informed_by
---

# CONTRACT-001: Shared UMF Python binding

**Type:** library/extension. **Version:** 0.1.0. **Status:** draft.

## Purpose

Consume official UMF Python support while keeping TableSpec's native extension
and compiler semantics owned by this repository.

## Scope and Boundaries

Core 0.8.0 documents use `tablespec.pipeline` 0.1.0 at module and element scopes.
Shared field name, description, title, aliases and scalar family reside in core.
Native type refinement and all remaining pipeline metadata reside in `metadata`
objects governed by `src/tablespec/extensions/pipeline.schema.json`. Shared core
schemas and Python machinery MUST NOT be copied into TableSpec.
The legacy model schema remains a native compatibility contract, not UMF core.

## Normative Surface

| Surface | Rules |
| --- | --- |
| `from_legacy(mapping,document_id=None)` | Migrate one table into one table module, ordered column:index Field IDs. Preserve native metadata without adding Pydantic defaults; inconsistent/unsafe portable values refuse. Native null or invalid shared aliases remain native metadata. |
| `to_legacy(document)` | Derive a mapping from core and pipeline metadata. Require core 0.8.0, one module, scalar Fields and explicit native data_type refinements. Family alone MUST NOT infer native storage/coercion. |
| `compiler_view` / `UMF.from_document` | Apply native validation; reject unsupported core properties, unknown native model fields and inconsistent scalar/refinement declarations. Retain an isolated authoritative document. |
| `UMF.to_document()` | Return retained source for shared-loaded views. Unsynchronized compiler-view edits refuse. Legacy views migrate using their current native model data. |
| `UMFLoader.load_document` / `save_document` | Canonical JSON/YAML reading and JSON persistence through official serialization. Legacy JSON, inline YAML and split input migrate with retained exact UTF-8 files. Split merge/migration rules remain TableSpec-owned. |
| Existing `load` / `save_json` | Shared JSON input derives a view; saving that view writes the retained canonical document. Legacy inputs keep existing compatibility behavior. YAML model helpers and compile snapshots preserve canonical shared documents. Shared-to-split export refuses. |
| `pipeline_registry()` | Register only consumer-owned schemas. Document validation does not execute native pipeline rules and MUST report incomplete native semantics. |
| `retain_sources` / `recover_sources` | Document-scoped `tablespec.source-archive` 0.1.0 carries files, snapshot and filesSha256. Recover unchanged original file strings only; changed meaning or changed archived files refuse. |

## Precedence and Compatibility

Core names and scalar families govern the derived view. Metadata MUST NOT repeat
shared declarations when a core counterpart exists. Native contextual nullability,
keys, lengths, precision, source shape and derivations retain their qualified
TableSpec meanings; they are not automatically promoted into ideal core assertions.
The initial binding refuses core nullability, cardinality, facets, keys,
relationships, examples, defaults and allowedValues until explicit execution
mappings are qualified. Unknown unrelated vocabularies remain retained and gain
no execution claim. Column-index identity is migration-local, not durable across
reordering; authors MAY use stable IDs in newly authored documents.

## Error Semantics

ValueError or native Pydantic validation errors refuse execution or export;
original input is unchanged. No fallback deletes unknown metadata. Structural
UMF validity and native compiler/pipeline execution remain separate claims.
The archive supports explicit unchanged-file rollback, not automatic edited
source reconstruction or permission to overwrite a source directory.

## Examples

```python
from tablespec.models import UMF
from tablespec.umf_loader import UMFLoader
loader = UMFLoader()
document = loader.load_document("tables/orders")
loader.save_document(document, "orders.umf.json")
view = UMF.from_document(document)
```
