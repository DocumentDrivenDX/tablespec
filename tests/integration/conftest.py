"""Shared Docker-gated SQL Server 2022 + Northwind fixtures (FEAT-031 / US-039).

US-039's local test scenario: a SQL Server container loaded with a
Northwind-faithful fixture (``tests/fixtures/northwind/northwind.sql``,
executed INSIDE the container via ``docker exec sqlcmd`` -- no Python DB
drivers, per the operator decision on DISC-01). Every fixture SKIPS (never
fails) when Docker is unavailable or the image cannot be pulled.

Shared by ``test_jdbc_discovery.py`` (AC1..AC3 depth) and
``test_northwind_e2e.py`` (the US-039 end-to-end acceptance run) so one
container + one discovery run back both suites.

All connectivity is Spark's JDBC connector: the test session pulls the mssql
driver via ``spark.jars.packages`` (JDBC-02/DISC-01).
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tablespec.models.umf import UMF, JdbcSource

MSSQL_IMAGE = "mcr.microsoft.com/mssql/server:2022-latest"
MSSQL_JDBC_PACKAGE = "com.microsoft.sqlserver:mssql-jdbc:12.8.1.jre11"
MSSQL_DRIVER = "com.microsoft.sqlserver.jdbc.SQLServerDriver"
SQLCMD = "/opt/mssql-tools18/bin/sqlcmd"

#: SA password for the throwaway container (strong-password policy compliant).
#: Overridable via env; the value must never appear in any emitted UMF.
SA_PASSWORD = os.environ.get("TABLESPEC_TEST_MSSQL_SA_PASSWORD", "Nw!Disc0very#2026x")
#: Environment-variable name the discovery spec references (JDBC-01/JDBC-04).
SECRET_ENV_VAR = "TABLESPEC_TEST_MSSQL_PASSWORD"

NORTHWIND_SQL = Path(__file__).parents[1] / "fixtures" / "northwind" / "northwind.sql"

#: The 13 classic Northwind base tables, post-sanitization (JDBC-05).
EXPECTED_TABLES = {
    "categories",
    "customer_customer_demo",
    "customer_demographics",
    "customers",
    "employee_territories",
    "employees",
    "order_details",
    "orders",
    "products",
    "region",
    "shippers",
    "suppliers",
    "territories",
}


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def _sqlcmd(
    container: str, *args: str, timeout: int = 60
) -> subprocess.CompletedProcess[str]:
    """Run sqlcmd INSIDE the container (no Python DB drivers, ever)."""
    return _run(
        [
            "docker",
            "exec",
            container,
            SQLCMD,
            "-C",
            "-S",
            "localhost",
            "-U",
            "sa",
            "-P",
            SA_PASSWORD,
            *args,
        ],
        timeout=timeout,
    )


@pytest.fixture(scope="session")
def northwind_jdbc_url():
    """Start SQL Server 2022 in Docker, load Northwind, yield its JDBC URL.

    Skips (never fails) when Docker is unavailable or the image cannot be
    pulled; a failure to execute the checked-in fixture script is a real
    failure.
    """
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker is not installed; SQL Server JDBC lane unavailable")
    if _run(["docker", "info"], timeout=60).returncode != 0:
        pytest.skip("docker daemon is not running; SQL Server JDBC lane unavailable")

    # The mssql/server image is amd64-only; on arm64 hosts Docker runs it
    # under emulation (e.g. OrbStack/Rosetta). Pull may take minutes.
    pull = _run(
        ["docker", "pull", "--platform", "linux/amd64", MSSQL_IMAGE], timeout=1200
    )
    if pull.returncode != 0:
        pytest.skip(f"cannot pull {MSSQL_IMAGE}: {pull.stderr.strip()[-500:]}")

    run = _run(
        [
            "docker",
            "run",
            "-d",
            "--platform",
            "linux/amd64",
            "-e",
            "ACCEPT_EULA=Y",
            "-e",
            f"MSSQL_SA_PASSWORD={SA_PASSWORD}",
            "-p",
            "127.0.0.1:0:1433",  # random host port
            MSSQL_IMAGE,
        ],
        timeout=120,
    )
    if run.returncode != 0:
        pytest.skip(f"cannot start {MSSQL_IMAGE}: {run.stderr.strip()[-500:]}")
    container = run.stdout.strip()

    try:
        # Readiness: SQL Server under emulation can take a while to accept logins.
        deadline = time.monotonic() + 300
        ready = False
        while time.monotonic() < deadline:
            if _sqlcmd(container, "-Q", "SELECT 1").returncode == 0:
                ready = True
                break
            time.sleep(3)
        if not ready:
            logs = _run(["docker", "logs", "--tail", "30", container], timeout=30)
            pytest.skip(
                "SQL Server container never became ready (environmental); "
                f"last log lines:\n{logs.stdout[-1500:]}{logs.stderr[-500:]}"
            )

        # Load the checked-in Northwind fixture INSIDE the container.
        cp = _run(
            ["docker", "cp", str(NORTHWIND_SQL), f"{container}:/tmp/northwind.sql"],
            timeout=60,
        )
        assert cp.returncode == 0, f"docker cp failed: {cp.stderr}"
        load = _sqlcmd(container, "-b", "-i", "/tmp/northwind.sql", timeout=300)
        assert load.returncode == 0, (
            f"Northwind fixture load failed:\n{load.stdout[-2000:]}\n{load.stderr[-500:]}"
        )

        host, port = _reachable_endpoint(container)
        yield (
            f"jdbc:sqlserver://{host}:{port};databaseName=Northwind;"
            "encrypt=true;trustServerCertificate=true"
        )
    finally:
        _run(["docker", "rm", "-f", container], timeout=60)


def _reachable_endpoint(container: str) -> tuple[str, int]:
    """The (host, port) this process can actually reach the container on.

    Candidates: the published loopback port (the plain Docker case) and the
    container's bridge IP (covers remote/VM docker daemons -- e.g. an OrbStack
    machine whose published ports bind on the host, not here). Skips when
    neither is reachable (environmental).
    """
    candidates: list[tuple[str, int]] = []
    port_proc = _run(["docker", "port", container, "1433/tcp"], timeout=30)
    if port_proc.returncode == 0 and port_proc.stdout.strip():
        first = port_proc.stdout.splitlines()[0]
        candidates.append(("127.0.0.1", int(first.rsplit(":", 1)[1])))
    inspect = _run(
        [
            "docker",
            "inspect",
            "-f",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
            container,
        ],
        timeout=30,
    )
    if inspect.returncode == 0 and inspect.stdout.strip():
        candidates.append((inspect.stdout.strip(), 1433))

    for host, port in candidates:
        try:
            with socket.create_connection((host, port), timeout=5):
                return host, port
        except OSError:
            continue
    pytest.skip(
        f"SQL Server container is up but no candidate endpoint is reachable "
        f"from this process: {candidates}"
    )


@pytest.fixture(scope="session")
def mssql_spark():
    """A Spark session with the mssql JDBC driver on its classpath.

    The driver jar arrives via ``spark.jars.packages`` (test-only -- no
    runtime dependency). ``jars.packages`` only takes effect at JVM start, so
    when an earlier fixture already started a session we verify the driver is
    actually loadable and skip otherwise.
    """
    pyspark = pytest.importorskip("pyspark", reason="PySpark required for JDBC lanes")
    del pyspark
    from pyspark.sql import SparkSession

    existing = SparkSession.getActiveSession()
    created = existing is None
    if existing is not None:
        spark = existing
    else:
        try:
            spark = (
                SparkSession.builder.appName("tablespec-jdbc-discovery")
                .master("local[2]")
                .config("spark.jars.packages", MSSQL_JDBC_PACKAGE)
                .config("spark.ui.enabled", "false")
                .config("spark.sql.shuffle.partitions", "2")
                .getOrCreate()
            )
        except Exception as exc:  # noqa: BLE001 - environmental (e.g. no Ivy/network)
            pytest.skip(f"could not start Spark with the mssql JDBC driver: {exc}")

    try:
        # Spark's classloader (Utils.classForName) sees Ivy-delivered jars;
        # plain java.lang.Class.forName uses the system loader and would not.
        spark._jvm.org.apache.spark.util.Utils.classForName(  # noqa: SLF001
            MSSQL_DRIVER, True, True
        )
    except Exception:
        if created:
            spark.stop()
        pytest.skip(
            "mssql JDBC driver not loadable on the active Spark session "
            "(shared session started without spark.jars.packages?)"
        )

    yield spark
    if created:
        spark.stop()


@pytest.fixture(scope="session")
def discovery_spec(northwind_jdbc_url) -> JdbcSource:
    """The connection spec discovery runs with: secret REFERENCE only."""
    from tablespec.models.umf import JdbcSource

    os.environ[SECRET_ENV_VAR] = SA_PASSWORD
    return JdbcSource(
        kind="jdbc",
        url=northwind_jdbc_url,
        dbtable="INFORMATION_SCHEMA.TABLES",  # connection spec; ignored by discover()
        driver=MSSQL_DRIVER,
        user="sa",
        password_secret_ref=SECRET_ENV_VAR,
    )


@pytest.fixture(scope="session")
def discovered(discovery_spec, mssql_spark) -> dict[str, UMF]:
    """One discovery run shared by every assertion: table_name -> UMF."""
    from tablespec.profiling.jdbc_mapper import JdbcToUmfMapper

    umfs = JdbcToUmfMapper().discover(discovery_spec, mssql_spark)
    return {u.table_name: u for u in umfs}
