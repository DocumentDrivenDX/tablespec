# Agent Instructions

This project uses **bd** (beads) for issue tracking. Run `bd onboard` to get started.

## Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work atomically
bd close <id>         # Complete work
bd dolt push          # Push beads data to remote
```

## Non-Interactive Shell Commands

**ALWAYS use non-interactive flags** with file operations to avoid hanging on confirmation prompts.

Shell commands like `cp`, `mv`, and `rm` may be aliased to include `-i` (interactive) mode on some systems, causing the agent to hang indefinitely waiting for y/n input.

**Use these forms instead:**
```bash
# Force overwrite without prompting
cp -f source dest           # NOT: cp source dest
mv -f source dest           # NOT: mv source dest
rm -f file                  # NOT: rm file

# For recursive operations
rm -rf directory            # NOT: rm -r directory
cp -rf source dest          # NOT: cp -r source dest
```

**Other commands that may prompt:**
- `scp` - use `-o BatchMode=yes` for non-interactive
- `ssh` - use `-o BatchMode=yes` to fail instead of prompting
- `apt-get` - use `-y` flag
- `brew` - use `HOMEBREW_NO_AUTO_UPDATE=1` env var

<!-- BEGIN BEADS INTEGRATION -->
## Issue Tracking with bd (beads)

**IMPORTANT**: This project uses **bd (beads)** for ALL issue tracking. Do NOT use markdown TODOs, task lists, or other tracking methods.

### Why bd?

- Dependency-aware: Track blockers and relationships between issues
- Version-controlled: Built on Dolt with cell-level merge
- Agent-optimized: JSON output, ready work detection, discovered-from links
- Prevents duplicate tracking systems and confusion

### Quick Start

**Check for ready work:**

```bash
bd ready --json
```

**Create new issues:**

```bash
bd create "Issue title" --description="Detailed context" -t bug|feature|task -p 0-4 --json
bd create "Issue title" --description="What this issue is about" -p 1 --deps discovered-from:bd-123 --json
```

**Claim and update:**

```bash
bd update <id> --claim --json
bd update bd-42 --priority 1 --json
```

**Complete work:**

```bash
bd close bd-42 --reason "Completed" --json
```

### Issue Types

- `bug` - Something broken
- `feature` - New functionality
- `task` - Work item (tests, docs, refactoring)
- `epic` - Large feature with subtasks
- `chore` - Maintenance (dependencies, tooling)

### Priorities

- `0` - Critical (security, data loss, broken builds)
- `1` - High (major features, important bugs)
- `2` - Medium (default, nice-to-have)
- `3` - Low (polish, optimization)
- `4` - Backlog (future ideas)

### Workflow for AI Agents

1. **Check ready work**: `bd ready` shows unblocked issues
2. **Claim your task atomically**: `bd update <id> --claim`
3. **Work on it**: Implement, test, document
4. **Discover new work?** Create linked issue:
   - `bd create "Found bug" --description="Details about what was found" -p 1 --deps discovered-from:<parent-id>`
5. **Complete**: `bd close <id> --reason "Done"`

### Auto-Sync

bd automatically syncs with git:

- Exports to `.beads/issues.jsonl` after changes (5s debounce)
- Imports from JSONL when newer (e.g., after `git pull`)
- No manual export/import needed!

### Important Rules

- ✅ Use bd for ALL task tracking
- ✅ Always use `--json` flag for programmatic use
- ✅ Link discovered work with `discovered-from` dependencies
- ✅ Check `bd ready` before asking "what should I work on?"
- ❌ Do NOT create markdown TODO lists
- ❌ Do NOT use external issue trackers
- ❌ Do NOT duplicate tracking systems

For more details, see README.md and docs/QUICKSTART.md.

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds

<!-- END BEADS INTEGRATION -->

## Running Tests on Databricks

### Architecture: Single Spark Entrypoint

`tablespec.spark_factory.create_delta_spark_session()` is the **single entrypoint** for all
Spark session creation. It detects the environment automatically:
- On Databricks: returns the runtime's active SparkSession (never creates one).
- Locally: creates a session with Delta Lake config.

The `spark_session` pytest fixture in `tests/conftest.py` delegates to this factory.
Do NOT add separate Databricks detection logic anywhere else.

### Critical: Run pytest IN-PROCESS (not as subprocess)

On Databricks, the SparkSession lives in the notebook kernel process. A subprocess
(e.g. `subprocess.run(["python", "-m", "pytest", ...])`) **cannot** access it because
Spark Connect URLs aren't inherited. Always use `pytest.main([...])` in-process.

### Critical: Do NOT use `uv run pytest` on Databricks

The Databricks runtime provides PySpark via Spark Connect in the system Python environment.
`uv run` creates an isolated `.venv` that **cannot access the runtime's PySpark** — all
Spark-dependent tests will fail with `ModuleNotFoundError` or Spark Connect URL errors.

**Correct pattern (in a notebook cell):**
```python
# Cell 1: %pip triggers interpreter restart → .pth files processed → no sys.path hacking
%pip install -e /Workspace/Users/erik.labianca@synaptiq.ai/tablespec --quiet
%pip install ipytest pytest-cov pytest-mock anyio hypothesis --quiet

# Cell 2: Configure ipytest (notebook-friendly pytest wrapper)
import ipytest, os, sys
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True
ipytest.autoconfig(addopts=["-v", "--tb=short", "-p", "no:cacheprovider"],
                   run_in_thread=False, raise_on_error=True)

# Cell 3: Run tests in-process (factory's getActiveSession() finds runtime session)
ipytest.run("tests/integration/")
```

**Wrong patterns:**
```bash
# DO NOT — subprocess can't access Spark Connect session
python -m pytest tests/

# DO NOT — creates isolated venv without pyspark
uv run pytest tests/
```

### Workspace filesystem limitations

- **No `__pycache__` support**: The workspace filesystem (`/Workspace/...`) does not support
  creating `__pycache__` directories. Always set `PYTHONDONTWRITEBYTECODE=1` and use
  `-p no:cacheprovider` with pytest.
- **No `.venv` on workspace FS**: If you must use uv for non-Spark work, point the venv to
  local disk: `UV_PROJECT_ENVIRONMENT=/tmp/tablespec-venv`

### Makefile targets

- `make test-databricks` — integration tests only
- `make test-databricks-all` — full suite (skips modules requiring local Spark install)

### Runner notebook

`scripts/run_integration_tests_databricks` — attach to any cluster, run cells in order.
Uses `pytest.main()` in-process.

### What's skip-aware on Databricks

- `tests/conftest.py` `spark_session` fixture calls `create_delta_spark_session()` which
  auto-detects Databricks and returns the active runtime session.
- `tests/integration/test_demo.py` is skipped — it spawns a subprocess that can't access
  Spark Connect (legitimate limitation of subprocess execution model).
- Tests requiring `tablespec.session` or monkeypatching `pyspark.sql.functions` may need
  the `spark` extra installed (`pip install tablespec[spark]`) even on Databricks if they
  import internal modules that aren't satisfied by the runtime's pyspark alone.

### Building wheels

- `uv build` works on Databricks (no Spark dependency for building).
- Version override: `UV_DYNAMIC_VERSIONING_BYPASS=X.Y.Z uv build` (workspace FS has no git tags).

## File Reading Discipline

- Never read files larger than 200 lines at once.
- Never page through a file sequentially.
- Always identify candidate files with search before opening them.
- Limit exploration to 5 files before stopping for user approval.
