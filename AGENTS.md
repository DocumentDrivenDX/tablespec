# Agent Instructions

This project uses **DDx beads** for issue tracking. Run `ddx bead ready` to find available work.

## Quick Reference

```bash
ddx bead ready             # Find available work
ddx bead ready --execution # Find execution-safe work
ddx bead show <id>         # View issue details
ddx bead update <id> --claim  # Claim work
ddx bead close <id>        # Complete work
ddx bead status            # Tracker health
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
## Issue Tracking with DDx Beads

**IMPORTANT**: This project uses **DDx beads** for ALL issue tracking. Do NOT use markdown TODOs, task lists, or other tracking methods.

### Why DDx beads?

- Dependency-aware: Track blockers and relationships between issues
- Version-controlled: Stored in `.ddx/beads.jsonl`
- Agent-optimized: JSON output, ready work detection, discovered-from links
- Prevents duplicate tracking systems and confusion

### Quick Start

**Check for ready work:**

```bash
ddx bead ready --json
```

**Create new issues:**

```bash
ddx bead create "Issue title" --description "Detailed context" --type bug --priority 1
ddx bead create "Issue title" --description "What this issue is about" --priority 1 --depends-on <parent-id>
```

**Claim and update:**

```bash
ddx bead update <id> --claim
ddx bead update <id> --priority 1
```

**Complete work:**

```bash
ddx bead close <id>
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

1. **Check ready work**: `ddx bead ready` shows unblocked issues
2. **Claim your task**: `ddx bead update <id> --claim`
3. **Work on it**: Implement, test, document
4. **Discover new work?** Create linked issue:
   - `ddx bead create "Found bug" --description "Details about what was found" --priority 1 --depends-on <parent-id>`
5. **Complete**: `ddx bead close <id>`

### Important Rules

- ✅ Use DDx beads for ALL task tracking
- ✅ Use `--json` when supported for programmatic reads
- ✅ Link discovered work with explicit dependencies or parent relationships
- ✅ Check `ddx bead ready` before asking "what should I work on?"
- ❌ Do NOT create markdown TODO lists
- ❌ Do NOT use external issue trackers
- ❌ Do NOT duplicate tracking systems

For more details, run `ddx bead --help`.

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
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

<!-- DDX-AGENTS:START -->
<!-- Managed by ddx init / ddx update. Edit outside these markers. -->

# DDx

This project uses [DDx](https://github.com/DocumentDrivenDX/ddx) for
document-driven development. Use the `ddx` skill for beads, work,
review, agents, and status — every skills-compatible harness (Claude
Code, OpenAI Codex, Gemini CLI, etc.) discovers it from
`.claude/skills/ddx/` and `.agents/skills/ddx/`.

## Default Interactive Mode

Broad conversational DDx prompts — queue orientation, planning, review,
guidance folding, spec alignment, and bead breakdown — use
`interactive-steward` / `queue_steward`. Explicit worker commands
(`ddx work`, `ddx try <id>`, "execute bead `<id>`") route to
`bead_execution`. Explicit code/doc edit requests route to
`direct_user_implementation`. Explicit review-only requests route to
`review`.

`DDX_MODE=bead_execution` overrides only the interactive queue-steward default.
It **never** overrides tracker, merge, commit, safety, or verification policy —
those apply in every mode.

### Mutation policy

- **read / plan / fresh-eyes review / fold guidance / align specs** — non-mutating
  by default; no tracker writes, no code edits.
- **Tracker mutation** (e.g. `ddx bead create`, `ddx bead update`) requires an
  explicit durable-output verb: "create a bead", "file this as work",
  "break down into beads".
- **Code edits** require explicit implementation intent ("fix this",
  "implement X") or `bead_execution` mode.

## Files to commit

After modifying any of these paths, stage and commit them:

- `.ddx/beads.jsonl` — work item tracker
- `.ddx/config.yaml` — project configuration
- `.agents/skills/ddx/` — the ddx skill (shipped by ddx init)
- `.claude/skills/ddx/` — same skill, Claude Code location
- `docs/` — project documentation and artifacts

## Conventions

- Use `ddx bead` for work tracking (not custom issue files).
- Documents with `ddx:` frontmatter are tracked in the document graph.
- Run `ddx doctor` to check environment health.
- Run `ddx doc stale` to find documents needing review.

## The Databricks App: `apps/data-profiling/`

A Streamlit Databricks App maintained in this repository — first-party code under
the same Apache-2.0 license as the library. `NOTICE` records that it began life in
a separate repository.

- **Formatting:** `ruff format` covers it, like everything else.
- **Tests:** its 258 tests run in `make test` and CI, wired in via `testpaths` +
  `pythonpath` in the root `pyproject.toml`. Note `apps/data-profiling/tests/` is
  deliberately **not a package** — a second top-level `tests` package would shadow
  this repo's own.
- **Lint / type-check:** `make lint` and pyright still scope to `src/` (+ `scripts/`).
  `ruff check apps/` is not yet clean; bringing it under those gates is open work.
- It has its own `CLAUDE.md` with its own conventions (e.g. no emojis in code).
  Honor those inside that tree.
- Library changes it depends on belong in `src/tablespec/`, not in the app.
- See `docs/guide/data-profiling-app.md` for architecture and deployment.

## Merge Policy

Branches containing `ddx try` or `ddx work` commits
carry a per-attempt execution audit trail:

- `chore: update tracker (execute-bead <TIMESTAMP>)` — attempt heartbeats
- `Merge bead <bead-id> attempt <TIMESTAMP>- into <branch>` — successful lands
- `feat|fix|...: ... [ddx-<id>]` — substantive bead work

Bead records store `closing_commit_sha` pointers into this history. Any
SHA rewrite breaks the trail. **Never squash, rebase, or filter** these
branches. Use only:

- `git merge --ff-only` when the target is a strict ancestor, or
- `git merge --no-ff` when divergence exists

Forbidden on execute-bead branches: `gh pr merge --squash`,
`gh pr merge --rebase`, `git rebase -i` with fixup/squash/drop,
`git filter-branch`, `git filter-repo`, and `git commit --amend` on
any commit already in the trail.
<!-- DDX-AGENTS:END -->
