.PHONY: help install install-dev install-spark setup-spark spark-env format lint type-check test test-unit test-integration coverage docs docs-serve clean build run

TRACKED_LINT_FILES := $(shell git ls-files -- 'src/**/*.py' 'scripts/**/*.py')
TRACKED_TEST_FILES := $(shell git ls-files -- 'tests/**/*.py' ':(exclude)tests/golden/**/*.expected.py')

# Shell snippet that resolves a PySpark-compatible JAVA_HOME and exports it, or
# aborts the recipe if none can be found. Spark 4.0 needs JDK 17/21; newer JDKs
# crash with "getSubject is not supported". scripts/setup_test_env.py prefers an
# already-installed openjdk@17/@21, else falls back to the Coursier zulu:21 path.
# Resolving inside the recipe (vs. a $(shell) variable) means a resolver failure
# aborts the target instead of silently running tests on an incompatible JDK.
EXPORT_SPARK_JAVA_HOME = JAVA_HOME="$$(uv run python scripts/setup_test_env.py)" && export JAVA_HOME

# Default target
help: ## Display this help message
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# Setup & Installation
install: ## Install project dependencies
	uv sync

install-dev: ## Install project with dev dependencies
	uv sync --all-extras --group dev

install-spark: ## Install with Spark extras and dev dependencies
	uv sync --extra spark --group dev

setup-spark: install-spark ## Download and configure local Spark 4.0 + JDK 21 into .local/
	uv run python scripts/setup_spark.py

spark-env: ## Print a Spark-compatible JAVA_HOME (resolves/provisions JDK 17 or 21)
	@uv run python scripts/setup_test_env.py --export

pre-commit-install: ## Install pre-commit hooks
	uv run pre-commit install

pre-commit-run: ## Run all pre-commit hooks manually
	uv run pre-commit run --all-files

# Code Quality
format: ## Format code with ruff
	uv run ruff format .

lint: ## Lint code with ruff
	uv run ruff check $(TRACKED_LINT_FILES)

lint-fix: ## Lint and fix code with ruff
	uv run ruff check --fix $(TRACKED_LINT_FILES)

type-check: ## Type check with pyright
	uv run pyright

# Testing
# Test/coverage targets export a Spark-compatible JAVA_HOME (see
# EXPORT_SPARK_JAVA_HOME) so PySpark-backed tests don't crash on an incompatible
# default JDK. The `&&` chain ensures a failed resolve aborts the recipe.
test: ## Run all tests
	$(EXPORT_SPARK_JAVA_HOME) && uv run pytest $(TRACKED_TEST_FILES)

test-unit: ## Run unit tests only
	$(EXPORT_SPARK_JAVA_HOME) && uv run pytest tests/unit/

test-integration: ## Run integration tests only
	$(EXPORT_SPARK_JAVA_HOME) && uv run pytest tests/integration/

test-demo: ## Run demo script as acceptance test
	$(EXPORT_SPARK_JAVA_HOME) && uv run python examples/demo.py

coverage: ## Run tests with coverage report
	$(EXPORT_SPARK_JAVA_HOME) && uv run pytest --cov=src --cov-report=term-missing --cov-report=html

# Documentation
docs: ## Build API documentation
	uv run mkdocs build

docs-serve: ## Serve API documentation locally
	uv run mkdocs serve

# Development
clean: ## Remove build artifacts and cache files
	rm -rf build/ dist/ *.egg-info .pytest_cache/ .coverage htmlcov/ .ruff_cache/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

build: ## Build the package
	uv build

# Databricks targets
test-databricks: ## Run integration tests on Databricks (requires DATABRICKS_RUNTIME_VERSION)
	@if [ -z "$DATABRICKS_RUNTIME_VERSION" ]; then echo "ERROR: Not running on Databricks"; exit 1; fi
	PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/integration/ -v --tb=short -p no:cacheprovider

test-databricks-all: ## Run full test suite on Databricks (skips local-spark-only tests)
	@if [ -z "$DATABRICKS_RUNTIME_VERSION" ]; then echo "ERROR: Not running on Databricks"; exit 1; fi
	PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/ -v --tb=short -p no:cacheprovider \
		--ignore=tests/unit/test_quality_executor_selection.py \
		--ignore=tests/unit/test_baseline_service.py

# Convenience targets
check: lint type-check test ## Run all checks (lint, type-check, test)

all: install-dev format check ## Install, format, and run all checks
