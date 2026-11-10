# UMF Format

Universal Metadata Format (UMF) is a YAML-based schema format for describing database tables with rich metadata.

## Structure

```yaml
version: "1.0"
table_name: Medical_Claims
source_file: claims_spec.xlsx
sheet_name: Medical Claims
description: Healthcare claims and billing information
table_type: data_table

columns:
  - name: claim_id
    data_type: VARCHAR
    length: 50
    description: Unique claim identifier
    nullable:
      MD: false  # Medicaid
      MP: false  # Medicare Part D
      ME: false  # Medicare
    sample_values:
      - "CLM001"
      - "CLM002"

  - name: claim_amount
    data_type: DECIMAL
    precision: 10
    scale: 2
    description: Claim amount in USD
    nullable:
      MD: true
      MP: true
      ME: true

validation_rules:
  table_level:
    - rule_type: row_count
      description: Table must not be empty
      severity: error
      parameters:
        min_value: 1

  column_level:
    claim_id:
      - rule_type: uniqueness
        description: claim_id must be unique
        severity: error

relationships:
  foreign_keys:
    - column: provider_id
      references_table: Providers
      references_column: provider_id
      confidence: 0.95

  referenced_by:
    - table: Claim_Lines
      column: claim_id
      foreign_key_column: claim_id

metadata:
  updated_at: 2025-01-15T10:30:00Z
  created_by: data-platform-team
  pipeline_phase: 4
```

## Supported Data Types

- `VARCHAR` - Variable-length string (requires `length`)
- `CHAR` - Fixed-length string
- `TEXT` - Unlimited text
- `INTEGER` - 32-bit integer
- `BIGINT` - 64-bit integer (use for keys and counts that can exceed 2,147,483,647)
- `DECIMAL` - Fixed-precision decimal (supports `precision` and `scale`)
- `FLOAT` - Floating-point number
- `DATE` - Date without time
- `DATETIME` - Date with time
- `BOOLEAN` - True/false value

## Optional Columns

`optional: true` marks a column that some source files may not carry (an
older or newer file vintage); ingest lands it as NULL for those files. It
tells validation that the absence is expected: the baseline structural check
requires only the non-optional columns (`expect_table_columns_to_match_set`
with `exact_match: false`) in place of the exact column count and order, so
a file without the column passes while one missing any other column still
fails. It is unrelated to `nullable`, which is about values in a column that
is present.

```yaml
columns:
  - name: legacy_code
    data_type: VARCHAR
    length: 20
    optional: true
```

## Sources: Excel and External Tables

Besides `delimited`, `parquet`, `json`, `jdbc` and `delta`, a `source:` block
can declare:

```yaml
# one worksheet of an .xlsx workbook, landed as all-STRING rows
source:
  kind: excel
  sheet: Sheet1          # name (case-insensitive) or zero-based index; default first sheet
  header_row: auto       # or a zero-based row number (default 0)
  header_candidates: [0, 1]
```

`header_row: auto` picks the candidate row whose cells best match the
columns' names, canonical names and aliases (ties go to the later row, for
workbooks that sometimes add a title row). Reading needs
`umf-tablespec[excel]`.

```yaml
# an existing table described here and read in place, not ingested
source:
  kind: external
  table: ${catalog}.billing.claims
```

## Ingestion Modes

`ingestion.mode` selects how landed rows reach the typed table:

| Mode | Effect |
|------|--------|
| `incremental` (default) | Latest row per primary key, upserted |
| `snapshot` | Latest delivery replaces the table |
| `append` | Every landed row is kept (history and event tables) |
| `change_tracking` | Apply a change feed: latest operation per key wins; delete codes remove the row |

`change_tracking` requires a `primary_key`. Its columns default to SQL Server
Change Tracking's names:

```yaml
ingestion:
  mode: change_tracking
  order_by: [_load_ts]
  change_tracking:
    operation_column: SYS_CHANGE_OPERATION   # default
    delete_values: [D]                       # default
    key_columns: [CT_claim_id]               # optional; aligned with primary_key
```

`key_columns` names raw columns that carry the key on every row, for feeds
whose delete rows leave the data columns NULL; the effective key is
`coalesce(key_column, primary_key_column)`. `generate_ingest_sql` renders all
four modes. The dbt and LDP emitters render `append` as a keyless incremental
append and do not render `change_tracking` yet (they raise).
