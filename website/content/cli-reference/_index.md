---
title: CLI Reference
weight: 3
next: /api-reference
---

tablespec ships a Typer-based CLI with Rich output for schema management and
compilation.

## Global options

```
tablespec [OPTIONS] COMMAND [ARGS]...
```

| Option | Description |
|--------|-------------|
| `--help` | Show help and exit. |
| `--version` | Show version and exit. |

## Commands

### `compile`

Compile a UMF schema to one or more output formats.

```bash
tablespec compile SCHEMA_PATH [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--format` | `sql` | Output format: `sql`, `pyspark`, `json-schema`, `all` |
| `--output` | stdout | Output file path. Use `-` for stdout. |
| `--lob` | `MD` | Line-of-business for nullability: `MD`, `MP`, `ME` |

**Example:**

```bash
# Generate SQL DDL to stdout
tablespec compile schema.yaml --format sql

# Generate all formats and write to a directory
tablespec compile schema.yaml --format all --output ./artifacts/
```

### `validate`

Validate a UMF schema file for correctness.

```bash
tablespec validate SCHEMA_PATH
```

Checks that the UMF file is valid YAML and that all fields conform to the
UMF Pydantic model. Exits with code 0 on success, 1 on validation failure.

**Example:**

```bash
tablespec validate schema.yaml
```

### `types`

Display the type mappings for all columns in a UMF schema.

```bash
tablespec types SCHEMA_PATH [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--format` | `table` | Output format: `table`, `json` |

Shows UMF type, SQL type, PySpark type, and GX type for each column.

**Example:**

```bash
tablespec types schema.yaml
tablespec types schema.yaml --format json
```

### `diff`

Show the differences between two UMF schemas.

```bash
tablespec diff SCHEMA_A SCHEMA_B [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--format` | `table` | Output format: `table`, `json` |

Reports added, removed, and changed columns with their type and nullability
differences.

**Example:**

```bash
tablespec diff schema_v1.yaml schema_v2.yaml
```

### `gx baseline`

Generate a Great Expectations expectation suite from a UMF schema.

```bash
tablespec gx baseline SCHEMA_PATH [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--output` | stdout | Output path for the GX JSON suite. |
| `--lob` | `MD` | Line-of-business for nullability expectations. |

**Example:**

```bash
tablespec gx baseline schema.yaml --output ./ge_suites/medical_claims.json
```

### `gx extract`

Extract a UMF schema from an existing Great Expectations suite.

```bash
tablespec gx extract GX_SUITE_PATH [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--output` | stdout | Output path for the UMF YAML. |

**Example:**

```bash
tablespec gx extract ./ge_suites/medical_claims.json --output schema.yaml
```

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Validation error or command failure |
| 2 | Usage error (bad arguments or flags) |
