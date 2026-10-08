"""Main CLI commands for bounded sample-data generation and UC loading."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import typer
import yaml

from .config import GenerationConfig
from .engine import SampleDataGenerator
from .sink import (
    SQLSink,
    SparkSQLSink,
    WarehouseSQLSink,
    load_dataset,
    target_namespace,
)
from .streaming import GeneratedDataset, plan_counts

app = typer.Typer(help="Generate fabricated domain sample data and load Unity Catalog")


@app.command("load")
def load(
    umf: Path = typer.Option(..., "--umf", exists=True, file_okay=False),
    target: str = typer.Option(..., "--target", help="Unity Catalog catalog.schema"),
    scale: str = typer.Option("small", "--scale"),
    domain: str = typer.Option("healthcare", "--domain"),
    scale_config: Path | None = typer.Option(
        None,
        "--scale-config",
        exists=True,
        dir_okay=False,
        help="YAML presets with roots and children",
    ),
    hot_key_ratio: float = typer.Option(0.8, "--hot-key-ratio", min=0, max=1),
    seed: int = typer.Option(42, "--seed"),
    root_entity_count: int = typer.Option(
        100, "--root-entity-count", "--num-members", min=0
    ),
    table_count: list[str] | None = typer.Option(
        None, "--table-count", help="Repeat TABLE=ROWS"
    ),
    backend: str = typer.Option("warehouse", "--backend", help="warehouse or spark"),
    warehouse_id: str | None = typer.Option(None, "--warehouse-id"),
    profile: str | None = typer.Option(None, "--profile"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    drop_existing: bool = typer.Option(False, "--drop-existing"),
    batch_size: int = typer.Option(500, "--batch-size", min=1),
) -> None:
    """Verify fabricated data locally, then stage and replace UC table data."""
    try:
        target_namespace(target)
        if backend not in ("warehouse", "spark"):
            raise ValueError("Backend must be warehouse or spark")
        if not dry_run and backend == "warehouse" and (not warehouse_id or not profile):
            raise ValueError("Loading requires --warehouse-id and --profile")
        overrides = {}
        for item in table_count or []:
            name, value = item.split("=", 1)
            overrides[name] = int(value)
        distributions = {}
        if scale_config:
            presets = yaml.safe_load(scale_config.read_text())
            distributions = {
                name: edge.get("distribution", "skewed")
                for name, edge in presets[scale]["children"].items()
            }
        config = GenerationConfig(
            relationship_distributions=distributions,
            high_frequency_key_ratio=hot_key_ratio,
            root_entity_count=root_entity_count,
            domain=domain,
            random_seed=seed,
        )
        with TemporaryDirectory(prefix="tablespec-sample-") as temp:
            engine = SampleDataGenerator(umf, Path(temp), config)
            specs = engine.load_umf_files(strict=True)
            if not specs:
                raise ValueError("No UMF tables found")
            counts = plan_counts(
                specs, scale, overrides, root_entity_count, preset_path=scale_config
            )
            dataset = GeneratedDataset(
                Path(temp) / "rows.sqlite", specs, counts, config
            )
            try:
                typer.echo(json.dumps(dataset.generate(), sort_keys=True, indent=2))
                sink: SQLSink | None = None
                if not dry_run:
                    if backend == "spark":
                        from tablespec.spark_factory import create_delta_spark_session

                        sink = SparkSQLSink(
                            create_delta_spark_session("tablespec-sample-data")
                        )
                    else:
                        sink = WarehouseSQLSink(warehouse_id or "", profile or "")
                statements = load_dataset(
                    dataset,
                    target,
                    sink,
                    dry_run=dry_run,
                    drop_existing=drop_existing,
                    batch_size=batch_size,
                )
                if dry_run:
                    for statement in statements:
                        typer.echo(statement)
            finally:
                dataset.close()
    except (ValueError, ImportError, RuntimeError, TimeoutError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
