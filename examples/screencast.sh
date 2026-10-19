#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
# tablespec screencast — the "director" script
#
# Records identically under VHS and asciinema.
# Writes scene timestamps to /tmp/screencast_timing.log
# so narrate.sh can align voice clips to exact times.

set -e
cd "$(dirname "$0")/.."

# Source clip durations if available (written by narrate.sh)
CLIP_TIMING="/tmp/screencast_clip_durations.env"
[[ -f "$CLIP_TIMING" ]] && source "$CLIP_TIMING"

GREEN='\033[1;32m'
CYAN='\033[1;36m'
DIM='\033[2m'
RESET='\033[0m'
TIMING_LOG="/tmp/screencast_timing.log"
START_EPOCH=$(date +%s.%N)

echo "$START_EPOCH" > "$TIMING_LOG"

mark() {
    # Log scene name and elapsed seconds since start
    local now
    now=$(date +%s.%N)
    local elapsed
    elapsed=$(python3 -c "print(f'{$now - $START_EPOCH:.2f}')")
    echo "$1 $elapsed" >> "$TIMING_LOG"
}

narrate() {
    printf "${CYAN}"
    local text="$1"
    for ((i=0; i<${#text}; i++)); do
        printf "%s" "${text:$i:1}"
        sleep 0.02
    done
    printf "${RESET}\n"
}

divider() {
    printf "${DIM}─%.0s${RESET}" {1..60}
    echo
}

run() {
    printf "${GREEN}\$ %s${RESET}\n" "$*"
    "$@"
}

wait_for_clip() {
    # Pause so the voice clip can finish playing.
    # Uses a subtle cursor blink to prevent VHS from dropping idle frames.
    # $1 = clip duration in seconds
    # $2 = estimated time already elapsed (typing + command)
    local clip_dur="${1:-5}"
    local elapsed="${2:-3}"
    local remaining
    remaining=$(python3 -c "print(max($clip_dur - $elapsed + 1, 2))")
    local ticks
    ticks=$(python3 -c "print(int($remaining / 0.5))")
    for ((t=0; t<ticks; t++)); do
        printf "\r\033[K"  # carriage return + clear line (invisible activity)
        sleep 0.5
    done
}

# ─── Title ────────────────────────────────────────────────────────

clear
echo
mark "intro"
narrate "tablespec — Universal Metadata Format for table schemas"
narrate "One YAML schema drives SQL, PySpark, JSON Schema, validation, and more."
echo
wait_for_clip "${CLIP_intro:-6}" 3

# ─── Scene 1: YAML ───────────────────────────────────────────────

divider
mark "yaml"
narrate "Let's start with a UMF schema. This defines a healthcare claims table."
echo
run cat examples/schema.yaml
wait_for_clip "${CLIP_yaml:-5}" 2

# ─── Scene 2: Load ───────────────────────────────────────────────

divider
mark "load"
narrate "Load it into Python. Pydantic validates every field."
echo
run uv run python examples/scene.py load
wait_for_clip "${CLIP_load:-5}" 3

# ─── Scene 3: Generate ───────────────────────────────────────────

divider
mark "generate"
narrate "Generate SQL DDL, PySpark StructType, and JSON Schema — all from one UMF."
echo
run uv run python examples/scene.py generate
wait_for_clip "${CLIP_generate:-8}" 4

# ─── Scene 4: Types ──────────────────────────────────────────────

divider
mark "types"
narrate "Every UMF type maps to PySpark, JSON, and Great Expectations."
echo
run uv run python examples/scene.py types
wait_for_clip "${CLIP_types:-7}" 3

# ─── Scene 5: Domains ────────────────────────────────────────────

divider
mark "domains"
narrate "42 domain types. Feed it a column name and it infers the type automatically."
echo
run uv run python examples/scene.py domains
wait_for_clip "${CLIP_domains:-8}" 4

# ─── Scene 6: GX ─────────────────────────────────────────────────

divider
mark "gx"
narrate "Generate a full Great Expectations suite — deterministically, from metadata alone."
echo
run uv run python examples/scene.py gx
wait_for_clip "${CLIP_gx:-7}" 4

# ─── Scene 7: Prompts ────────────────────────────────────────────

divider
mark "prompts"
narrate "Generate structured prompts for LLMs to write documentation or validation rules."
echo
run uv run python examples/scene.py prompts
wait_for_clip "${CLIP_prompts:-7}" 4

# ─── Scene 8: Diff ───────────────────────────────────────────────

divider
mark "diff"
narrate "Schema evolution tracking. Modify a table, see exactly what changed."
echo
run uv run python examples/scene.py diff
wait_for_clip "${CLIP_diff:-5}" 3

# ─── Scene 9: Context-Aware Nullable ─────────────────────────────

divider
mark "context"
narrate "Context-aware validation. Different rules for each LOB, all from one YAML."
echo
run uv run python examples/scene.py context
wait_for_clip "${CLIP_context:-6}" 3

# ─── Scene 10: Compatibility Checking ────────────────────────────

divider
mark "compat"
narrate "Schema evolution safety. Check backward compatibility before deploying changes."
echo
run uv run python examples/scene.py compat
wait_for_clip "${CLIP_compat:-6}" 3

# ─── Scene 11: Excel Round-Trip ──────────────────────────────────

divider
mark "excel"
narrate "Export to Excel for domain experts. Import their edits back — no data loss."
echo
run uv run python examples/scene.py excel
wait_for_clip "${CLIP_excel:-5}" 3

# ─── Scene 12: SQL Plan Generation ───────────────────────────────

divider
mark "sql_plan"
narrate "Generate full SQL execution plans from UMF — joins, derivations, survivorship, all automatic."
echo
run uv run python examples/scene.py sql_plan
wait_for_clip "${CLIP_sql_plan:-8}" 4

# ─── Scene 13: CLI Mutations ──────────────────────────────────────

divider
mark "cli"
narrate "CLI commands for schema authoring. Add, modify, rename columns. Set domain types. Manage validation rules."
echo
run uv run python examples/scene.py cli
wait_for_clip "${CLIP_cli:-10}" 8

# ─── Scene 14: Spark ─────────────────────────────────────────────

divider
mark "spark_session"
narrate "Starting a Spark session and creating a sample DataFrame."
echo
printf "${GREEN}\$ uv run python examples/scene.py spark${RESET}\n"

uv run python examples/scene.py spark 2>/dev/null | while IFS= read -r line; do
    case "$line" in
        "###MARK:"*"###")
            scene_name="${line#\#\#\#MARK:}"
            scene_name="${scene_name%\#\#\#}"
            mark "$scene_name"
            ;;
        *)
            printf '%s\n' "$line"
            ;;
    esac
done

wait_for_clip "${CLIP_spark_sample:-10}" 5

# ─── Close ────────────────────────────────────────────────────────

divider
echo
mark "close"
narrate "That's tablespec. Define once, use everywhere."
echo
wait_for_clip "${CLIP_close:-3}" 2

mark "end"
