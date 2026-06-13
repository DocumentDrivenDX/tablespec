# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — EDGAR plumbing: fetch, chunk, embed, and land SEC 10-K data
# MAGIC
# MAGIC **Consumer-side plumbing for the tablespec SEC 10-K demo (US-045).**
# MAGIC
# MAGIC Acquires a small set of 10-K filings from SEC EDGAR with a declared
# MAGIC `User-Agent` and rate limiting per the SEC fair-access policy; extracts
# MAGIC plain text; chunks it; and embeds each chunk — via the
# MAGIC `databricks-gte-large-en` Foundation Model API endpoint or a
# MAGIC deterministic fake (widget-selected).  Also fetches the XBRL companyfacts
# MAGIC JSON for the same companies.  Both datasets land in a Unity Catalog volume.
# MAGIC
# MAGIC tablespec itself never does any of this: parsing, chunking, and embedding
# MAGIC calls are permanently consumer plumbing (CORP-05 / PRD Non-Goal).
# MAGIC Notebook 02 (`02-sec10k-tablespec-demo`) runs the tablespec story —
# MAGIC spec, validate, workbooks, artifacts, staged validation scorecard — and
# MAGIC its output is identical regardless of which embedding mode was used here.
# MAGIC
# MAGIC **Widgets**
# MAGIC - `embedding_mode` — `fake` (default) uses deterministic seeded unit vectors
# MAGIC   (no endpoint required); `real` calls `databricks-gte-large-en`.
# MAGIC - `output_catalog` — Unity Catalog catalog for output (default `main`).
# MAGIC - `output_schema` — UC schema (default `sec_10k_demo`).
# MAGIC - `output_volume` — UC volume name (default `raw`).
# MAGIC - `wheel_path` — path/glob to the tablespec wheel (empty = preinstalled).
# MAGIC
# MAGIC **SEC EDGAR fair-access policy**
# MAGIC - Declared `User-Agent` required on every request
# MAGIC   (`Organization Name email@example.com` format).
# MAGIC - Automated traffic limited to 10 requests per second.
# MAGIC - Small fixed company set keeps the demo polite and fast.

# COMMAND ----------

dbutils.widgets.dropdown(
    "embedding_mode", "fake", ["fake", "real"],
    "Embedding mode (fake = deterministic, real = databricks-gte-large-en)"
)
dbutils.widgets.text("output_catalog", "main", "Unity Catalog catalog")
dbutils.widgets.text("output_schema", "sec_10k_demo", "UC schema")
dbutils.widgets.text("output_volume", "raw", "UC volume name")
dbutils.widgets.text("wheel_path", "", "tablespec wheel path/glob (empty = preinstalled)")

# COMMAND ----------

import glob as _glob

_wheel_widget = dbutils.widgets.get("wheel_path").strip()
if _wheel_widget:
    _matches = sorted(_glob.glob(_wheel_widget)) or [_wheel_widget]
    _wheel = _matches[-1]
    print(f"installing {_wheel}")
    %pip install --quiet {_wheel}
    dbutils.library.restartPython()
else:
    print("wheel_path empty — assuming tablespec is already installed")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Config and helpers

# COMMAND ----------

import hashlib
import json
import math
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

EMBEDDING_MODE = dbutils.widgets.get("embedding_mode").strip()
UC_CATALOG = dbutils.widgets.get("output_catalog").strip() or "main"
UC_SCHEMA = dbutils.widgets.get("output_schema").strip() or "sec_10k_demo"
UC_VOLUME = dbutils.widgets.get("output_volume").strip() or "raw"

VOLUME_BASE = Path(f"/Volumes/{UC_CATALOG}/{UC_SCHEMA}/{UC_VOLUME}")
CORPUS_DELTA_PATH = str(VOLUME_BASE / "sec_10k_corpus")
FACTS_JSONL_PATH = str(VOLUME_BASE / "sec_xbrl_facts" / "companyfacts.jsonl")

EMBEDDING_DIM = 1024
CHUNK_WORDS = 300
CHUNK_OVERLAP = 30
MAX_CHUNKS_PER_FILING = 25

# Small fixed company set — keeps the demo fast and polite to EDGAR.
# CIKs are zero-padded to 10 digits for EDGAR API paths.
COMPANIES = [
    ("Microsoft",   "0000789019"),
    ("Apple",       "0000320193"),
    ("Tesla",       "0001318605"),
]

# Required by SEC EDGAR fair-access policy.
EDGAR_USER_AGENT = "Telepath Data sec-10k-demo@example.com"
EDGAR_RATE_LIMIT_RPS = 10  # max requests per second

print(f"embedding mode : {EMBEDDING_MODE}")
print(f"volume base    : {VOLUME_BASE}")
print(f"corpus path    : {CORPUS_DELTA_PATH}")
print(f"facts path     : {FACTS_JSONL_PATH}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Rate-limited EDGAR fetch

# COMMAND ----------

_last_request_time: float = 0.0


def edgar_get(url: str, *, stream: bool = False) -> requests.Response:
    """Fetch a URL from SEC EDGAR with User-Agent and rate limiting."""
    global _last_request_time
    gap = 1.0 / EDGAR_RATE_LIMIT_RPS
    wait = gap - (time.monotonic() - _last_request_time)
    if wait > 0:
        time.sleep(wait)
    resp = requests.get(
        url,
        headers={"User-Agent": EDGAR_USER_AGENT, "Accept-Encoding": "gzip, deflate"},
        timeout=30,
        stream=stream,
    )
    _last_request_time = time.monotonic()
    resp.raise_for_status()
    return resp


def cik_url(cik: str, endpoint: str) -> str:
    """Build an SEC EDGAR data URL for a given CIK and endpoint suffix."""
    return f"https://data.sec.gov/{endpoint.lstrip('/')}"


# COMMAND ----------

# MAGIC %md
# MAGIC ## Text extraction and chunking helpers

# COMMAND ----------

_HTML_TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")


def strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    no_tags = _HTML_TAG_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", no_tags).strip()


def chunk_text(
    text: str,
    words_per_chunk: int = CHUNK_WORDS,
    overlap: int = CHUNK_OVERLAP,
    max_chunks: int = MAX_CHUNKS_PER_FILING,
) -> list[str]:
    """Split text into overlapping word windows.

    Returns at most *max_chunks* chunks so the demo stays small.
    """
    words = text.split()
    if not words:
        return []
    step = max(1, words_per_chunk - overlap)
    chunks = []
    i = 0
    while i < len(words) and len(chunks) < max_chunks:
        chunk = " ".join(words[i : i + words_per_chunk])
        if chunk:
            chunks.append(chunk)
        i += step
    return chunks


# COMMAND ----------

# MAGIC %md
# MAGIC ## Embedding: fake (deterministic) and real (Foundation Model API)

# COMMAND ----------


def _fake_embedding(text: str, dimension: int = EMBEDDING_DIM) -> list[float]:
    """Deterministic seeded unit vector — same algorithm as generators.generate_embedding().

    Seed is derived from the chunk text, so identical input → identical vector
    across runs. This keeps notebook 02's tablespec story identical to the real
    endpoint path (DEMO-02 / AC4 — no model coupling in the spec).
    """
    seed_material = f"{text!r}:{dimension}"
    digest = hashlib.sha256(seed_material.encode("utf-8")).digest()
    seed_value = int.from_bytes(digest[:8], "big", signed=False)
    rng = random.Random(seed_value)
    values = [rng.uniform(-1.0, 1.0) for _ in range(dimension)]
    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0.0:
        values[0] = 1.0
        norm = 1.0
    return [round(v / norm, 8) for v in values]


def _real_embedding(texts: list[str]) -> list[list[float]]:
    """Call databricks-gte-large-en via the Foundation Model API (batch).

    Requires FM API access on this workspace.  Raises clearly if the endpoint
    is unavailable — switch to embedding_mode=fake to run without it.
    """
    import mlflow.deployments

    client = mlflow.deployments.get_deploy_client("databricks")
    response = client.predict(
        endpoint="databricks-gte-large-en",
        inputs={"input": texts},
    )
    return [item["embedding"] for item in response["data"]]


def embed_chunks(
    chunks: list[str],
    mode: str = EMBEDDING_MODE,
    batch_size: int = 32,
) -> list[list[float]]:
    """Embed a list of text chunks using the selected mode.

    fake — deterministic seeded unit vectors (no endpoint).
    real — databricks-gte-large-en via the FM API (batched).
    """
    if mode == "fake":
        return [_fake_embedding(chunk) for chunk in chunks]

    embeddings = []
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        embeddings.extend(_real_embedding(batch))
        time.sleep(0.1)  # gentle pacing between real batches
    return embeddings


MODEL_NAME = (
    "fake-deterministic-1024"
    if EMBEDDING_MODE == "fake"
    else "databricks-gte-large-en"
)
print(f"embedding model (provenance value): {MODEL_NAME}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Fetch 10-K filings from EDGAR

# COMMAND ----------


def fetch_latest_10k_url(cik: str) -> tuple[str, str] | None:
    """Return (accession_number, filing_index_url) for the most recent 10-K.

    Returns None if no 10-K is found in the last 5 years of filings.
    """
    submissions_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    data = edgar_get(submissions_url).json()
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    for form, acc, doc in zip(forms, accessions, primary_docs):
        if form == "10-K":
            acc_path = acc.replace("-", "")
            url = (
                f"https://www.sec.gov/Archives/edgar/data/"
                f"{int(cik)}/{acc_path}/{doc}"
            )
            return acc, url
    return None


def fetch_filing_text(url: str, max_bytes: int = 512 * 1024) -> str:
    """Fetch the filing document and return plain text (HTML stripped).

    Caps at *max_bytes* to keep the demo fast — 10-K filings can be large.
    """
    resp = edgar_get(url)
    raw = resp.text[:max_bytes]
    return strip_html(raw)


print("fetching 10-K filing URLs...")
filing_info: list[tuple[str, str, str, str]] = []  # (company, cik, accession, url)

for company, cik in COMPANIES:
    result = fetch_latest_10k_url(cik)
    if result is None:
        print(f"  {company} ({cik}): no 10-K found — skipping")
        continue
    accession, url = result
    filing_info.append((company, cik, accession, url))
    print(f"  {company} ({cik}): {url[:80]}...")

print(f"\nfound {len(filing_info)} 10-K filings")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Chunk, embed, and build corpus rows

# COMMAND ----------

ACQUIRED_AT = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

corpus_rows: list[dict[str, Any]] = []

for company, cik, accession, url in filing_info:
    print(f"\nprocessing {company}...")
    text = fetch_filing_text(url)
    chunks = chunk_text(text)
    print(f"  {len(chunks)} chunks from {len(text):,} chars of plain text")

    vectors = embed_chunks(chunks)
    doc_id = f"{cik}-{accession.replace('-', '')}"

    for idx, (chunk, vector) in enumerate(zip(chunks, vectors)):
        chunk_id = f"{doc_id}:{idx:04d}"
        corpus_rows.append(
            {
                "doc_id": doc_id,
                "chunk_id": chunk_id,
                "source_path": url,
                "chunk_index": idx,
                "text": chunk,
                "embedding": vector,
                "embedding_model": MODEL_NAME,
                "acquired_at": ACQUIRED_AT,
            }
        )

print(f"\ncorpus: {len(corpus_rows)} rows total")
print(f"sample doc_id  : {corpus_rows[0]['doc_id']}")
print(f"sample chunk_id: {corpus_rows[0]['chunk_id']}")
print(f"embedding dim  : {len(corpus_rows[0]['embedding'])} (expected {EMBEDDING_DIM})")
assert all(len(r["embedding"]) == EMBEDDING_DIM for r in corpus_rows), (
    f"embedding dimension mismatch — expected {EMBEDDING_DIM}"
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write corpus to Delta

# COMMAND ----------

from pyspark.sql.types import (
    ArrayType,
    FloatType,
    IntegerType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

CORPUS_SCHEMA = StructType(
    [
        StructField("doc_id", StringType(), False),
        StructField("chunk_id", StringType(), False),
        StructField("source_path", StringType(), False),
        StructField("chunk_index", IntegerType(), False),
        StructField("text", StringType(), False),
        StructField("embedding", ArrayType(FloatType()), True),
        StructField("embedding_model", StringType(), False),
        StructField("acquired_at", StringType(), False),
    ]
)

corpus_df = spark.createDataFrame(corpus_rows, schema=CORPUS_SCHEMA)
corpus_df.write.format("delta").mode("overwrite").option(
    "overwriteSchema", "true"
).save(CORPUS_DELTA_PATH)

print(f"corpus written to {CORPUS_DELTA_PATH}")
display(corpus_df.select("doc_id", "chunk_id", "chunk_index", "embedding_model").limit(6))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Fetch XBRL companyfacts and write as JSONL

# COMMAND ----------

facts_dir = Path(FACTS_JSONL_PATH).parent
facts_dir.mkdir(parents=True, exist_ok=True)

print("fetching XBRL companyfacts...")
facts_rows: list[str] = []

for company, cik in COMPANIES:
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    data = edgar_get(url).json()
    row = {"cik": data["cik"], "entityName": data["entityName"]}
    facts_rows.append(json.dumps(row))
    print(f"  {company}: cik={data['cik']}, entityName={data['entityName']!r}")

Path(FACTS_JSONL_PATH).write_text("\n".join(facts_rows) + "\n")
print(f"\ncompanyfacts written to {FACTS_JSONL_PATH} ({len(facts_rows)} rows)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Handoff
# MAGIC
# MAGIC Run `02-sec10k-tablespec-demo` on this cluster.  Pass the same widget
# MAGIC values (`output_catalog`, `output_schema`, `output_volume`) so notebook 02
# MAGIC reads from the paths this notebook just wrote.
# MAGIC
# MAGIC The tablespec story in notebook 02 is **identical** regardless of which
# MAGIC embedding mode was used here — specs carry no endpoint, credential, or model
# MAGIC coupling (US-045 AC4).

# COMMAND ----------

print("READY")
print(f"  corpus delta   : {CORPUS_DELTA_PATH}")
print(f"  facts jsonl    : {FACTS_JSONL_PATH}")
print(f"  embedding mode : {EMBEDDING_MODE}")
print(f"  corpus rows    : {len(corpus_rows)}")
print(f"  facts rows     : {len(facts_rows)}")
dbutils.notebook.exit(
    json.dumps(
        {
            "status": "READY",
            "corpus_path": CORPUS_DELTA_PATH,
            "facts_path": FACTS_JSONL_PATH,
            "embedding_mode": EMBEDDING_MODE,
            "corpus_rows": len(corpus_rows),
            "facts_rows": len(facts_rows),
        }
    )
)
