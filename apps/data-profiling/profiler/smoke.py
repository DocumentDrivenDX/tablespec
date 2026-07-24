"""FR-23 agent-side smoke: resolve → provision → validate_config.

No live workspace required when ``PROFILER_RUNTIME=mock`` and a fake SQL
executor is supplied. Operator workspace steps: product microsite Getting Started.
"""

from __future__ import annotations

from typing import Mapping, Optional

from profiler.config import AppConfig, resolve_config
from profiler.diagnostics import validate_config
from profiler.provision import SqlExecutor, provision


def run_fr23_smoke(
    *,
    env: Optional[Mapping[str, str]] = None,
    registry_path: str = "connections.yaml",
    executor: Optional[SqlExecutor] = None,
    grant_to: Optional[str] = None,
) -> int:
    """Return 0 if composition succeeds, 1 if startup faults on a non-mock runtime.

    Always runs provision when an executor is provided. On mock runtime,
    validate_config returns no faults (nothing to probe).
    """
    cfg: AppConfig = resolve_config(env=env, registry_path=registry_path)
    if executor is not None:
        provision(cfg, executor=executor, grant_to=grant_to)
    faults = validate_config(cfg)
    if faults and cfg.is_databricks:
        for f in faults:
            print(f.message())
        return 1
    print(f"FR-23 smoke OK: metadata home {cfg.describe()}")
    return 0
