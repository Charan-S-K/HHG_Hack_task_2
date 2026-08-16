# Data Handoff Details — RUN 2 Update

This file describes how to reproduce and re-verify the local dataset subset and
all persisted indexes used in **HH Goa Voice Radar** (RUN 1 and RUN 2).

---

## RUN 1 — Original Dataset Subset

### Reproduction Instructions

To reproduce the exact subset stored in `data/subset.jsonl`:

1. **Source Dataset**: `ai4bharat/MSMARCO-XI` on Hugging Face.
2. **Split**: `validation` (retrieved from raw parquet path `validation/hinval.parquet`).
3. **Hugging Face Commit / Revision**: `bf5cdc1f26e581e519018e434db14edd1b77602b`
4. **Sampling Parameters**:
    * **Seed Value**: `42`
    * **Candidate Range**: The first `500` records in the stream.
    * **Final Sample Size**: `100` records sampled from the candidate range.
5. **Target File**: Saved as a JSONL file at `data/subset.jsonl`.

### Regeneration Command

```bash
python3 scratch/sample_local_parquet.py
```

*Note: The intermediate raw `hinval.parquet` is deleted after sampling.*

### Index Rebuilding (RUN 1 Baseline / "fixed" strategy)

* **Re-indexing Date**: 2026-08-14
* **Vector Database**: FAISS (IndexFlatL2)
* **Dimensions**: 384
* **Embedding Model**: `intfloat/multilingual-e5-small`
* **New location (RUN 2)**: `data/faiss_index/fixed/index.faiss`
  (migrated from `data/faiss_index/index.faiss` at server startup automatically)

---

## RUN 2 — Multi-Strategy Indexes

RUN 2 adds **three additional chunking strategies**, each with its own
persisted FAISS index. All four strategies index the **same committed
`data/subset.jsonl`** from RUN 1 — no re-sampling is performed.

### Index Locations

| Strategy   | Index path                            | Metadata path                              |
|------------|---------------------------------------|--------------------------------------------|
| `fixed`    | `data/faiss_index/fixed/index.faiss`  | `data/faiss_index/fixed/metadata.json`     |
| `sentence` | `data/faiss_index/sentence/index.faiss` | `data/faiss_index/sentence/metadata.json` |
| `metadata` | `data/faiss_index/metadata/index.faiss` | `data/faiss_index/metadata/metadata.json` |
| `hybrid`   | `data/faiss_index/hybrid/index.faiss` | `data/faiss_index/hybrid/metadata.json`    |

### Regeneration Commands

```bash
# Build all four strategy indexes at once (recommended):
python -m backend.vector_store.indexer --strategy all --force

# Build a single strategy:
python -m backend.vector_store.indexer --strategy hybrid --force
python -m backend.vector_store.indexer --strategy sentence --force
python -m backend.vector_store.indexer --strategy metadata --force
python -m backend.vector_store.indexer --strategy fixed --force
```

### Git / LFS Status

* `data/subset.jsonl` — committed directly (~1.2 MB, within Git size limits)
* `data/faiss_index/fixed/index.faiss` — committed directly (~1.7 MB)
* `data/faiss_index/*/metadata.json` — committed directly (small JSON files)
* `data/faiss_index/sentence/index.faiss`, `metadata/index.faiss`, `hybrid/index.faiss` —
  generated locally; if too large for Git direct commit, regenerate using commands above.

---

## RUN 2 — Benchmark Query Set

The benchmark harness samples queries directly from `data/subset.jsonl`:

| Parameter      | Value                                   |
|----------------|-----------------------------------------|
| Source file    | `data/subset.jsonl`                     |
| Query field    | `query` (Hindi, native dataset language) |
| Seed           | `42` (same as RUN 1)                    |
| Sample size    | Up to 100 queries (all 100 if available) |
| Reproducibility | `random.Random(42).sample(queries, 100)` |

**Note**: The benchmark query set is naturally Hindi-only (the dataset's native
query field is Hindi). This is expected and intentional — the benchmark tests
retrieval and generation latency, not multilingual coverage.

Results are saved to: `data/benchmark_results.json`

---

## Embedding Model (unchanged from RUN 1)

* **Model**: `intfloat/multilingual-e5-small`
* **Dimensions**: 384
* **Prefixes**: `query: ` for queries, `passage: ` for indexed passages
* **Rationale**: Genuine multilingual support for Devanagari and other Indian scripts

---

## Production Default Strategy

The **hybrid** strategy is the production default (set in `config.py` and `.env`).
See `RETRIEVAL_NOTES.md` for the real benchmark comparison that justifies this choice.
