"""Tests for pipeline dependency resolution."""

# @covers US-020-AC1
# @covers US-020-AC2
# @covers US-020-AC3
# @covers US-020-AC4

import pytest
import yaml

from tablespec.dependency_resolver import (
    CircularDependencyError,
    DependencyResolutionError,
    DependencyResolver,
    VersionConstraintError,
)

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_pipeline_yaml(pipelines_root, name, *, version="1.0.0", dependencies=None):
    """Create a pipeline.yaml file for a pipeline."""
    pipeline_dir = pipelines_root / name
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "name": name,
        "version": version,
        "dependencies": dependencies or {},
    }
    (pipeline_dir / "pipeline.yaml").write_text(yaml.dump(data))


# ---------------------------------------------------------------------------
# Tests: Error classes
# ---------------------------------------------------------------------------


class TestErrorClasses:
    """Test custom exception hierarchy."""

    def test_hierarchy(self):
        assert issubclass(CircularDependencyError, DependencyResolutionError)
        assert issubclass(VersionConstraintError, DependencyResolutionError)
        assert issubclass(DependencyResolutionError, Exception)

    def test_circular_error_message(self):
        err = CircularDependencyError("A -> B -> A")
        assert "A -> B -> A" in str(err)

    def test_version_constraint_error_message(self):
        err = VersionConstraintError("requires >=2.0.0 but found 1.0.0")
        assert ">=2.0.0" in str(err)


# ---------------------------------------------------------------------------
# Tests: DependencyResolver (requires PipelineMetadata model)
# ---------------------------------------------------------------------------


class TestDependencyResolverInit:
    """Test resolver initialization."""

    def test_init_without_pipeline_model(self, tmp_path):
        """If PipelineMetadata is not importable, constructor raises ImportError."""
        # PipelineMetadata is None in the current environment
        from tablespec.dependency_resolver import PipelineMetadata

        if PipelineMetadata is None:
            with pytest.raises(ImportError, match="PipelineMetadata"):
                DependencyResolver(tmp_path)
        else:
            # If model is available, init should work
            resolver = DependencyResolver(tmp_path)
            assert resolver.pipelines_root == tmp_path


class TestVersionConstraintValidation:
    """Test version constraint checking (does not need PipelineMetadata)."""

    def test_validate_version_satisfied(self, tmp_path):
        """Version within range passes."""
        from tablespec.dependency_resolver import PipelineMetadata

        if PipelineMetadata is None:
            pytest.skip("PipelineMetadata not available")

        resolver = DependencyResolver(tmp_path)
        assert resolver.validate_version_constraint(">=1.0.0,<2.0.0", "1.5.0") is True

    def test_validate_version_not_satisfied(self, tmp_path):
        """Version outside range fails."""
        from tablespec.dependency_resolver import PipelineMetadata

        if PipelineMetadata is None:
            pytest.skip("PipelineMetadata not available")

        resolver = DependencyResolver(tmp_path)
        assert resolver.validate_version_constraint(">=2.0.0", "1.5.0") is False

    def test_validate_exact_version(self, tmp_path):
        """Exact version match."""
        from tablespec.dependency_resolver import PipelineMetadata

        if PipelineMetadata is None:
            pytest.skip("PipelineMetadata not available")

        resolver = DependencyResolver(tmp_path)
        assert resolver.validate_version_constraint("==1.0.0", "1.0.0") is True
        assert resolver.validate_version_constraint("==1.0.0", "1.0.1") is False

    def test_validate_invalid_constraint(self, tmp_path):
        """Invalid constraint string returns False."""
        from tablespec.dependency_resolver import PipelineMetadata

        if PipelineMetadata is None:
            pytest.skip("PipelineMetadata not available")

        resolver = DependencyResolver(tmp_path)
        assert resolver.validate_version_constraint("not_valid!!!", "1.0.0") is False


class TestDependencyResolverWithModel:
    """Tests that need PipelineMetadata available."""

    @pytest.fixture(autouse=True)
    def _skip_if_no_model(self):
        from tablespec.dependency_resolver import PipelineMetadata

        if PipelineMetadata is None:
            pytest.skip("PipelineMetadata not available")

    def test_load_pipeline_metadata(self, tmp_path):
        """Load a valid pipeline.yaml."""
        _write_pipeline_yaml(tmp_path, "test_pipeline")
        resolver = DependencyResolver(tmp_path)
        metadata = resolver.load_pipeline_metadata("test_pipeline")
        assert metadata.name == "test_pipeline"
        assert metadata.version == "1.0.0"

    def test_load_pipeline_not_found(self, tmp_path):
        """Missing pipeline.yaml raises FileNotFoundError."""
        resolver = DependencyResolver(tmp_path)
        with pytest.raises(FileNotFoundError, match="pipeline.yaml"):
            resolver.load_pipeline_metadata("nonexistent")

    def test_load_pipeline_name_mismatch(self, tmp_path):
        """Directory name must match pipeline name in YAML."""
        pipeline_dir = tmp_path / "wrong_name"
        pipeline_dir.mkdir()
        data = {"name": "correct_name", "version": "1.0.0", "dependencies": {}}
        (pipeline_dir / "pipeline.yaml").write_text(yaml.dump(data))

        resolver = DependencyResolver(tmp_path)
        with pytest.raises(ValueError, match="mismatch"):
            resolver.load_pipeline_metadata("wrong_name")

    def test_load_caches_metadata(self, tmp_path):
        """Metadata is cached after first load."""
        _write_pipeline_yaml(tmp_path, "cached")
        resolver = DependencyResolver(tmp_path)
        m1 = resolver.load_pipeline_metadata("cached")
        m2 = resolver.load_pipeline_metadata("cached")
        assert m1 is m2

    def test_get_available_pipelines(self, tmp_path):
        """Discover all valid pipelines."""
        _write_pipeline_yaml(tmp_path, "alpha", version="1.0.0")
        _write_pipeline_yaml(tmp_path, "beta", version="2.0.0")
        # Create invalid pipeline (no pipeline.yaml)
        (tmp_path / "gamma").mkdir()

        resolver = DependencyResolver(tmp_path)
        available = resolver.get_available_pipelines()
        assert available == {"alpha": "1.0.0", "beta": "2.0.0"}

    def test_get_available_skips_files(self, tmp_path):
        """Non-directory entries are skipped."""
        _write_pipeline_yaml(tmp_path, "real")
        (tmp_path / "readme.md").write_text("not a pipeline")

        resolver = DependencyResolver(tmp_path)
        available = resolver.get_available_pipelines()
        assert "readme.md" not in available
        assert "real" in available

    def test_resolve_no_dependencies(self, tmp_path):
        """Pipeline with no dependencies resolves to empty dict."""
        _write_pipeline_yaml(tmp_path, "standalone")
        resolver = DependencyResolver(tmp_path)
        resolved = resolver.resolve_dependencies("standalone")
        assert resolved == {}

    def test_resolve_dependencies_satisfied(self, tmp_path):
        """All dependencies satisfied."""
        _write_pipeline_yaml(tmp_path, "provider", version="1.5.0")
        _write_pipeline_yaml(
            tmp_path,
            "consumer",
            dependencies={
                "provider": {"version": ">=1.0.0,<2.0.0", "required": True},
            },
        )

        resolver = DependencyResolver(tmp_path)
        resolved = resolver.resolve_dependencies("consumer")
        assert resolved == {"provider": "1.5.0"}

    def test_resolve_dependencies_version_mismatch(self, tmp_path):
        """Version constraint not satisfied raises error."""
        _write_pipeline_yaml(tmp_path, "dep", version="1.0.0")
        _write_pipeline_yaml(
            tmp_path,
            "app",
            dependencies={
                "dep": {"version": ">=2.0.0", "required": True},
            },
        )

        resolver = DependencyResolver(tmp_path)
        with pytest.raises(VersionConstraintError, match="version mismatch"):
            resolver.resolve_dependencies("app")

    def test_resolve_missing_required_dependency(self, tmp_path):
        """Missing required dependency raises error."""
        _write_pipeline_yaml(
            tmp_path,
            "app",
            dependencies={
                "nonexistent": {"version": ">=1.0.0", "required": True},
            },
        )

        resolver = DependencyResolver(tmp_path)
        with pytest.raises(VersionConstraintError, match="not found"):
            resolver.resolve_dependencies("app")

    def test_resolve_optional_dependency_missing(self, tmp_path):
        """Missing optional dependency is silently skipped."""
        _write_pipeline_yaml(
            tmp_path,
            "app",
            dependencies={
                "optional_dep": {"version": ">=1.0.0", "required": False},
            },
        )

        resolver = DependencyResolver(tmp_path)
        resolved = resolver.resolve_dependencies("app")
        assert resolved == {}

    def test_detect_no_cycles(self, tmp_path):
        """No cycles detected in linear dependency chain."""
        _write_pipeline_yaml(
            tmp_path, "a", dependencies={"b": {"version": ">=1.0.0", "required": True}}
        )
        _write_pipeline_yaml(tmp_path, "b")

        resolver = DependencyResolver(tmp_path)
        cycles = resolver.detect_cycles("a")
        assert cycles == []

    def test_detect_direct_cycle(self, tmp_path):
        """Detect direct circular dependency A -> B -> A."""
        _write_pipeline_yaml(
            tmp_path,
            "a",
            dependencies={"b": {"version": ">=1.0.0", "required": True}},
        )
        _write_pipeline_yaml(
            tmp_path,
            "b",
            dependencies={"a": {"version": ">=1.0.0", "required": True}},
        )

        resolver = DependencyResolver(tmp_path)
        cycles = resolver.detect_cycles("a")
        assert len(cycles) >= 1
        # The cycle should contain both a and b
        cycle = cycles[0]
        assert "a" in cycle
        assert "b" in cycle

    def test_detect_indirect_cycle(self, tmp_path):
        """Detect indirect cycle A -> B -> C -> A."""
        _write_pipeline_yaml(
            tmp_path, "a", dependencies={"b": {"version": ">=1.0.0", "required": True}}
        )
        _write_pipeline_yaml(
            tmp_path, "b", dependencies={"c": {"version": ">=1.0.0", "required": True}}
        )
        _write_pipeline_yaml(
            tmp_path, "c", dependencies={"a": {"version": ">=1.0.0", "required": True}}
        )

        resolver = DependencyResolver(tmp_path)
        cycles = resolver.detect_cycles("a")
        assert len(cycles) >= 1

    def test_detect_cycles_missing_pipeline(self, tmp_path):
        """Missing dependency in cycle detection is handled gracefully."""
        _write_pipeline_yaml(
            tmp_path,
            "a",
            dependencies={"missing": {"version": ">=1.0.0", "required": True}},
        )

        resolver = DependencyResolver(tmp_path)
        cycles = resolver.detect_cycles("a")
        assert cycles == []

    def test_get_dependency_graph_simple(self, tmp_path):
        """Build a simple dependency graph."""
        _write_pipeline_yaml(
            tmp_path,
            "a",
            version="1.0.0",
            dependencies={"b": {"version": ">=1.0.0", "required": True}},
        )
        _write_pipeline_yaml(tmp_path, "b", version="2.0.0")

        resolver = DependencyResolver(tmp_path)
        graph = resolver.get_dependency_graph("a")
        assert graph["name"] == "a"
        assert graph["version"] == "1.0.0"
        assert "b" in graph["dependencies"]
        assert graph["dependencies"]["b"]["name"] == "b"
        assert graph["dependencies"]["b"]["version"] == "2.0.0"

    def test_get_dependency_graph_circular(self, tmp_path):
        """Circular reference is marked in graph."""
        _write_pipeline_yaml(
            tmp_path, "a", dependencies={"b": {"version": ">=1.0.0", "required": True}}
        )
        _write_pipeline_yaml(
            tmp_path, "b", dependencies={"a": {"version": ">=1.0.0", "required": True}}
        )

        resolver = DependencyResolver(tmp_path)
        graph = resolver.get_dependency_graph("a")
        # The second encounter of "a" should be marked as circular
        b_graph = graph["dependencies"]["b"]
        a_in_b = b_graph["dependencies"].get("a", {})
        assert a_in_b.get("circular") is True

    def test_get_dependency_graph_missing(self, tmp_path):
        """Missing pipeline is marked in graph."""
        _write_pipeline_yaml(
            tmp_path,
            "a",
            dependencies={"missing": {"version": ">=1.0.0", "required": True}},
        )

        resolver = DependencyResolver(tmp_path)
        graph = resolver.get_dependency_graph("a")
        missing = graph["dependencies"]["missing"]
        assert missing.get("missing") is True

    def test_validate_dependencies_all_good(self, tmp_path):
        """Validate returns empty list when all is well."""
        _write_pipeline_yaml(
            tmp_path, "a", dependencies={"b": {"version": ">=1.0.0", "required": True}}
        )
        _write_pipeline_yaml(tmp_path, "b", version="1.5.0")

        resolver = DependencyResolver(tmp_path)
        errors = resolver.validate_dependencies("a")
        assert errors == []

    def test_validate_dependencies_with_cycle(self, tmp_path):
        """Validate reports circular dependencies."""
        _write_pipeline_yaml(
            tmp_path, "a", dependencies={"b": {"version": ">=1.0.0", "required": True}}
        )
        _write_pipeline_yaml(
            tmp_path, "b", dependencies={"a": {"version": ">=1.0.0", "required": True}}
        )

        resolver = DependencyResolver(tmp_path)
        errors = resolver.validate_dependencies("a")
        assert any("Circular" in e for e in errors)

    def test_validate_missing_pipeline(self, tmp_path):
        """Validate reports missing pipeline metadata."""
        resolver = DependencyResolver(tmp_path)
        errors = resolver.validate_dependencies("nonexistent")
        assert len(errors) > 0
        assert any("not found" in e for e in errors)
