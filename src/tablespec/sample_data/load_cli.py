"""Main CLI commands for bounded sample-data generation and UC loading."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import typer
import yaml

from .config import GenerationConfig
from .engine import SampleDataGenerator
from .domains import get_run_domain_pack
from .sink import (
    SDKVolumeFiles,
    SparkSQLSink,
    WarehouseSQLSink,
    load_dataset,
    target_namespace,
    volume_path,
)
from .streaming import GeneratedDataset, plan_counts
from .verification import verify_loaded

app = typer.Typer(help="Generate fabricated domain sample data and load Unity Catalog")


@app.command("export")
def export(
    umf: Path = typer.Option(..., "--umf", exists=True, file_okay=False),
    output: Path = typer.Option(..., "--output", dir_okay=False),
    scale: str = typer.Option("small", "--scale"),
    domain: str = typer.Option("healthcare", "--domain"),
    domain_pack: Path | None = typer.Option(
        None, "--domain-pack", exists=True, dir_okay=False
    ),
    seed: int = typer.Option(42, "--seed"),
    table_count: list[str] | None = typer.Option(None, "--table-count"),
    scale_config: Path | None = typer.Option(
        None, "--scale-config", exists=True, dir_okay=False
    ),
) -> None:
    """Generate and verify a portable ZIP of CSV tables without a workspace."""
    from .archive import export_csv_zip

    try:
        if output.suffix.lower() != ".zip":
            raise ValueError("Output must have a .zip suffix")
        overrides = {}
        for item in table_count or []:
            name, value = item.split("=", 1)
            overrides[name] = int(value)
        config = GenerationConfig(
            domain=domain, domain_pack_path=domain_pack, random_seed=seed
        )
        with TemporaryDirectory(prefix="tablespec-export-") as temp:
            specs = SampleDataGenerator(umf, Path(temp), config).load_umf_files(
                strict=True
            )
            if not specs:
                raise ValueError("No UMF tables found")
            metadata = get_run_domain_pack(config).metadata or {}
            presets = metadata.get("scale_presets")
            if scale_config:
                presets = yaml.safe_load(scale_config.read_text())
            if presets and scale in presets:
                config.relationship_distributions = {
                    name: edge.get("distribution", "skewed")
                    for name, edge in presets[scale]["children"].items()
                }
            counts = plan_counts(
                specs, scale, overrides, preset_path=scale_config, presets=presets
            )
            dataset = GeneratedDataset(
                Path(temp) / "rows.sqlite", specs, counts, config
            )
            try:
                dataset.generate()
                export_csv_zip(dataset, output)
                typer.echo(json.dumps(dataset.report, sort_keys=True, indent=2))
                typer.echo(str(output))
            finally:
                dataset.close()
    except (ValueError, ImportError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command("load")
def load(
    umf: Path = typer.Option(..., "--umf", exists=True, file_okay=False),
    target: str = typer.Option(..., "--target", help="Unity Catalog catalog.schema"),
    scale: str = typer.Option("small", "--scale"),
    domain: str = typer.Option("healthcare", "--domain"),
    domain_pack: Path | None = typer.Option(
        None, "--domain-pack", exists=True, dir_okay=False
    ),
    scale_config: Path | None = typer.Option(
        None,
        "--scale-config",
        exists=True,
        dir_okay=False,
        help="YAML presets with roots and children",
    ),
    hot_key_ratio: float = typer.Option(
        0.8,
        "--hot-key-ratio",
        min=0,
        max=1,
        help="Legacy option; bounded sampling uses --skew-exponent",
    ),
    seed: int = typer.Option(42, "--seed"),
    skew_exponent: float = typer.Option(0.8, "--skew-exponent", min=0, max=0.95),
    matter_duration_min_days: int = typer.Option(
        30, "--matter-duration-min-days", min=1
    ),
    matter_duration_max_days: int = typer.Option(
        1095, "--matter-duration-max-days", min=1
    ),
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
    bulk: bool = typer.Option(False, "--bulk"),
    volume: str | None = typer.Option(None, "--volume"),
    verify_only: bool = typer.Option(False, "--verify-only"),
    batch_size: int = typer.Option(500, "--batch-size", min=1),
) -> None:
    """Verify fabricated data locally, then stage and replace UC table data."""
    try:
        target_namespace(target)
        if bulk and (not volume or backend != "warehouse"):
            raise ValueError("--bulk requires --volume and --backend warehouse")
        if volume:
            volume_path(volume)
            if not bulk:
                raise ValueError("--volume requires --bulk")
        if verify_only and (dry_run or bulk or drop_existing):
            raise ValueError(
                "--verify-only cannot combine with dry-run, bulk or drop-existing"
            )
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
            domain_pack_path=domain_pack,
            random_seed=seed,
            skew_exponent=skew_exponent,
            matter_duration_min_days=matter_duration_min_days,
            matter_duration_max_days=matter_duration_max_days,
        )
        with TemporaryDirectory(prefix="tablespec-sample-") as temp:
            engine = SampleDataGenerator(umf, Path(temp), config)
            specs = engine.load_umf_files(strict=True)
            if not specs:
                raise ValueError("No UMF tables found")
            presets = (get_run_domain_pack(config).metadata or {}).get("scale_presets")
            if presets and scale in presets and not scale_config:
                config.relationship_distributions = {
                    name: edge.get("distribution", "skewed")
                    for name, edge in presets[scale]["children"].items()
                }
            counts = plan_counts(
                specs,
                scale,
                overrides,
                root_entity_count,
                preset_path=scale_config,
                presets=presets,
            )
            dataset = GeneratedDataset(
                Path(temp) / "rows.sqlite", specs, counts, config
            )
            try:
                if not verify_only:
                    typer.echo(json.dumps(dataset.generate(), sort_keys=True, indent=2))
                sink: SparkSQLSink | WarehouseSQLSink | None = None
                if not dry_run:
                    if backend == "spark":
                        from tablespec.spark_factory import create_delta_spark_session

                        sink = SparkSQLSink(
                            create_delta_spark_session("tablespec-sample-data")
                        )
                    else:
                        sink = WarehouseSQLSink(warehouse_id or "", profile or "")
                if verify_only and sink:
                    typer.echo(
                        json.dumps(
                            verify_loaded(
                                specs, counts, target, sink, domain == "legal"
                            ),
                            sort_keys=True,
                            indent=2,
                        )
                    )
                    typer.echo("Load verification PASSED")
                    return
                statements = load_dataset(
                    dataset,
                    target,
                    sink,
                    dry_run=dry_run,
                    drop_existing=drop_existing,
                    batch_size=batch_size,
                    volume=volume if bulk else None,
                    files=SDKVolumeFiles(sink.client)
                    if bulk and isinstance(sink, WarehouseSQLSink)
                    else None,
                )
                if not dry_run and sink:
                    typer.echo(
                        json.dumps(
                            verify_loaded(
                                specs, counts, target, sink, domain == "legal"
                            ),
                            sort_keys=True,
                            indent=2,
                        )
                    )
                    typer.echo("Load verification PASSED")
                if dry_run:
                    for statement in statements:
                        typer.echo(statement)
            finally:
                dataset.close()
    except (ValueError, ImportError, RuntimeError, TimeoutError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command("ingest")
def ingest(
    pack: Path = typer.Option(..., "--pack", exists=True, dir_okay=False),
    output: Path | None = typer.Option(None, "--output", dir_okay=False),
    target: str | None = typer.Option(None, "--target"),
    backend: str = typer.Option("warehouse", "--backend"),
    warehouse_id: str | None = typer.Option(None, "--warehouse-id"),
    profile: str | None = typer.Option(None, "--profile"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    mixed: bool = typer.Option(False, "--mixed"),
    scale: str = typer.Option("small", "--scale"),
    seed: int = typer.Option(42, "--seed"),
    source_policy: str = typer.Option("redistribution", "--source-policy"),
) -> None:
    """Verify pinned local CSV sources, export a ZIP, or use the shared loader."""
    from .archive import export_csv_zip
    from .ingest import ImportedDataset

    try:
        if output is None and target is None:
            raise ValueError("Provide --output or --target")
        if output is not None and output.suffix.lower() != ".zip":
            raise ValueError("Output must have a .zip suffix")
        if backend not in ("warehouse", "spark"):
            raise ValueError("Backend must be warehouse or spark")
        if target is not None:
            target_namespace(target)
            if (
                not dry_run
                and backend == "warehouse"
                and (not warehouse_id or not profile)
            ):
                raise ValueError("Loading requires --warehouse-id and --profile")
        with TemporaryDirectory(prefix="tablespec-ingest-") as temp:
            if mixed:
                from .mixed import MixedDataset

                data = MixedDataset(
                    Path(temp) / "rows.sqlite", pack, scale, seed, source_policy
                )
            else:
                data = ImportedDataset(Path(temp) / "rows.sqlite", pack, source_policy)
            try:
                typer.echo(json.dumps(data.report, sort_keys=True, indent=2))
                if output is not None:
                    export_csv_zip(data, output)
                    typer.echo(str(output))
                if target is not None:
                    sink = None
                    if not dry_run:
                        if backend == "spark":
                            from tablespec.spark_factory import (
                                create_delta_spark_session,
                            )

                            sink = SparkSQLSink(
                                create_delta_spark_session("tablespec-source-ingest")
                            )
                        else:
                            sink = WarehouseSQLSink(warehouse_id or "", profile or "")
                    statements = load_dataset(data, target, sink, dry_run=dry_run)
                    if dry_run:
                        for statement in statements:
                            typer.echo(statement)
                    elif sink is not None:
                        typer.echo(
                            json.dumps(
                                verify_loaded(
                                    data.specs,
                                    data.counts,
                                    target,
                                    sink,
                                    mixed and data.config.domain == "legal",
                                ),
                                sort_keys=True,
                                indent=2,
                            )
                        )
                        typer.echo("Load verification PASSED")
            finally:
                data.close()
    except (ValueError, ImportError, RuntimeError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command("replay")
def replay(
    pack: Path = typer.Option(..., "--domain-pack", exists=True, dir_okay=False),
    output: Path = typer.Option(..., "--output", dir_okay=False),
    scale: str = typer.Option("small", "--scale"),
    seed: int = typer.Option(42, "--seed"),
) -> None:
    """Expand authored fabricated scenario components; no population simulation."""
    from .archive import export_csv_zip
    from .replay import ReplayDataset

    try:
        if output.suffix.lower() != ".zip":
            raise ValueError("Output must have a .zip suffix")
        with TemporaryDirectory(prefix="tablespec-replay-") as temp:
            data = ReplayDataset(Path(temp) / "rows.sqlite", pack, scale, seed)
            try:
                export_csv_zip(data, output)
                typer.echo(json.dumps(data.run_metadata, sort_keys=True))
            finally:
                data.close()
    except (ValueError, ImportError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
