"""Great Expectations validation utilities."""

from .gx_processor import GXExpectationProcessor

# Define __all__ at module level for type checkers
__all__ = [
    "VALIDATION_ERROR_SCHEMA",
    "VALIDATION_RESULT_SCHEMA",
    "ExpectColumnValuesToCastToType",
    "ExpectColumnValuesToMatchDomainType",
    "GXExpectationProcessor",
    "GXTableValidator",
    "TableValidator",
    "build_validation_report_from_staged_execution",
    "ValidationBlockingError",
    "ValidationDeltaWriter",
    "ValidationResult",
]

# TableValidator and GXTableValidator require pyspark - only available with tablespec[spark]
try:
    from .table_validator import VALIDATION_ERROR_SCHEMA, TableValidator
except ImportError:
    # pyspark not available - symbols won't be accessible at runtime but type checkers can see __all__
    pass

# Optional modules that may not be ported yet
try:
    from .custom_gx_expectations import ExpectColumnValuesToCastToType
    from .custom_gx_expectations import ExpectColumnValuesToMatchDomainType
except (ImportError, ValueError):
    pass

try:
    from .delta_writer import VALIDATION_RESULT_SCHEMA, ValidationDeltaWriter
except (ImportError, ValueError):
    pass

try:
    from .gx_table_validator import (
        GXTableValidator,
        ValidationBlockingError,
        ValidationResult,
    )
except (ImportError, ValueError):
    pass

try:
    from .staged_report import build_validation_report_from_staged_execution
except (ImportError, ValueError):
    pass
