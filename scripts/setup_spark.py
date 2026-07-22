#!/usr/bin/env python3
"""Setup script to install Spark 4.0 with JDK 21 for local development and testing.

Downloads and configures:
- Coursier (dependency manager)
- Zulu JDK 21 (via Coursier)
- Apache Spark 4.0.0 with Hadoop 3 (includes Delta Lake 4.0)

All artifacts are installed to .local/ under the project root.

Ported from pulseflow's setup_spark_scala213.py, simplified for tablespec
(no Unity Catalog, no DBR dependencies, no Hive Thrift).
"""

import gzip
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile


def _get_exe_extension() -> str:
    """Return '.exe' on Windows, empty string otherwise."""
    return ".exe" if platform.system().lower() == "windows" else ""


def _get_script_extension() -> str:
    """Return '.cmd' on Windows, empty string otherwise."""
    return ".cmd" if platform.system().lower() == "windows" else ""


def cached_download(
    url: str,
    checksum: str,
    dest_path: Path,
    *,
    decompress_gz: bool = False,
    extract_zip: bool = False,
) -> None:
    """Download a file using a global cache with hardlinks.

    Before downloading, checks if the file exists in ~/.local/cache/tablespec-downloads/
    with a valid checksum. If so, hardlinks from cache. Otherwise, downloads to cache,
    verifies checksum, then hardlinks to destination.

    Args:
        url: The URL to download from
        checksum: Expected SHA512 checksum of the downloaded file (before decompression).
                  Use empty string to skip checksum verification.
        dest_path: Target file path (will be hardlinked or copied from cache)
        decompress_gz: If True, decompress .gz file before creating destination file
        extract_zip: If True, extract first file from .zip archive to destination

    """
    cache_dir = Path.home() / ".local" / "cache" / "tablespec-downloads"
    cache_dir.mkdir(parents=True, exist_ok=True)

    cache_filename = url.split("/")[-1]
    cache_path = cache_dir / cache_filename

    verify_checksum = bool(checksum)

    # Check if cache exists (with optional checksum validation)
    cache_valid = cache_path.exists() and (
        not verify_checksum or _verify_checksum(cache_path, checksum)
    )

    # Check if destination already exists with valid checksum
    dest_valid = dest_path.exists() and (
        not verify_checksum or _verify_checksum(dest_path, checksum)
    )

    if cache_valid:
        print(f"  Using cached file: {cache_filename}")
    elif dest_valid:
        print(f"  Destination already valid, skipping download: {dest_path.name}")
        return
    else:
        if cache_path.exists():
            if verify_checksum:
                print(f"  Cached file corrupted, re-downloading: {cache_filename}")
            cache_path.unlink()

        print(f"  Downloading to cache: {cache_filename}")
        print(f"   URL: {url}")

        try:
            result = subprocess.run(
                [
                    "curl",
                    "-C",
                    "-",
                    "-L",
                    "--retry",
                    "5",
                    "--retry-delay",
                    "3",
                    "--retry-connrefused",
                    "-o",
                    str(cache_path),
                    "--progress-bar",
                    url,
                ],
                check=True,
                capture_output=False,
            )
            if result.returncode == 0:
                print(f"  Downloaded to cache: {cache_filename}")
            else:
                msg = f"curl failed with code {result.returncode}"
                raise Exception(msg)
        except FileNotFoundError:
            print("   (Using fallback download method, no progress bar)")
            try:
                urllib.request.urlretrieve(url, cache_path)
                print(f"  Downloaded to cache: {cache_filename}")
            except Exception as e:
                print(f"  Failed to download: {e}")
                if cache_path.exists():
                    cache_path.unlink()
                sys.exit(1)
        except Exception as e:
            print(f"  Failed to download: {e}")
            if cache_path.exists():
                cache_path.unlink()
            sys.exit(1)

        if verify_checksum:
            if not _verify_checksum(cache_path, checksum):
                print("  Downloaded file failed checksum verification")
                cache_path.unlink()
                sys.exit(1)
            print(f"  Checksum verified for {cache_filename}")

    # Create destination file from cache
    if dest_path.exists():
        dest_path.unlink()

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    if decompress_gz:
        print(f"  Decompressing {cache_filename}...")
        try:
            with gzip.open(cache_path, "rb") as f_in, open(dest_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            if platform.system().lower() != "windows":
                dest_path.chmod(0o755)
            print(f"  Decompressed to {dest_path.name}")
        except Exception as e:
            print(f"  Failed to decompress: {e}")
            if dest_path.exists():
                dest_path.unlink()
            sys.exit(1)
    elif extract_zip:
        print(f"  Extracting {cache_filename}...")
        try:
            with zipfile.ZipFile(cache_path, "r") as zip_ref:
                names = zip_ref.namelist()
                if not names:
                    msg = "ZIP file is empty"
                    raise RuntimeError(msg)
                with zip_ref.open(names[0]) as source, open(dest_path, "wb") as target:
                    shutil.copyfileobj(source, target)
            if platform.system().lower() != "windows":
                dest_path.chmod(0o755)
            print(f"  Extracted to {dest_path.name}")
        except Exception as e:
            print(f"  Failed to extract: {e}")
            if dest_path.exists():
                dest_path.unlink()
            sys.exit(1)
    else:
        try:
            os.link(cache_path, dest_path)
            print(f"  Hardlinked from cache to {dest_path.name}")
        except OSError:
            shutil.copy2(cache_path, dest_path)
            print(f"  Copied from cache to {dest_path.name} (hardlink not supported)")


def _verify_checksum(file_path: Path, expected_checksum: str) -> bool:
    """Verify SHA512 checksum of a file."""
    if not file_path.exists():
        return False
    try:
        sha512_hash = hashlib.sha512()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha512_hash.update(chunk)
        return sha512_hash.hexdigest() == expected_checksum
    except Exception:
        return False


def setup_coursier(bin_dir: Path) -> None:
    """Download and install Coursier CLI using cached download."""
    if shutil.which("cs"):
        print("  Coursier already available in PATH")
        return

    coursier_bin = bin_dir / f"cs{_get_exe_extension()}"

    if coursier_bin.exists() and coursier_bin.stat().st_size > 0:
        print("  Coursier already installed")
        return

    print("  Installing Coursier...")

    system = platform.system().lower()
    machine = platform.machine().lower()

    arch_map = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "arm64": "aarch64",
        "aarch64": "aarch64",
    }
    arch = arch_map.get(machine, machine)

    if system == "darwin":
        coursier_url = f"https://github.com/coursier/launchers/raw/master/cs-{arch}-apple-darwin.gz"
        use_zip = False
    elif system == "linux":
        coursier_url = (
            f"https://github.com/coursier/launchers/raw/master/cs-{arch}-pc-linux.gz"
        )
        use_zip = False
    elif system == "windows":
        coursier_url = (
            f"https://github.com/coursier/launchers/raw/master/cs-{arch}-pc-win32.zip"
        )
        use_zip = True
    else:
        msg = f"Unsupported platform: {system}"
        raise RuntimeError(msg)

    print(f"   Platform: {system}-{arch}")

    try:
        if use_zip:
            cached_download(coursier_url, "", coursier_bin, extract_zip=True)
        else:
            cached_download(coursier_url, "", coursier_bin, decompress_gz=True)

        if coursier_bin.exists() and coursier_bin.stat().st_size > 0:
            test_result = subprocess.run(
                [str(coursier_bin), "--help"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if test_result.returncode == 0:
                print("  Coursier is working correctly")
            else:
                msg = "Coursier installed but not working correctly"
                raise RuntimeError(msg)
        else:
            msg = "Coursier binary not found or empty after installation"
            raise RuntimeError(msg)

    except Exception as e:
        print(f"  Failed to install Coursier: {e}")
        sys.exit(1)


def setup_jdk(bin_dir: Path, share_dir: Path) -> None:
    """Install Zulu JDK 21 using Coursier (required for Spark 4.0.0)."""
    cs_path = shutil.which("cs")
    coursier_bin = cs_path or str(bin_dir / f"cs{_get_exe_extension()}")

    java_home = share_dir / "java"

    # Check if JDK is already installed and correct version
    java_bin = java_home / "bin" / f"java{_get_exe_extension()}"
    if java_home.exists() and java_bin.exists():
        try:
            result = subprocess.run(
                [str(java_bin), "-version"],
                capture_output=True,
                text=True,
                check=True,
            )
            if "21.0" in result.stderr and "Zulu" in result.stderr:
                print("  Zulu JDK 21 already installed")
                return
        except subprocess.CalledProcessError:
            pass

    print("  Installing Zulu JDK 21 using Coursier...")
    print("   This may take 2-5 minutes (downloading ~100-150 MB)...")
    try:
        subprocess.run(
            [coursier_bin, "java", "--jvm", "zulu:21", "-version"],
            check=True,
            timeout=300,
        )

        env_result = subprocess.run(
            [coursier_bin, "java", "--jvm", "zulu:21", "--env"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )

        java_home_path = None
        for line in env_result.stdout.strip().split("\n"):
            if "export JAVA_HOME=" in line:
                potential_path = line.split("export JAVA_HOME=")[1].strip("\"'")
                if potential_path and not potential_path.startswith(("%", "$")):
                    java_home_path = potential_path
                break
            if "$env:JAVA_HOME" in line or "set JAVA_HOME" in line:
                if "=" in line:
                    potential_path = line.split("=", 1)[1].strip().strip("\"'")
                    if potential_path and not potential_path.startswith(("%", "$")):
                        java_home_path = potential_path
                break

        if not java_home_path:
            try:
                home_result = subprocess.run(
                    [coursier_bin, "java-home", "--jvm", "zulu:21"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                potential_path = home_result.stdout.strip()
                if potential_path and not potential_path.startswith("%"):
                    test_path = Path(potential_path)
                    if (
                        test_path.exists()
                        and (test_path / "bin" / f"java{_get_exe_extension()}").exists()
                    ):
                        java_home_path = potential_path
            except subprocess.CalledProcessError:
                pass

        # Last resort: search coursier cache
        if not java_home_path:
            print("  Trying to locate JDK in Coursier cache...")
            cache_locations = []
            if platform.system().lower() == "windows":
                localappdata = os.getenv("LOCALAPPDATA")
                if localappdata:
                    cache_locations.append(
                        Path(localappdata) / "Coursier" / "cache" / "arc"
                    )
            else:
                cache_locations.append(Path.home() / ".cache" / "coursier" / "arc")

            for cache_loc in cache_locations:
                if cache_loc.exists():
                    for jdk_dir in cache_loc.glob("**/zulu*21.*"):
                        if (jdk_dir / "bin" / f"java{_get_exe_extension()}").exists():
                            java_home_path = str(jdk_dir)
                            print(f"  Found JDK in cache: {jdk_dir}")
                            break
                if java_home_path:
                    break

        if not java_home_path:
            print("  Could not determine JAVA_HOME from Coursier")
            print(f"   --env output was:\n{env_result.stdout}")
            msg = "Could not determine JAVA_HOME from Coursier"
            raise RuntimeError(msg)

        java_home_path = Path(java_home_path)
        if java_home.exists():
            if java_home.is_symlink():
                java_home.unlink()
            else:
                shutil.rmtree(java_home)

        if platform.system().lower() == "windows":
            shutil.copytree(java_home_path, java_home)
            print("  Zulu JDK 21 copied successfully")
        else:
            java_home.symlink_to(java_home_path)
            print("  Zulu JDK 21 symlinked successfully")

        print(f"   JAVA_HOME: {java_home_path}")

        java_exec = java_home / "bin" / f"java{_get_exe_extension()}"
        result = subprocess.run(
            [str(java_exec), "-version"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            version_line = result.stderr.split("\n")[0]
            print(f"   Java version: {version_line}")

    except subprocess.TimeoutExpired:
        print("  JDK installation timed out after 5 minutes")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"  Failed to install JDK using Coursier: {e}")
        sys.exit(1)


def download_and_extract_spark(
    spark_url: str,
    spark_filename: str,
    spark_checksum: str,
    download_dir: Path,
    local_dir: Path,
    spark_home: Path,
) -> None:
    """Download and extract Spark tarball using cached download."""
    spark_tarball = download_dir / spark_filename

    if _is_spark_installation_valid(spark_home):
        print(f"  Spark already extracted at {spark_home}")
        return

    print(f"  Downloading Spark {spark_filename}...")
    cached_download(spark_url, spark_checksum, spark_tarball)

    if spark_home.exists():
        print("  Incomplete Spark installation detected, cleaning up...")
        shutil.rmtree(spark_home)

    print(f"  Extracting {spark_filename}...")
    try:
        with tarfile.open(spark_tarball, "r:gz") as tar:
            tar.extractall(local_dir)
        print(f"  Extracted to {spark_home}")
    except Exception as e:
        print(f"  Failed to extract Spark: {e}")
        sys.exit(1)


def fetch_delta_lake(bin_dir: Path, spark_home: Path) -> None:
    """Fetch Delta Lake 4.0 JARs using Coursier and install into Spark jars directory."""
    jars_dir = spark_home / "jars"

    # Check if Delta Lake is already installed
    existing = list(jars_dir.glob("delta-spark_2.13-*.jar"))
    if existing:
        print(f"  Delta Lake already installed: {existing[0].name}")
        return

    cs_path = shutil.which("cs")
    coursier_bin = cs_path or str(bin_dir / f"cs{_get_exe_extension()}")

    cache_dir = spark_home.parent / "cache" / "coursier"
    cache_dir.mkdir(parents=True, exist_ok=True)

    dependency = "io.delta:delta-spark_2.13:4.0.0"
    print(f"  Fetching Delta Lake dependency: {dependency}")
    print("   This may take 1-3 minutes on first run...")

    try:
        cmd = [
            coursier_bin,
            "fetch",
            "--cache",
            str(cache_dir),
            "--repository",
            "central",
            "--repository",
            "https://repo1.maven.org/maven2",
            dependency,
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=300,
        )
        jar_paths = result.stdout.strip().split("\n")

        print(f"  Fetched {len(jar_paths)} JAR files")

        copied_count = 0
        for jar_path_raw in jar_paths:
            jar_path = jar_path_raw.strip()
            if jar_path and jar_path.endswith(".jar"):
                jar_file = Path(jar_path)
                if jar_file.exists():
                    dest_jar = jars_dir / jar_file.name
                    if not dest_jar.exists():
                        shutil.copy2(jar_file, dest_jar)
                        copied_count += 1

        print(f"  Copied {copied_count} new JARs to Spark jars directory")

    except subprocess.TimeoutExpired:
        print("  Delta Lake fetch timed out after 5 minutes")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"  Failed to fetch Delta Lake: {e}")
        print(f"   stderr: {e.stderr}")
        sys.exit(1)


def _is_spark_installation_valid(spark_dir: Path) -> bool:
    """Check if Spark installation is complete and valid."""
    if not spark_dir.exists():
        return False

    spark_submit = spark_dir / "bin" / f"spark-submit{_get_script_extension()}"
    required_paths = [
        spark_submit,
        spark_dir / "python" / "pyspark",
        spark_dir / "python" / "lib",
        spark_dir / "jars",
        spark_dir / "conf",
    ]

    for path in required_paths:
        if not path.exists():
            return False

    py4j_lib = spark_dir / "python" / "lib"
    py4j_jars = list(py4j_lib.glob("py4j-*.zip"))
    if not py4j_jars:
        return False

    jars_dir = spark_dir / "jars"
    essential_jars = ["spark-core*", "spark-sql*", "spark-catalyst*"]
    return all(
        list(jars_dir.glob(f"{jar_pattern}.jar")) for jar_pattern in essential_jars
    )


def _is_complete_setup_valid(spark_home: Path, bin_dir: Path) -> bool:
    """Check if complete setup (Coursier + JDK + Spark) is valid."""
    coursier_bin = bin_dir / f"cs{_get_exe_extension()}"

    if not coursier_bin.exists() and not shutil.which("cs"):
        return False

    project_root = bin_dir.parent
    java_home = project_root / "share" / "java"
    java_bin = java_home / "bin" / f"java{_get_exe_extension()}"
    if not java_bin.exists():
        return False

    if not _is_spark_installation_valid(spark_home):
        return False

    # Spark 4.0 bundles Delta Lake, so check for delta jars
    jars_dir = spark_home / "jars"
    key_jars = ["delta-spark_2.13-*.jar"]
    return all(list(jars_dir.glob(jar_pattern)) for jar_pattern in key_jars)


def _create_log4j_config(spark_dir: Path) -> None:
    """Create log4j2.properties configuration for quiet local development logging."""
    conf_dir = spark_dir / "conf"
    log4j_config_path = conf_dir / "log4j2.properties"

    if log4j_config_path.exists():
        print("  log4j2.properties already exists")
        return

    log4j_content = """#
# Tablespec Spark Logging Configuration
# ERROR level to console only (quiet for testing)
#

rootLogger.level = error
rootLogger.appenderRef.console.ref = console

appender.console.type = Console
appender.console.name = console
appender.console.target = SYSTEM_ERR
appender.console.layout.type = PatternLayout
appender.console.layout.pattern = %d{HH:mm:ss} %p %c{1}: %m%n

# Suppress py4j debug logging
logger.py4j.name = py4j
logger.py4j.level = error

# Suppress noisy Spark components
logger.spark_storage.name = org.apache.spark.storage
logger.spark_storage.level = error

logger.spark_scheduler.name = org.apache.spark.scheduler
logger.spark_scheduler.level = error

logger.hadoop.name = org.apache.hadoop
logger.hadoop.level = error

logger.hadoop_util.name = org.apache.hadoop.util.NativeCodeLoader
logger.hadoop_util.level = error

logger.jetty.name = org.eclipse.jetty
logger.jetty.level = error

logger.delta.name = io.delta
logger.delta.level = warn
"""

    try:
        with open(log4j_config_path, "w") as f:
            f.write(log4j_content)
        print(f"  Created log4j2.properties at {log4j_config_path}")
    except Exception as e:
        print(f"  Failed to create log4j2.properties: {e}")
        sys.exit(1)


def _check_java_installation(java_home_path: Path) -> None:
    """Validate that Java is installed and runnable."""
    java_executable = java_home_path / "bin" / f"java{_get_exe_extension()}"
    if not java_executable.exists():
        msg = f"Java executable not found at {java_executable}"
        raise RuntimeError(msg)
    try:
        result = subprocess.run(
            [str(java_executable), "-version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            msg = f"Java version command failed: {result.stderr.strip()}"
            raise RuntimeError(msg)
        print("  Java installation verified:\n" + result.stderr.strip())
    except Exception as e:
        msg = f"Failed to verify Java installation: {e}"
        raise RuntimeError(msg) from e


def verify_spark_session() -> bool:
    """Verify Spark works by creating a session via the tablespec factory."""
    print("Verifying Spark session creation...")

    project_root = Path(__file__).parent.parent
    spark_home = project_root / ".local" / "spark-4.0.0-bin-hadoop3"
    java_home = project_root / ".local" / "share" / "java"

    if not spark_home.exists():
        print(f"  Spark home not found at {spark_home}")
        return False

    # Set environment so the factory finds the local Spark install
    os.environ["SPARK_HOME"] = str(spark_home)
    os.environ["JAVA_HOME"] = str(java_home)
    os.environ["PYSPARK_PYTHON"] = sys.executable
    os.environ["PYSPARK_DRIVER_PYTHON"] = sys.executable

    try:
        from tablespec.spark_factory import create_delta_spark_session

        spark = create_delta_spark_session(
            "tablespec-setup-verify",
            {
                "spark.master": "local[1]",
                "spark.ui.enabled": "false",
            },
        )

        spark.sparkContext.setLogLevel("ERROR")

        # Test basic Spark
        test_df = spark.range(3)
        result = test_df.collect()
        if len(result) != 3:
            print(f"  Spark test failed: expected 3 rows, got {len(result)}")
            spark.stop()
            return False
        print("  Basic Spark operation verified")

        # Test Delta Lake
        import tempfile

        temp_dir = tempfile.mkdtemp()
        try:
            test_df.write.format("delta").mode("overwrite").save(temp_dir)
            delta_df = spark.read.format("delta").load(temp_dir)
            delta_result = delta_df.collect()
            if len(delta_result) != 3:
                print(
                    f"  Delta Lake test failed: expected 3 rows, got {len(delta_result)}"
                )
                spark.stop()
                return False
            print("  Delta Lake write/read verified")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            spark.stop()

        return True

    except Exception as e:
        print(f"  Spark session test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def setup_spark() -> None:
    """Set up Spark 4.0 with JDK 21 for local development."""
    print("Setting up Spark 4.0 for tablespec local development...")

    # Configuration
    spark_version = "4.0.0"
    spark_filename = f"spark-{spark_version}-bin-hadoop3.tgz"
    spark_url = (
        f"https://archive.apache.org/dist/spark/spark-{spark_version}/{spark_filename}"
    )
    spark_checksum = "b5a9e2ea22ac971bad81ab079e510f1ab92732efaf790af4b895174b28d99a65d35543f4300caa073257b6fe42062daafe3eea106d1945806166098606f8d03c"

    # Directories
    project_root = Path(__file__).parent.parent
    local_dir = project_root / ".local"
    download_dir = local_dir / "downloads"
    bin_dir = local_dir / "bin"
    share_dir = local_dir / "share"
    spark_home = local_dir / f"spark-{spark_version}-bin-hadoop3"

    # Create directories
    for directory in [local_dir, download_dir, bin_dir, share_dir]:
        directory.mkdir(exist_ok=True, parents=True)

    # Check if complete setup is already valid
    if _is_complete_setup_valid(spark_home, bin_dir):
        print(f"  Valid Spark installation found at {spark_home}")
    else:
        print("  Setup validation failed, proceeding with installation...")

        # Step 1: Setup Coursier
        print("\nStep 1: Setting up Coursier...")
        setup_coursier(bin_dir)

        # Step 2: Setup JDK using Coursier
        print("\nStep 2: Setting up JDK 21 (Zulu) using Coursier...")
        setup_jdk(bin_dir, share_dir)

        # Step 3: Download and setup Spark
        print("\nStep 3: Setting up Spark...")
        download_and_extract_spark(
            spark_url,
            spark_filename,
            spark_checksum,
            download_dir,
            local_dir,
            spark_home,
        )

    # Step 4: Fetch Delta Lake JARs
    print("\nStep 4: Fetching Delta Lake 4.0 JARs...")
    fetch_delta_lake(bin_dir, spark_home)

    # Verify Java
    java_home_path = project_root / ".local" / "share" / "java"
    _check_java_installation(java_home_path)

    # Configure logging
    print("\nConfiguring Spark logging...")
    _create_log4j_config(spark_home)

    # Verify Spark session
    print()
    if not verify_spark_session():
        print("\nSpark verification failed - setup incomplete")
        sys.exit(1)

    print("\nSpark 4.0 setup complete!")
    print(f"  SPARK_HOME: {spark_home}")
    print(f"  JAVA_HOME:  {java_home_path}")


if __name__ == "__main__":
    setup_spark()
