# Excel Conversion

tablespec provides round-trip conversion between UMF and Excel for non-technical domain experts. Excel workbooks include data validation dropdowns, helper columns, and instructions.

## Export UMF to Excel

```python
from tablespec import UMFToExcelConverter, UMFLoader

loader = UMFLoader()
umf = loader.load("tables/medical_claims/")
converter = UMFToExcelConverter()
workbook = converter.convert(umf)
workbook.save("medical_claims.xlsx")
```

## Import Excel back to UMF

```python
from tablespec import ExcelToUMFConverter

importer = ExcelToUMFConverter()
umf, metadata = importer.convert("medical_claims.xlsx")
```

The importer accepts UMF spellings such as `INTEGER`, `VARCHAR`, and `DECIMAL`,
along with common Excel-friendly aliases like `IntegerType` and `StringType`,
then normalizes the result back to UMF data type names before validation.

## Sheets

A generated workbook contains these sheets:

- **Schema** — table-level fields (`table_name`, `canonical_name`, description, etc.).
- **Columns** — one row per column (name, type, length, nullability, description, …).
- **Relationships** — foreign keys (Source Column / References Table / References Column).
- **Derivations** — machine-readable column derivations (see below).
- **Survivorship** — a human-readable, hierarchical view of derivation logic
  (presentation only; not parsed back on import).
- **Validation Rules**, **File Format**, **Metadata**, and a hidden
  **_Instructions** sheet that backs the dropdowns.

## Derivations round-trip

The **Derivations** sheet captures a column's full derivation so it survives the
UMF → Excel → UMF round-trip exactly — and regenerates byte-identical gold SQL
from `generate_sql_plan`. It has one row per derivation candidate, plus
column-level fields written on the column's first row:

| Column | Meaning |
|--------|---------|
| Column | Target column the derivation belongs to |
| Priority | Candidate priority (1 = highest) |
| Source Table / Source Column | Where the value comes from |
| Expression | SQL expression for computed values |
| Join Filter | WHERE-style scope for the candidate's join |
| Table Instance | Alias when the same table is joined multiple times |
| Row Filter | Pre-aggregation row filter (used with window functions) |
| Order By | Window `ORDER BY` columns — JSON list in one cell |
| Select Columns | Extra columns to carry through aggregation — JSON list |
| Join Via | Multi-hop join through a lookup table — JSON object |
| Reason | Why this source/priority was chosen |
| Derivation Strategy | Top-level strategy: `primary_key`, `base_column`, `max_across_sources` |
| Survivorship Strategy | Survivorship method (e.g. `highest_priority`, `most_recent`) |
| Default Value / Default Condition | Fallback when all candidates are null |
| Survivorship Explanation | Prose explanation of the selection logic |

`Derivation Strategy` (top-level `derivation.strategy`) and `Survivorship
Strategy` (`survivorship.strategy`) are deliberately separate columns because
they drive different SQL paths. List/nested fields (`Order By`, `Select
Columns`, `Join Via`) are JSON-encoded into a single cell; a malformed JSON cell
is reported as a benign note rather than failing the import. Workbooks that
predate the Derivations sheet import unchanged (no derivations attached).

**Excel data-validation limits.** Dropdown option lists longer than 255
characters (e.g. the domain-type list) are stored as ranges on the hidden
`_Instructions` sheet rather than inline in the validation formula. Inline lists
over Excel's 255-character limit cause Excel to report the file as corrupt and
silently drop the validation.
