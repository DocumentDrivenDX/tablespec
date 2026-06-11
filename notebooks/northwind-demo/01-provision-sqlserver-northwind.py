# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Provision SQL Server + Northwind on the driver node
# MAGIC
# MAGIC **Consumer-side plumbing for the tablespec Northwind demo (US-039).**
# MAGIC
# MAGIC Installs SQL Server 2022 (Developer edition) directly on this cluster's
# MAGIC driver node, configures it via mssql-conf, and loads the Northwind fixture —
# MAGIC the same scenario as the `mssql_import` bundle (a database restored on a
# MAGIC Databricks driver node). tablespec itself never does any of this: per
# MAGIC US-039 / FEAT-031, install/restore is consumer-owned and tablespec only
# MAGIC ever *points* at the resulting JDBC endpoint.
# MAGIC
# MAGIC **Cluster requirements**
# MAGIC - Single node (driver == executor, so `localhost` JDBC works end-to-end)
# MAGIC - An LTS runtime whose Ubuntu has a SQL Server release: the notebook
# MAGIC   detects the host Ubuntu and installs the matching rev —
# MAGIC   Ubuntu 22.04 (DBR 15.4/16.4 LTS) → SQL Server 2022;
# MAGIC   Ubuntu 24.04 (DBR 17.3 LTS, Spark 4) → SQL Server 2025
# MAGIC - Single-user access mode (shell commands run as root)
# MAGIC
# MAGIC **Widgets**
# MAGIC - `sa_password` — SA password; leave empty to auto-generate. Stored only
# MAGIC   at `/local_disk0/northwind_demo/sa_password` (mode 0600, driver-local,
# MAGIC   gone when the cluster terminates). For anything beyond a demo, use a
# MAGIC   Databricks secret scope instead.
# MAGIC - `fixture_path` — path to `northwind.sql`. Defaults to the copy shipped
# MAGIC   next to this notebook (works from a Git folder checkout); also accepts
# MAGIC   a `/dbfs/...` or `/Volumes/...` path.

# COMMAND ----------

dbutils.widgets.text("sa_password", "", "SA password (empty = auto-generate)")
dbutils.widgets.text("fixture_path", "", "Path to northwind.sql (empty = next to notebook)")

# COMMAND ----------

import os
import secrets
import string
from pathlib import Path

STATE_DIR = Path("/local_disk0/northwind_demo")
STATE_DIR.mkdir(parents=True, exist_ok=True)
PASSWORD_FILE = STATE_DIR / "sa_password"
URL_FILE = STATE_DIR / "jdbc_url"
SQLSERVR_LOG = STATE_DIR / "sqlservr.log"

JDBC_URL = (
    "jdbc:sqlserver://localhost:1433;databaseName=Northwind;"
    "encrypt=true;trustServerCertificate=true"
)


def _resolve_sa_password() -> str:
    widget = dbutils.widgets.get("sa_password").strip()
    if widget:
        return widget
    if PASSWORD_FILE.exists():
        return PASSWORD_FILE.read_text().strip()
    alphabet = string.ascii_letters + string.digits
    # SQL Server complexity: upper + lower + digit, length >= 8.
    return "Nw1" + "".join(secrets.choice(alphabet) for _ in range(17))


def _resolve_fixture_path() -> Path:
    widget = dbutils.widgets.get("fixture_path").strip()
    if widget:
        path = Path(widget)
        if not path.exists():
            raise FileNotFoundError(f"fixture_path widget points at a missing file: {path}")
        return path
    # Default: northwind.sql shipped next to this notebook (Git folder /
    # workspace import keep the folder layout).
    notebook_dir = Path(
        dbutils.notebook.entry_point.getDbutils()
        .notebook()
        .getContext()
        .notebookPath()
        .get()
    ).parent
    candidates = [
        Path("/Workspace") / notebook_dir.relative_to("/") / "northwind.sql",
        Path.cwd() / "northwind.sql",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "northwind.sql not found next to the notebook; pass fixture_path "
        f"(tried: {[str(c) for c in candidates]})"
    )


SA_PASSWORD = _resolve_sa_password()
FIXTURE = _resolve_fixture_path()
PASSWORD_FILE.write_text(SA_PASSWORD)
PASSWORD_FILE.chmod(0o600)
URL_FILE.write_text(JDBC_URL)
print(f"fixture: {FIXTURE}")
print(f"jdbc url: {JDBC_URL}")
print(f"sa password: stored at {PASSWORD_FILE} (not echoed)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Install SQL Server 2022 + sqlcmd (idempotent)

# COMMAND ----------

import subprocess


def sh(cmd: str, **env: str) -> str:
    """Run a shell command as root on the driver; raise with output on failure."""
    result = subprocess.run(
        ["bash", "-lc", cmd],
        capture_output=True,
        text=True,
        env={**os.environ, **env},
    )
    if result.returncode != 0:
        # Print the FULL output to the cell first — the platform truncates
        # exception messages, which hides the decisive line (e.g. apt's E:).
        print(f"command failed ({result.returncode}): {cmd}")
        print("--- stdout ---");  print(result.stdout[-8000:])
        print("--- stderr ---");  print(result.stderr[-8000:])
        raise RuntimeError(f"command failed ({result.returncode}): {cmd}")
    return result.stdout


# Detect the host Ubuntu and select the matching SQL Server release:
# Ubuntu 22.04 → SQL Server 2022; Ubuntu 24.04 → SQL Server 2025.
_os_release = dict(
    line.split("=", 1)
    for line in Path("/etc/os-release").read_text().splitlines()
    if "=" in line
)
UBUNTU = _os_release["VERSION_ID"].strip('"')
MSSQL_REV = {"22.04": "2022", "24.04": "2025"}.get(UBUNTU)
if MSSQL_REV is None:
    raise RuntimeError(
        f"Unsupported Ubuntu {UBUNTU}: no matching mssql-server release "
        "(supported: 22.04 → 2022, 24.04 → 2025). Pick a DBR whose Ubuntu "
        "is supported (15.4/16.4 LTS → 22.04, 17.3 LTS → 24.04)."
    )
# sqlservr links against liblber/libldap, which Azure DBR images don't ship
# (exit 127 without them); the runtime package name differs per Ubuntu.
LDAP_LIBS = {"22.04": "libldap-2.5-0 libsasl2-2", "24.04": "libldap2 libsasl2-2"}[UBUNTU]
print(f"host: Ubuntu {UBUNTU} → mssql-server-{MSSQL_REV}")

if Path("/opt/mssql/bin/sqlservr").exists():
    print("mssql-server already installed — skipping apt install")
else:
    # Microsoft repo trust, belt and braces (Azure DBR images pre-trust
    # nothing, and the repo InRelease may be signed by a key that
    # keys/microsoft.asc does not carry — observed on the 24.04/2025 repos):
    # build a keyring from microsoft.asc, show what's in it, fetch the
    # repo-signing key from the Ubuntu keyserver if missing, install the
    # keyring in BOTH locations, and inject explicit signed-by into the lists.
    MS_SIGNING_KEY = "EB3E94ADBE1229CF"
    sh(
        "curl -fsSL https://packages.microsoft.com/keys/microsoft.asc "
        "| sudo gpg --dearmor --yes -o /usr/share/keyrings/microsoft-prod.gpg"
    )
    keys = sh("gpg --show-keys --keyid-format long /usr/share/keyrings/microsoft-prod.gpg")
    print(keys)
    if MS_SIGNING_KEY not in keys:
        print(f"{MS_SIGNING_KEY} missing from microsoft.asc — fetching from keyserver")
        sh(
            "sudo gpg --no-default-keyring --keyring /usr/share/keyrings/microsoft-prod.gpg "
            f"--keyserver hkps://keyserver.ubuntu.com --recv-keys {MS_SIGNING_KEY}"
        )
        print(sh("gpg --show-keys --keyid-format long /usr/share/keyrings/microsoft-prod.gpg"))
    sh("sudo cp /usr/share/keyrings/microsoft-prod.gpg /etc/apt/trusted.gpg.d/microsoft-prod.gpg")
    for repo, dest in [
        (f"mssql-server-{MSSQL_REV}.list", f"mssql-server-{MSSQL_REV}.list"),
        ("prod.list", "mssql-release.list"),
    ]:
        sh(
            f"curl -fsSL https://packages.microsoft.com/config/ubuntu/{UBUNTU}/{repo} "
            f"| sed 's|\\[arch=|[signed-by=/usr/share/keyrings/microsoft-prod.gpg arch=|; "
            f"s|^deb https|deb [signed-by=/usr/share/keyrings/microsoft-prod.gpg] https|' "
            f"| sudo tee /etc/apt/sources.list.d/{dest}"
        )
    # Jammy DBR images use a curated apt mirror that omits the LDAP runtime
    # libs sqlservr needs ('no installation candidate'); add the official
    # Ubuntu archive there. Noble images already configure the full archive
    # (ubuntu.sources) — adding it again only produces duplicate-target noise.
    if UBUNTU == "22.04":
        sh(
            'echo "deb http://archive.ubuntu.com/ubuntu jammy main universe" '
            "| sudo tee /etc/apt/sources.list.d/ubuntu-archive-demo.list"
        )
    sh("sudo apt-get update")
    sh(
        "sudo ACCEPT_EULA=Y DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "
        f"mssql-server mssql-tools18 msodbcsql18 unixodbc-dev {LDAP_LIBS}"
    )
    print(f"installed mssql-server-{MSSQL_REV} + mssql-tools18 + msodbcsql18 (+ldap runtime libs)")

SQLCMD = "/opt/mssql-tools18/bin/sqlcmd"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configure + start SQL Server (proven `mssql-conf` + `systemctl` path)

# COMMAND ----------

import time


def _sqlcmd(query: str, database: str = "master") -> subprocess.CompletedProcess:
    return subprocess.run(
        [SQLCMD, "-C", "-S", "localhost", "-U", "sa", "-P", SA_PASSWORD,
         "-d", database, "-Q", query, "-b"],
        capture_output=True,
        text=True,
    )


def _dump_diagnostics() -> None:
    """Make failures diagnosable from the job-run output (the cluster is ephemeral)."""
    for cmd in (
        "sudo tail -n 60 /var/opt/mssql/log/errorlog 2>/dev/null || true",
        "sudo systemctl status mssql-server --no-pager 2>&1 | tail -n 20 || true",
        "sudo journalctl -u mssql-server --no-pager 2>&1 | tail -n 30 || true",
        "free -m",
    ):
        print(f"\n$ {cmd}")
        print(subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True).stdout)


already_up = _sqlcmd("SELECT 1").returncode == 0
if already_up:
    print("SQL Server already running")
else:
    # The sequence proven on Databricks by the mssql_import bundle:
    # clean slate, non-interactive mssql-conf setup with preserved env,
    # then systemd start (available on DBR driver nodes).
    sh("sudo systemctl stop mssql-server 2>/dev/null || true")
    sh("sudo rm -rf /var/opt/mssql")
    result = subprocess.run(
        [
            "sudo",
            "--preserve-env=MSSQL_SA_PASSWORD,ACCEPT_EULA,MSSQL_PID",
            "/opt/mssql/bin/mssql-conf",
            "-n",
            "setup",
        ],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "MSSQL_SA_PASSWORD": SA_PASSWORD,
            "ACCEPT_EULA": "Y",
            "MSSQL_PID": "Developer",
        },
    )
    print(result.stdout[-2000:])
    if result.returncode != 0:
        _dump_diagnostics()
        raise RuntimeError(f"mssql-conf setup failed:\n{result.stderr[-2000:]}")
    sh("sudo systemctl start mssql-server")

    deadline = time.time() + 180
    while time.time() < deadline:
        if _sqlcmd("SELECT 1").returncode == 0:
            break
        time.sleep(2)
    else:
        _dump_diagnostics()
        raise RuntimeError("SQL Server did not become ready within 180s")
    print("SQL Server is up")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load the Northwind fixture (idempotent)

# COMMAND ----------

has_db = _sqlcmd(
    "IF DB_ID('Northwind') IS NULL RAISERROR('missing', 16, 1)"
).returncode == 0

if has_db:
    print("Northwind database already present — skipping fixture load")
else:
    local_fixture = STATE_DIR / "northwind.sql"
    local_fixture.write_text(Path(FIXTURE).read_text())
    result = subprocess.run(
        [SQLCMD, "-C", "-S", "localhost", "-U", "sa", "-P", SA_PASSWORD,
         "-i", str(local_fixture), "-b"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"fixture load failed:\n{result.stdout[-3000:]}\n{result.stderr[-1000:]}")
    print("Northwind loaded")

tables = _sqlcmd(
    "SET NOCOUNT ON; SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
    "WHERE TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME",
    database="Northwind",
)
print(tables.stdout)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Handoff
# MAGIC
# MAGIC The demo notebook (`02-northwind-discovery-demo`) reads the endpoint from
# MAGIC `/local_disk0/northwind_demo/` — run it on **this same cluster**.

# COMMAND ----------

print("READY")
print(f"  jdbc_url      : {JDBC_URL}")
print(f"  password file : {PASSWORD_FILE} (driver-local, 0600)")
dbutils.notebook.exit("READY")
