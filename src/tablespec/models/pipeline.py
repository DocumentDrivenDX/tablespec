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


__all__ = ["PipelineDependency", "PipelineMetadata"]
