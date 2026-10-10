"""Pure Python CLI for network-open fetch and network-isolated publish jobs."""

from pathlib import Path
import json
import typer

from .bagit import export_bag, validate_bag
from .core import LoaderError, load_publication, read_pack, verify_release
from .fetch import fetch_sources
from .publish import (
    DuckDBMetadataSink,
    LocalObjects,
    SparkMetadataSink,
    publish_sources,
    validate_volume,
)

app = typer.Typer(
    help="Fetch original documents or publish a verified offline corpus; no Bun required"
)


def emit(receipt: dict) -> None:
    typer.echo(json.dumps(receipt))
    if receipt["status"] != "complete":
        raise typer.Exit(1)


def refuse(error: Exception) -> None:
    typer.echo(
        json.dumps(
            {
                "status": "refused",
                "code": str(error)
                if isinstance(error, LoaderError)
                else "CONFIGURATION_OR_SINK_IO",
            }
        ),
        err=True,
    )
    raise typer.Exit(1)


@app.command("fetch")
def fetch(
    pack: Path = typer.Option(..., exists=True, dir_okay=False),
    inventory: Path = typer.Option(..., exists=True, dir_okay=False),
    output: Path = typer.Option(..., "--output", "--state"),
    mode: str = "backfill",
    rights: str = "redistribute",
    release_json: Path | None = typer.Option(None, exists=True, dir_okay=False),
) -> None:
    """Collect selected URLs where public-network access is available."""
    try:
        emit(
            fetch_sources(
                pack,
                inventory,
                output,
                mode=mode,
                rights=rights,
                release_path=release_json,
            )
        )
    except (ValueError, OSError, KeyError, TypeError) as exc:
        refuse(exc)


@app.command("replay")
def replay(
    pack: Path = typer.Option(..., exists=True, dir_okay=False),
    state: Path = typer.Option(..., exists=True, file_okay=False),
    rights: str = "redistribute",
) -> None:
    """Verify and republish the committed inventory without any source requests."""
    try:
        emit(fetch_sources(pack, None, state, mode="replay", rights=rights))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        refuse(exc)


def _publish(
    fetched: Path,
    target: str,
    backend: str,
    mode: str,
    volume: str | None,
    objects: Path | None,
    database: Path | None,
    pack: Path | None,
    release_json: Path | None,
) -> dict:
    if (fetched / "bagit.txt").exists():
        fetched = validate_bag(fetched)
    # Validate the complete handoff and installed release before opening a backend.
    load_publication(fetched)
    read_pack(pack or fetched / "pack/domain-pack.json", release_json)
    if backend == "spark":
        if not volume or objects or database:
            raise LoaderError("SPARK_VOLUME_REQUIRED")
        root = validate_volume(target, volume)
        from tablespec.spark_factory import create_delta_spark_session

        sink = SparkMetadataSink(create_delta_spark_session(), target)
        return publish_sources(
            fetched,
            sink,
            LocalObjects(root),
            mode=mode,
            pack_path=pack,
            release_path=release_json,
        )
    if backend == "duckdb":
        if not objects or not database or volume:
            raise LoaderError("DUCKDB_TARGET_REQUIRED")
        import duckdb

        with duckdb.connect(str(database)) as connection:
            return publish_sources(
                fetched,
                DuckDBMetadataSink(connection, target),
                LocalObjects(objects),
                mode=mode,
                pack_path=pack,
                release_path=release_json,
            )
    raise LoaderError("BACKEND")


@app.command("publish")
def publish(
    fetched: Path = typer.Option(
        ..., "--fetched", "--state", exists=True, file_okay=False
    ),
    target: str = typer.Option(...),
    backend: str = "spark",
    mode: str = "replace",
    volume: str | None = None,
    objects: Path | None = None,
    database: Path | None = None,
    pack: Path | None = typer.Option(None, exists=True, dir_okay=False),
    release_json: Path | None = typer.Option(None, exists=True, dir_okay=False),
) -> None:
    """Publish verified metadata and originals without public-network access."""
    try:
        emit(
            _publish(
                fetched,
                target,
                backend,
                mode,
                volume,
                objects,
                database,
                pack,
                release_json,
            )
        )
    except Exception as exc:
        refuse(exc)


@app.command("run")
def run(
    pack: Path = typer.Option(..., exists=True, dir_okay=False),
    inventory: Path = typer.Option(..., exists=True, dir_okay=False),
    state: Path = typer.Option(...),
    target: str = typer.Option(...),
    backend: str = "spark",
    mode: str = "backfill",
    rights: str = "redistribute",
    publish_mode: str = "merge",
    volume: str | None = None,
    objects: Path | None = None,
    database: Path | None = None,
    release_json: Path | None = typer.Option(None, exists=True, dir_okay=False),
) -> None:
    """Explicit one-shot acquisition followed by verified publication."""
    try:
        receipt = fetch_sources(
            pack, inventory, state, mode=mode, rights=rights, release_path=release_json
        )
        emit(receipt)
        emit(
            _publish(
                state,
                target,
                backend,
                publish_mode,
                volume,
                objects,
                database,
                pack,
                release_json,
            )
        )
    except Exception as exc:
        refuse(exc)


@app.command("verify-release")
def release(
    release_json: Path = typer.Option(..., exists=True, dir_okay=False),
) -> None:
    """Compare a downloaded UMF release index with the installed offline authority."""
    try:
        value = verify_release(release_json)
        emit(
            {
                "status": "complete",
                "loader_id": value["id"],
                "loader_version": value["version"],
            }
        )
    except Exception as exc:
        refuse(exc)


@app.command("handoff")
def handoff(
    state: Path = typer.Option(..., exists=True, file_okay=False),
    output: Path = typer.Option(...),
) -> None:
    """Export the committed corpus as a complete BagIt SHA-256 transfer package."""
    try:
        emit(export_bag(state, output))
    except Exception as exc:
        refuse(exc)


@app.command("verify-handoff")
def verify_handoff(
    fetched: Path = typer.Option(..., exists=True, file_okay=False),
) -> None:
    """Verify payload, tag fixity and source closure without network access."""
    try:
        validate_bag(fetched)
        emit({"status": "complete", "format": "BagIt-1.0"})
    except Exception as exc:
        refuse(exc)


@app.command("audit")
def audit(state: Path = typer.Option(..., exists=True, file_okay=False)) -> None:
    """Verify every retained original revision; suitable for cron or job scheduling."""
    from .preservation import fixity_audit

    try:
        if (state / "bagit.txt").exists():
            state = validate_bag(state)
        emit(fixity_audit(state))
    except Exception as exc:
        refuse(exc)
