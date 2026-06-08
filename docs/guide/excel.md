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
