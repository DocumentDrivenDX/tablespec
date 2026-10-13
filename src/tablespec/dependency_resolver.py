"""Pipeline Dependency Resolution

Handles pipeline dependency loading, version constraint validation, and
cycle detection for cross-pipeline table references.
"""

from pathlib import Path
from typing import TypedDict

try:
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version
except ImportError:
    SpecifierSet = None  # type: ignore[assignment,misc]
    Version = None  # type: ignore[assignment,misc]

from pydantic import ValidationError
import yaml

try:
    from tablespec.models.pipeline import PipelineMetadata
except ImportError:
    PipelineMetadata = None  # type: ignore[assignment,misc]


class DependencyGraph(TypedDict, total=False):
    """Type definition for dependency graph structure."""

    name: str
    version: str | None
    dependencies: dict[str, "DependencyGraph"]
    circular: bool
    missing: bool


class DependencyResolutionError(Exception):
    """Raised when pipeline dependencies cannot be resolved."""


class CircularDependencyError(DependencyResolutionError):
    """Raised when circular dependencies are detected."""


class VersionConstraintError(DependencyResolutionError):
    """Raised when version constraints cannot be satisfied."""


class DependencyResolver:
    """Resolves and validates pipeline dependencies with SemVer constraints."""

    def __init__(self, pipelines_root: Path) -> None:
        """Initialize resolver with pipelines directory.

        Args:
            pipelines_root: Path to pipelines directory containing pipeline.yaml files

        """
        if PipelineMetadata is None:
            msg = "PipelineMetadata model is not available. Ensure tablespec.models.pipeline is installed."
            raise ImportError(msg)
        self.pipelines_root = pipelines_root
        self._metadata_cache: dict[str, PipelineMetadata] = {}  # type: ignore[type-arg]

    def load_pipeline_metadata(self, pipeline: str) -> PipelineMetadata:  # type: ignore[return]
        """Load pipeline.yaml metadata file.

        Args:
            pipeline: Pipeline name

        Returns:
            Parsed PipelineMetadata

        Raises:
            FileNotFoundError: If pipeline.yaml not found
            ValidationError: If pipeline.yaml format is invalid

        """
        if pipeline in self._metadata_cache:
            return self._metadata_cache[pipeline]

        pipeline_yaml = self.pipelines_root / pipeline / "pipeline.yaml"
        if not pipeline_yaml.exists():
            msg = (
                f"Pipeline metadata not found: {pipeline_yaml}. "
                f"Create pipeline.yaml to declare dependencies and exports."
            )
            raise FileNotFoundError(msg)

        with open(pipeline_yaml) as f:
            data = yaml.safe_load(f)

        try:
            metadata = PipelineMetadata(**data)
        except ValidationError as e:
            msg = f"Invalid pipeline.yaml format for '{pipeline}': {e}"
            raise ValidationError(msg) from e

        # Validate pipeline name matches directory
        if metadata.name != pipeline:
            msg = f"Pipeline name mismatch: directory is '{pipeline}' but pipeline.yaml declares '{metadata.name}'"
            raise ValueError(msg)

        self._metadata_cache[pipeline] = metadata
        return metadata

    def get_available_pipelines(self) -> dict[str, str]:
        """Get all available pipelines with their versions.

        Returns:
            Dictionary mapping pipeline name to version (e.g., {"testdata": "1.0.0"})

        Note:
            Only returns pipelines that have a pipeline.yaml file.

        """
        available = {}
        for pipeline_dir in self.pipelines_root.iterdir():
            if not pipeline_dir.is_dir():
                continue

            pipeline_yaml = pipeline_dir / "pipeline.yaml"
            if not pipeline_yaml.exists():
                continue

            try:
                metadata = self.load_pipeline_metadata(pipeline_dir.name)
                available[metadata.name] = metadata.version
            except (FileNotFoundError, ValidationError, ValueError):
                # Skip pipelines with invalid metadata
                continue

        return available

    def validate_version_constraint(self, constraint: str, available: str) -> bool:
        """Check if available version satisfies SemVer constraint.

        Args:
            constraint: Version constraint string (e.g., ">=1.2.0,<2.0.0")
            available: Available version string (e.g., "1.5.0")

        Returns:
            True if constraint is satisfied, False otherwise

        Examples:
            >>> resolver = DependencyResolver(pipelines_dir)
            >>> resolver.validate_version_constraint(">=1.0.0,<2.0.0", "1.5.0")
            True
            >>> resolver.validate_version_constraint(">=2.0.0", "1.5.0")
            False

        """
        if SpecifierSet is None or Version is None:
            msg = "packaging library is required for version constraint validation. Install it with: pip install packaging"
            raise ImportError(msg)

        try:
            spec_set = SpecifierSet(constraint)
            version = Version(available)
            return version in spec_set
        except Exception:
            return False

    def resolve_dependencies(
        self, pipeline: str, available_pipelines: dict[str, str] | None = None
    ) -> dict[str, str]:
        """Resolve all dependencies for a pipeline with version constraints.

        Args:
            pipeline: Pipeline name
            available_pipelines: Optional dict of available pipeline versions.
                                If None, will auto-discover from pipelines_root.

        Returns:
            Dictionary mapping dependency name to resolved version

        Raises:
            FileNotFoundError: If pipeline metadata not found
            VersionConstraintError: If dependencies cannot be satisfied

        """
        metadata = self.load_pipeline_metadata(pipeline)

        if available_pipelines is None:
            available_pipelines = self.get_available_pipelines()

        resolved = {}
        errors = []

        for dep_name, dep in metadata.dependencies.items():
            if not dep.required:
                # Optional dependency - skip if not available
                if dep_name not in available_pipelines:
                    continue

            if dep_name not in available_pipelines:
                errors.append(
                    f"Required dependency '{dep_name}' not found. "
                    f"Available pipelines: {list(available_pipelines.keys())}"
                )
                continue

            available_version = available_pipelines[dep_name]
            if not self.validate_version_constraint(dep.version, available_version):
                errors.append(
                    f"Dependency '{dep_name}' version mismatch: "
                    f"requires {dep.version} but found {available_version}"
                )
                continue

            resolved[dep_name] = available_version

        if errors:
            raise VersionConstraintError(
                f"Cannot resolve dependencies for pipeline '{pipeline}':\n"
                + "\n".join(f"  - {err}" for err in errors)
            )

        return resolved

    def detect_cycles(
        self, pipeline: str, visited: set[str] | None = None
    ) -> list[list[str]]:
        """Detect circular dependencies starting from a pipeline.

        Args:
            pipeline: Pipeline name to check
            visited: Set of pipelines already visited (for recursive calls)

        Returns:
            List of dependency cycles, where each cycle is a list of pipeline names

        Examples:
            >>> resolver = DependencyResolver(pipelines_dir)
            >>> cycles = resolver.detect_cycles("pipeline_a")
            >>> if cycles:
            ...     print(f"Circular dependency: {' -> '.join(cycles[0])}")

        """
        if visited is None:
            visited = set()

        # Track path for cycle detection
        path = [pipeline]
        return self._detect_cycles_recursive(pipeline, visited, path)

    def _detect_cycles_recursive(
        self, pipeline: str, visited: set[str], path: list[str]
    ) -> list[list[str]]:
        """Recursive helper for cycle detection."""
        visited.add(pipeline)
        cycles = []

        try:
            metadata = self.load_pipeline_metadata(pipeline)
        except FileNotFoundError:
            # Pipeline not found - can't have cycles
            return cycles

        for dep_name in metadata.dependencies:
            if dep_name in path:
                # Found a cycle
                cycle_start = path.index(dep_name)
                cycle = [*path[cycle_start:], dep_name]
                cycles.append(cycle)
            elif dep_name not in visited:
                # Recursively check dependency
                new_path = [*path, dep_name]
                sub_cycles = self._detect_cycles_recursive(dep_name, visited, new_path)
                cycles.extend(sub_cycles)

        return cycles

    def get_dependency_graph(
        self, pipeline: str, visited: set[str] | None = None
    ) -> DependencyGraph:
        """Build complete transitive dependency graph.

        Args:
            pipeline: Pipeline name
            visited: Set of pipelines already visited (for cycle prevention)

        Returns:
            Nested dictionary representing dependency tree:
            {
                "name": "pipeline_a",
                "version": "1.0.0",
                "dependencies": {
                    "pipeline_b": {
                        "name": "pipeline_b",
                        "version": "2.1.0",
                        "dependencies": {}
                    }
                }
            }

        """
        if visited is None:
            visited = set()

        if pipeline in visited:
            return {
                "name": pipeline,
                "version": None,
                "dependencies": {},
                "circular": True,
            }

        visited = visited | {pipeline}

        try:
            metadata = self.load_pipeline_metadata(pipeline)
        except FileNotFoundError:
            return {
                "name": pipeline,
                "version": None,
                "dependencies": {},
                "missing": True,
            }

        graph: DependencyGraph = {
            "name": metadata.name,
            "version": metadata.version,
            "dependencies": {},
        }

        for dep_name in metadata.dependencies:
            graph["dependencies"][dep_name] = self.get_dependency_graph(
                dep_name, visited
            )

        return graph

    def validate_dependencies(self, pipeline: str) -> list[str]:
        """Validate all dependencies for a pipeline.

        Checks:
        - All required dependencies exist
        - Version constraints are satisfiable
        - No circular dependencies

        Args:
            pipeline: Pipeline name

        Returns:
            List of validation error messages (empty list = valid)

        """
        errors = []

        # Check if pipeline metadata exists
        try:
            self.load_pipeline_metadata(pipeline)
        except FileNotFoundError as e:
            return [str(e)]
        except ValidationError as e:
            return [str(e)]
        except ValueError as e:
            return [str(e)]

        # Check circular dependencies
        cycles = self.detect_cycles(pipeline)
        for cycle in cycles:
            cycle_path = " -> ".join(cycle)
            errors.append(f"Circular dependency detected: {cycle_path}")

        # Check version constraints
        try:
            self.resolve_dependencies(pipeline)
        except VersionConstraintError as e:
            errors.append(str(e))
        except FileNotFoundError as e:
            errors.append(str(e))

        return errors
