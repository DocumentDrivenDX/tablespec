# CLI

The `tablespec` command provides schema management, conversion, and validation from the terminal. Requires `typer` and `rich` (included in default dependencies).

## Commands

```bash
# Validate a UMF schema (single table or entire pipeline directory)
tablespec validate tables/outreach_list/

# Display schema summary
tablespec info tables/outreach_list/

# Convert between split and JSON formats
tablespec convert outreach_list.json tables/outreach_list/

# Batch convert a directory of UMF files
tablespec batch-convert tables/ output/ --format split

# Export UMF to Excel for domain expert review
tablespec export-excel tables/medical_claims/ claims.xlsx

# Import edited Excel back to UMF (split format)
tablespec import-excel claims.xlsx tables/medical_claims/

# Render a directory of UMFs into a navigable HTML guidebook
tablespec guidebook tables/ --output guidebook/

# List all registered domain types
tablespec domains-list

# Show details of a specific domain type
tablespec domains-show us_state_code

# Infer domain type for a column
tablespec domains-infer --column state --description "State code abbreviation"
```
