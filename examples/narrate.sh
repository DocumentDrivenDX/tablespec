#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
# Full pipeline: generate voice clips, record screencast with asciinema,
# convert to MP4, merge narration audio aligned to actual scene timestamps.
#
# Usage: bash examples/narrate.sh
# Requires: piper, ffmpeg, asciinema, agg
# Produces: examples/tablespec-demo-narrated.mp4
#           examples/tablespec-demo.cast (asciinema recording)
#           examples/tablespec-demo.gif

set -e
cd "$(dirname "$0")/.."

VOICE="/home/erik/.local/share/piper-voices/en_GB-cori-high.onnx"
WORK=$(mktemp -d)
trap "rm -rf $WORK" EXIT

# ─── Step 1: Generate voice clips and measure durations ──────────

echo "Step 1: Generating voice clips..."

declare -A CLIP_DUR

gen_clip() {
    local name="$1" text="$2"
    echo "$text" | piper --model "$VOICE" \
        --length-scale 1.05 \
        --sentence-silence 0.3 \
        --output_file "$WORK/${name}.wav" 2>/dev/null
    CLIP_DUR[$name]=$(ffprobe -v error -show_entries format=duration \
        -of csv=p=0 "$WORK/${name}.wav" | xargs printf "%.1f")
    printf "  %-14s %5ss\n" "$name" "${CLIP_DUR[$name]}"
}

gen_clip "intro"    "tablespec. Universal Metadata Format for table schemas. One YAML schema drives SQL, PySpark, JSON Schema, validation, and more."
gen_clip "yaml"     "This is a UMF schema for a healthcare claims table. Three columns, each with a data type and nullable configuration per Line of Business."
gen_clip "load"     "Load it into Python. Pydantic validates every field. The nullable config tells us which columns are required in which L.O.B."
gen_clip "generate" "From one UMF file, generate three schema formats. SQL DDL for data warehouses. PySpark StructType for Spark jobs. JSON Schema for API validation."
gen_clip "types"    "The type mapping engine converts between UMF, PySpark, JSON Schema, and Great Expectations. VARCHAR becomes StringType. DECIMAL stays DECIMAL with precision preserved."
gen_clip "domains"  "42 domain types ship built in. Feed it a column name like provider NPI and it recognizes it as a National Provider Identifier with 100% confidence. It even knows the validation rule."
gen_clip "gx"       "Generate a full Great Expectations suite deterministically from metadata alone. 13 expectations covering column existence, types, nullability, and length constraints."
gen_clip "prompts"  "Generate structured prompts for LLMs. Documentation prompts. Validation rule prompts. All the column metadata and domain context is included automatically."
gen_clip "diff"     "Schema evolution tracking. Modify a table and see exactly what changed. Added columns. Modified descriptions."
gen_clip "sql_plan" "Generate full SQL execution plans from UMF metadata. Joins, column derivations, survivorship logic, aggregations. All computed automatically from the schema relationships."
gen_clip "context"  "Context-aware validation. Different nullable rules for each Line of Business, all from one YAML file."
gen_clip "compat"   "Schema evolution safety. Check backward compatibility before deploying changes."
gen_clip "excel"    "Export to Excel for domain experts. Import their edits back with no data loss."
gen_clip "cli"      "CLI commands for schema authoring. Add a column, modify its type, rename it with alias preservation. Assign domain types from the built-in registry. And manage validation expectations — all without touching YAML directly."
gen_clip "spark_session"   "Now we enter PySpark territory. Creating a Spark session and a sample DataFrame with five claims."
gen_clip "spark_profile"   "SparkToUmfMapper infers a UMF schema from the DataFrame. Column names, types, and nullability, all detected automatically."
gen_clip "spark_validate"  "TableValidator checks the DataFrame against the UMF spec. It catches type drift that causes silent data corruption."
gen_clip "spark_sample"    "Sample data generation from UMF specs. 100 rows per table, respecting types, nullable rules, and domain constraints."
gen_clip "close"    "That's tablespec. Define once. Use everywhere."

echo

# ─── Step 2: Write clip durations for screencast.sh ──────────────

CLIP_ENV="/tmp/screencast_clip_durations.env"
cat > "$CLIP_ENV" << EOF
CLIP_intro=${CLIP_DUR[intro]}
CLIP_yaml=${CLIP_DUR[yaml]}
CLIP_load=${CLIP_DUR[load]}
CLIP_generate=${CLIP_DUR[generate]}
CLIP_types=${CLIP_DUR[types]}
CLIP_domains=${CLIP_DUR[domains]}
CLIP_gx=${CLIP_DUR[gx]}
CLIP_prompts=${CLIP_DUR[prompts]}
CLIP_diff=${CLIP_DUR[diff]}
CLIP_sql_plan=${CLIP_DUR[sql_plan]}
CLIP_context=${CLIP_DUR[context]}
CLIP_compat=${CLIP_DUR[compat]}
CLIP_excel=${CLIP_DUR[excel]}
CLIP_cli=${CLIP_DUR[cli]}
CLIP_spark_session=${CLIP_DUR[spark_session]}
CLIP_spark_profile=${CLIP_DUR[spark_profile]}
CLIP_spark_validate=${CLIP_DUR[spark_validate]}
CLIP_spark_sample=${CLIP_DUR[spark_sample]}
CLIP_close=${CLIP_DUR[close]}
EOF

# ─── Step 3: Record with asciinema (captures every frame) ────────

echo "Step 2: Recording with asciinema..."

CAST="examples/tablespec-demo.cast"
asciinema rec \
    --cols 120 --rows 40 \
    --command "bash examples/screencast.sh" \
    --overwrite \
    "$CAST" 2>/dev/null

CAST_DUR=$(python3 -c "
import json
with open('$CAST') as f:
    lines = f.readlines()
last_ts = 0
for line in lines[1:]:
    try:
        evt = json.loads(line)
        last_ts = evt[0]
    except: pass
print(f'{last_ts:.0f}')
")
echo "  Recorded: ${CAST}  (${CAST_DUR}s)"
echo

# ─── Step 2.5: Compress idle gaps in cast file ──────────────────

echo "Step 2.5: Compressing idle gaps (max 2s)..."

python3 -c "
import json
MAX_IDLE = 2.0
CAST = '$CAST'
with open(CAST) as f:
    lines = f.readlines()
header = lines[0]
events = [json.loads(l) for l in lines[1:]]
shift = 0
prev_orig = 0
for evt in events:
    orig_ts = evt[0]
    gap = orig_ts - prev_orig
    if gap > MAX_IDLE:
        shift += gap - MAX_IDLE
    evt[0] = round(orig_ts - shift, 6)
    prev_orig = orig_ts
with open(CAST, 'w') as f:
    f.write(header)
    for evt in events:
        f.write(json.dumps(evt) + '\n')
print(f'  Compressed: removed {shift:.1f}s of idle time')
last_ts = events[-1][0] if events else 0
print(f'  New duration: {last_ts:.0f}s')
"

# Apply same compression to timing log
python3 -c "
import json
MAX_IDLE = 2.0
CAST = '$CAST'
TIMING_LOG = '/tmp/screencast_timing.log'

# Rebuild the same shift table from the cast
with open(CAST) as f:
    lines = f.readlines()
# The cast is already compressed, but we need the original timestamps
# to compute shifts. Re-read to get compressed timestamps.
# Instead, compress the timing log offsets using the same algorithm.

with open(TIMING_LOG) as f:
    tlines = f.readlines()
start_epoch = tlines[0].strip()

# Collect all offsets
entries = []
for line in tlines[1:]:
    parts = line.strip().split()
    if len(parts) == 2:
        entries.append((parts[0], float(parts[1])))

# Apply same gap compression
shift = 0
prev_orig = 0
compressed_entries = []
for name, offset in entries:
    gap = offset - prev_orig
    if gap > MAX_IDLE:
        shift += gap - MAX_IDLE
    compressed_entries.append((name, round(offset - shift, 2)))
    prev_orig = offset

# Write back
with open(TIMING_LOG, 'w') as f:
    f.write(start_epoch + '\n')
    for name, offset in compressed_entries:
        f.write(f'{name} {offset}\n')
print('  Timing log compressed to match')
"
echo

# ─── Step 4: Convert to GIF and MP4 ─────────────────────────────

echo "Step 3: Converting to GIF and MP4..."

GIF="examples/tablespec-demo.gif"
MP4="examples/tablespec-demo.mp4"

agg --font-family "JetBrainsMono Nerd Font" \
    --font-size 16 \
    --theme asciinema \
    "$CAST" "$GIF" 2>/dev/null

# Convert GIF to MP4
ffmpeg -y -i "$GIF" \
    -movflags faststart \
    -pix_fmt yuv420p \
    -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" \
    "$MP4" 2>/dev/null

VID_DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$MP4" | xargs printf "%.0f")
echo "  GIF: $(du -h "$GIF" | cut -f1)"
echo "  MP4: $(du -h "$MP4" | cut -f1)  (${VID_DUR}s)"
echo

# ─── Step 5: Read actual scene timestamps ────────────────────────

echo "Step 4: Reading scene timestamps..."

TIMING_LOG="/tmp/screencast_timing.log"
if [[ ! -f "$TIMING_LOG" ]]; then
    echo "  ERROR: $TIMING_LOG not found"
    exit 1
fi

echo "  Scene offsets:"
while read -r scene offset; do
    [[ -z "$scene" ]] && continue
    printf "    %-14s %6.1fs\n" "$scene" "$offset"
done < <(tail -n +2 "$TIMING_LOG")
echo

# ─── Step 6: Build narration audio aligned to timestamps ─────────

echo "Step 5: Building narration audio..."

ffmpeg -y -f lavfi -i "anullsrc=r=22050:cl=mono" -t "$VID_DUR" "$WORK/silence.wav" 2>/dev/null

INPUTS="-i $WORK/silence.wav"
FILTER=""
IDX=1

add_seg() {
    local name="$1" offset_s="$2"
    [[ ! -f "$WORK/${name}.wav" ]] && return
    local offset_ms
    offset_ms=$(python3 -c "print(int($offset_s * 1000))")
    INPUTS="$INPUTS -i $WORK/${name}.wav"
    FILTER="${FILTER}[${IDX}]adelay=${offset_ms}|${offset_ms}[a${IDX}];"
    printf "  %-14s at %6.1fs  (clip: %ss)\n" "$name" "$offset_s" "${CLIP_DUR[$name]}"
    IDX=$((IDX + 1))
}

while read -r scene offset; do
    [[ -z "$scene" || "$scene" == "end" ]] && continue
    add_seg "$scene" "$offset"
done < <(tail -n +2 "$TIMING_LOG")

LAST=$((IDX - 1))
MIX="[0]"
for i in $(seq 1 $LAST); do
    MIX="${MIX}[a${i}]"
done
FILTER="${FILTER}${MIX}amix=inputs=$((LAST + 1)):normalize=0"

echo "  Mixing ${LAST} segments..."
ffmpeg -y $INPUTS -filter_complex "$FILTER" "$WORK/narration.wav" 2>/dev/null

# ─── Step 7: Merge narration with video ──────────────────────────

echo "Step 6: Merging narration with video..."

OUTPUT="examples/tablespec-demo-narrated.mp4"
ffmpeg -y -i "$MP4" -i "$WORK/narration.wav" \
    -c:v copy -c:a aac -b:a 128k \
    -map 0:v:0 -map 1:a:0 \
    -shortest \
    "$OUTPUT" 2>/dev/null

SIZE=$(du -h "$OUTPUT" | cut -f1)
FINAL_DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUTPUT" | xargs printf "%.0f")
echo
echo "Done!"
echo "  $CAST               (asciinema — scrollback + copy/paste)"
echo "  $GIF    (animated GIF)"
echo "  $MP4    (silent MP4)"
echo "  $OUTPUT (narrated MP4, ${SIZE}, ${FINAL_DUR}s)"
