# Data Handoff Details

This file describes how to reproduce and re-verify the local dataset subset used for the RAG index in **HH Goa Voice Radar**.

## Reproduction Instructions

To reproduce the exact subset stored in `data/subset.jsonl`:

1.  **Source Dataset**: `ai4bharat/MSMARCO-XI` on Hugging Face.
2.  **Split**: `validation` (retrieved from raw parquet path `validation/hinval.parquet`).
3.  **Hugging Face Commit / Revision**: `bf5cdc1f26e581e519018e434db14edd1b77602b`
4.  **Sampling Parameters**:
    *   **Seed Value**: `42`
    *   **Candidate Range**: The first `500` records in the stream.
    *   **Final Sample Size**: `100` records sampled from the candidate range.
5.  **Target File**: Saved as a JSONL file at [subset.jsonl](file:///Users/charantejsk/Documents/HHG/HHG_TASK_2/data/subset.jsonl).

## Code for Reproduction

Running the following command will download the file, apply the same random seed, and reproduce the file:

```bash
python3 scratch/sample_local_parquet.py
```

*Note: The intermediate raw `hinval.parquet` is deleted after sampling to prevent bloating the repository.*

## Index Rebuilding Details
*   **Re-indexing Date**: 2026-08-14
*   **Vector Database**: FAISS (IndexFlatL2)
*   **Dimensions**: 384
*   **Embedding Model**: `intfloat/multilingual-e5-small`
