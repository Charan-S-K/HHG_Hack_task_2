"""
Multi-strategy FAISS indexer — RUN 2.

Each strategy ('fixed', 'sentence', 'metadata', 'hybrid') builds its own
persisted index under data/faiss_index/<strategy>/.

Usage:
    python -m backend.vector_store.indexer --strategy hybrid --force
    python -m backend.vector_store.indexer --strategy all --force
"""

import os
import json
import argparse
import numpy as np
import faiss

from backend.config import (
    FAISS_INDEX_BASE,
    STRATEGY_INDEX_DIRS,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    EMBEDDING_MODEL_NAME,
)
from backend.dataset_ingestion.loader import load_subset_data
from backend.chunking.chunker import chunk_by_strategy
from backend.embeddings.embedder import embed_texts

VALID_STRATEGIES = ["fixed", "sentence", "metadata", "hybrid"]


def _get_paths(strategy: str):
    """Returns (index_file, metadata_file) paths for the given strategy."""
    base = STRATEGY_INDEX_DIRS[strategy]
    return os.path.join(base, "index.faiss"), os.path.join(base, "metadata.json")


def _index_exists(strategy: str) -> bool:
    idx_file, meta_file = _get_paths(strategy)
    return os.path.exists(idx_file) and os.path.exists(meta_file)


def build_index(strategy: str = "hybrid", force: bool = False) -> None:
    """
    Builds the FAISS index and metadata store for a given chunking strategy.
    Skips if already built unless force=True.
    """
    if strategy not in VALID_STRATEGIES:
        raise ValueError(f"Unknown strategy '{strategy}'. Valid: {VALID_STRATEGIES}")

    idx_file, meta_file = _get_paths(strategy)

    if _index_exists(strategy) and not force:
        print(f"[{strategy}] Index already exists at {idx_file}. Use --force to rebuild.")
        return

    print(f"\n{'='*60}")
    print(f"[{strategy}] Building FAISS index...")
    print(f"{'='*60}")

    records = load_subset_data()
    chunks_metadata = []
    chunk_texts_list = []

    for r in records:
        q_id        = r.get("query_id")
        source_q    = r.get("query")
        source_ans  = r.get("Answer")
        query_type  = r.get("query_type")
        passages    = r.get("passages", {})

        translated_passages = passages.get("Translated_passages", [])
        is_selected_flags   = passages.get("is_selected", [0] * len(translated_passages))

        for p_idx, p_text in enumerate(translated_passages):
            is_sel = is_selected_flags[p_idx] if p_idx < len(is_selected_flags) else 0

            # Build metadata dict for this passage
            passage_meta = {
                "query_id":      q_id,
                "passage_index": p_idx,
                "is_selected":   is_sel,
                "source_query":  source_q,
                "source_answer": source_ans,
                "query_type":    query_type,
            }

            # Chunk using the selected strategy
            p_chunks = chunk_by_strategy(p_text, strategy=strategy, metadata=passage_meta)

            for c_idx, chunk in enumerate(p_chunks):
                chunk_text_str = chunk["text"]
                chunk_texts_list.append(chunk_text_str)

                chunks_metadata.append({
                    "chunk_id":      len(chunks_metadata),
                    "query_id":      q_id,
                    "text":          chunk_text_str,
                    "passage_index": p_idx,
                    "chunk_index":   c_idx,
                    "is_selected":   is_sel,
                    "source_query":  source_q,
                    "source_answer": source_ans,
                    "query_type":    query_type,
                    "strategy":      strategy,
                })

    if not chunk_texts_list:
        print(f"[{strategy}] No chunks found — aborting.")
        return

    print(f"[{strategy}] Total chunks: {len(chunk_texts_list)}")

    # Generate embeddings
    print(f"[{strategy}] Generating embeddings (model: {EMBEDDING_MODEL_NAME})...")
    embeddings = embed_texts(chunk_texts_list)
    dimension = embeddings.shape[1]
    print(f"[{strategy}] Embeddings shape: {embeddings.shape}, dim={dimension}")

    # Build FAISS index
    index = faiss.IndexFlatL2(dimension)
    index.add(embeddings.astype("float32"))

    # Persist
    os.makedirs(STRATEGY_INDEX_DIRS[strategy], exist_ok=True)
    faiss.write_index(index, idx_file)
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(chunks_metadata, f, ensure_ascii=False, indent=2)

    print(f"[{strategy}] Saved index -> {idx_file}")
    print(f"[{strategy}] Saved metadata -> {meta_file}")
    print(f"[{strategy}] Done\n")


def build_all_strategies(force: bool = False) -> None:
    """Builds indexes for all four strategies."""
    for strategy in VALID_STRATEGIES:
        build_index(strategy, force=force)


def migrate_run1_index() -> None:
    """
    If the old RUN 1 flat index (data/faiss_index/index.faiss) exists, copy it
    into the 'fixed' strategy subdirectory so RUN 2 can find it.
    """
    old_idx = os.path.join(FAISS_INDEX_BASE, "index.faiss")
    old_meta = os.path.join(os.path.dirname(FAISS_INDEX_BASE), "metadata.json")

    new_idx, new_meta = _get_paths("fixed")

    if not _index_exists("fixed") and os.path.exists(old_idx):
        import shutil
        os.makedirs(STRATEGY_INDEX_DIRS["fixed"], exist_ok=True)
        shutil.copy2(old_idx, new_idx)
        print(f"Migrated RUN 1 index -> {new_idx}")

        if os.path.exists(old_meta):
            # Load old metadata and stamp strategy field
            with open(old_meta, "r", encoding="utf-8") as f:
                old_data = json.load(f)
            for rec in old_data:
                if "strategy" not in rec:
                    rec["strategy"] = "fixed"
            with open(new_meta, "w", encoding="utf-8") as f:
                json.dump(old_data, f, ensure_ascii=False, indent=2)
            print(f"Migrated RUN 1 metadata -> {new_meta}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build FAISS index for a chunking strategy")
    parser.add_argument(
        "--strategy",
        choices=VALID_STRATEGIES + ["all"],
        default="hybrid",
        help="Chunking strategy to index (default: hybrid). Use 'all' to build all.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force rebuild even if index already exists.",
    )
    args = parser.parse_args()

    # Migrate RUN 1 flat index into 'fixed' subdir if needed
    migrate_run1_index()

    if args.strategy == "all":
        build_all_strategies(force=args.force)
    else:
        build_index(args.strategy, force=args.force)
