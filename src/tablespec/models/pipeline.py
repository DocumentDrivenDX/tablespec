"""Pipeline metadata models for dependency resolution.

Provides Pydantic models for pipeline.yaml files that declare
pipeline identity, version, and inter-pipeline dependencies.
"""

from pydantic import BaseModel, Field


class PipelineDependency(BaseModel):
    """A dependency on another pipeline with version constraints."""

    version: str = Field(
        description="SemVer version constraint (e.g., '>=1.0.0,<2.0.0')"
    )
    required: bool = Field(
        default=True,
        description="Whether this dependency is required or optional",
    )


class PipelineMetadata(BaseModel):
    """Metadata from a pipeline.yaml file.

    Declares a pipeline's identity, version, and dependencies on other pipelines.
    Used by DependencyResolver for version constraint validation and cycle detection.
    """

    name: str = Field(description="Pipeline name (must match directory name)")
    version: str = Field(
        description="Pipeline version in SemVer format (e.g., '1.0.0')"
    )
    dependencies: dict[str, PipelineDependency] = Field(
        default_factory=dict,
        description="Dependencies on other pipelines, keyed by pipeline name",
    )


class TableReference(BaseModel):
    """Parsed table reference with optional pipeline qualification.

    Supports two formats:
    - Bare: "table_name" (references table in same pipeline)
    - Qualified: "pipeline_name.table_name" (references table in another pipeline)
    """

    pipeline: str | None = Field(
        default=None,
        description="Pipeline name (None = same pipeline as referencing table)",
    )
    table: str = Field(description="Table name within pipeline")

    @classmethod
    def parse(cls, ref: str) -> "TableReference":
        """Parse table reference string.

        Args:
            ref: Table reference string ("table" or "pipeline.table")

        Returns:
            Parsed TableReference

        Examples:
            >>> TableReference.parse("outreach_list")
            TableReference(pipeline=None, table='outreach_list')
            >>> TableReference.parse("reference_data.icd_codes")
            TableReference(pipeline='reference_data', table='icd_codes')
        """
        if "." in ref:
            parts = ref.split(".", 1)
            return cls(pipeline=parts[0], table=parts[1])
        return cls(pipeline=None, table=ref)

    def is_external(self) -> bool:
        """Check if this references an external pipeline."""
        return self.pipeline is not None

    def to_qualified_name(self, current_pipeline: str | None = None) -> str:
        """Convert to qualified name string.

        Args:
            current_pipeline: Optional current pipeline name (for resolving bare refs)

        Returns:
            Qualified name ("pipeline.table") when a pipeline is known, else bare name
        """
        target_pipeline = self.pipeline or current_pipeline
        if target_pipeline:
            return f"{target_pipeline}.{self.table}"
        return self.table

    def __str__(self) -> str:
        """String representation (qualified or bare)."""
        if self.pipeline:
            return f"{self.pipeline}.{self.table}"
        return self.table


__all__ = ["PipelineDependency", "PipelineMetadata", "TableReference"]
