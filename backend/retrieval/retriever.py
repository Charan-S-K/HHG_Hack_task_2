"""
Retrieval module with refinements — RUN 2.

Enhancements over RUN 1:
  - Strategy-specific index loading (fixed/sentence/metadata/hybrid)
  - Configurable top-k
  - Post-retrieval metadata filtering
  - Near-duplicate deduplication via dot-product similarity
  - Context compression to MAX_CONTEXT_CHARS
"""

import os
import json
import numpy as np
import faiss
from typing import List, Dict, Any, Optional

from backend.config import (
    STRATEGY_INDEX_DIRS,
    RETRIEVAL_K,
    RETRIEVAL_STRATEGY,
    DEDUP_SIMILARITY_THRESHOLD,
    MAX_CONTEXT_CHARS,
)
from backend.embeddings.embedder import embed_query

# Per-strategy singletons
_indices: Dict[str, Any] = {}
_metadatas: Dict[str, Any] = {}


def _load_retriever(strategy: str):
    """
    Loads and caches the FAISS index + metadata for a given strategy.
    Raises FileNotFoundError if index is not built yet.
    """
    global _indices, _metadatas

    if strategy not in _indices or _indices[strategy] is None:
        base_dir = STRATEGY_INDEX_DIRS.get(strategy)
        if base_dir is None:
            raise ValueError(f"Unknown retrieval strategy: '{strategy}'")

        idx_file  = os.path.join(base_dir, "index.faiss")
        meta_file = os.path.join(base_dir, "metadata.json")

        if not os.path.exists(idx_file) or not os.path.exists(meta_file):
            raise FileNotFoundError(
                f"Index for strategy '{strategy}' not found at {idx_file}. "
                f"Run: python -m backend.vector_store.indexer --strategy {strategy}"
            )

        print(f"[retriever] Loading '{strategy}' index from {idx_file}...")
        _indices[strategy]   = faiss.read_index(idx_file)
        with open(meta_file, "r", encoding="utf-8") as f:
            _metadatas[strategy] = json.load(f)
        print(f"[retriever] '{strategy}' index ready — "
              f"{_indices[strategy].ntotal} vectors, "
              f"{len(_metadatas[strategy])} metadata records.")

    return _indices[strategy], _metadatas[strategy]


def _deduplicate(
    results: List[Dict[str, Any]],
    query_emb: np.ndarray,
    threshold: float = DEDUP_SIMILARITY_THRESHOLD,
) -> List[Dict[str, Any]]:
    """
    Removes near-identical chunks by computing pairwise text similarity.
    Two chunks are considered duplicates if their Jaccard-token overlap > threshold.
    (Fast approximation — no re-embedding needed.)
    """
    if len(results) <= 1:
        return results

    def tokens(text: str):
        return set(text.lower().split())

    deduplicated = []
    for candidate in results:
        cand_toks = tokens(candidate["text"])
        is_dup = False
        for kept in deduplicated:
            kept_toks = tokens(kept["text"])
            union = cand_toks | kept_toks
            if not union:
                continue
            jaccard = len(cand_toks & kept_toks) / len(union)
            if jaccard > threshold:
                is_dup = True
                break
        if not is_dup:
            deduplicated.append(candidate)

    return deduplicated


def _compress_context(
    results: List[Dict[str, Any]],
    max_chars: int = MAX_CONTEXT_CHARS,
) -> List[Dict[str, Any]]:
    """
    Truncates context passed to LLM to max_chars total.
    Preserves as many full chunks as possible; truncates the last one if needed.
    """
    total = 0
    compressed = []
    for chunk in results:
        text = chunk["text"]
        remaining = max_chars - total
        if remaining <= 0:
            break
        if len(text) > remaining:
            chunk = chunk.copy()
            chunk["text"] = text[:remaining]
            chunk["truncated"] = True
            compressed.append(chunk)
            break
        compressed.append(chunk)
        total += len(text)
    return compressed


def retrieve_top_k(
    query_text: str,
    strategy: str = None,
    k: int = None,
    metadata_filter: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Main retrieval function.

    Args:
        query_text:      The query string.
        strategy:        Chunking/index strategy. Defaults to RETRIEVAL_STRATEGY.
        k:               Number of results to fetch before dedup. Defaults to RETRIEVAL_K.
        metadata_filter: Optional dict of field→value pairs for post-retrieval filtering.
                         E.g. {"query_type": "description"} or {"is_selected": 1}.

    Returns:
        List of chunk dicts (post-dedup, post-compression), each with added fields:
            distance        — raw L2 distance
            relevance_score — normalised score (lower distance = higher score)
    """
    if strategy is None:
        strategy = RETRIEVAL_STRATEGY
    if k is None:
        k = RETRIEVAL_K

    # Fetch more initially so dedup has headroom
    fetch_k = min(k * 3, 30)

    index, metadata = _load_retriever(strategy)

    # Embed query
    query_emb = embed_query(query_text).reshape(1, -1).astype("float32")

    # Search
    distances, indices = index.search(query_emb, fetch_k)

    raw_results = []
    for dist, idx in zip(distances[0], indices[0]):
        if idx < 0 or idx >= len(metadata):
            continue
        record = metadata[idx].copy()
        record["distance"] = float(dist)
        # Normalised relevance score: 1/(1+dist) so closer = higher score
        record["relevance_score"] = round(1.0 / (1.0 + float(dist)), 4)
        raw_results.append(record)

    # Metadata filtering
    if metadata_filter:
        filtered = []
        for r in raw_results:
            match = all(str(r.get(k)) == str(v) for k, v in metadata_filter.items())
            if match:
                filtered.append(r)
        raw_results = filtered if filtered else raw_results  # Don't return empty if filter is too strict

    # Sort by distance (ascending = most relevant first)
    raw_results.sort(key=lambda x: x["distance"])

    # Deduplicate
    deduped = _deduplicate(raw_results, query_emb)

    # Trim to requested k
    top_k = deduped[:k]

    # Context compression
    compressed = _compress_context(top_k)

    return compressed


def get_best_distance(results: List[Dict[str, Any]]) -> float:
    """Returns the L2 distance of the best (closest) retrieved chunk, or inf if empty."""
    if not results:
        return float("inf")
    return min(r["distance"] for r in results)
