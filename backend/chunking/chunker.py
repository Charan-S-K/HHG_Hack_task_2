"""
Multi-strategy chunking for HH Goa Voice Radar — RUN 2.

Strategies:
  fixed    — RUN 1 baseline: fixed-size character window with overlap
  sentence — sentence/semantic boundary splitting
  metadata — fixed-size + rich source metadata stamped on every chunk
  hybrid   — sentence boundaries + metadata + fixed-size fallback for degenerate cases
"""

import re
from typing import List, Dict, Any


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def clean_text(text: str) -> str:
    """Normalises whitespace, removes extra line breaks, strips boundaries."""
    if not text:
        return ""
    cleaned = re.sub(r'\s+', ' ', text)
    return cleaned.strip()


def _make_base_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Returns a safe copy of source metadata fields to stamp on chunks."""
    return {
        "query_id":       metadata.get("query_id"),
        "passage_index":  metadata.get("passage_index"),
        "is_selected":    metadata.get("is_selected", 0),
        "source_query":   metadata.get("source_query"),
        "source_answer":  metadata.get("source_answer"),
        "query_type":     metadata.get("query_type"),
    }


# ---------------------------------------------------------------------------
# Strategy 1: Fixed-size with overlap (RUN 1 baseline)
# ---------------------------------------------------------------------------

def fixed_size_chunker(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
    metadata: Dict[str, Any] = None,
) -> List[Dict[str, Any]]:
    """
    Fixed-size character window with overlapping boundaries.
    Preserves RUN 1 behaviour exactly.  Optionally stamps metadata.
    """
    text = clean_text(text)
    if not text:
        return []

    meta = _make_base_metadata(metadata or {})

    if len(text) <= chunk_size:
        return [{
            "text": text,
            "start_char": 0,
            "end_char": len(text),
            "strategy": "fixed",
            **meta,
        }]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk_str = text[start:end]
        chunks.append({
            "text": chunk_str,
            "start_char": start,
            "end_char": min(end, len(text)),
            "strategy": "fixed",
            **meta,
        })
        start += (chunk_size - overlap)
        if start >= len(text):
            break

    return chunks


# RUN 1 backwards-compat alias
def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[Dict[str, Any]]:
    """RUN 1 API alias — delegates to fixed_size_chunker without metadata."""
    return fixed_size_chunker(text, chunk_size=chunk_size, overlap=overlap)


# ---------------------------------------------------------------------------
# Strategy 2: Sentence / semantic-boundary chunker
# ---------------------------------------------------------------------------

# Sentence boundary pattern: handles Hindi danda (।), ?, !, . followed by space
_SENT_BOUNDARY = re.compile(r'(?<=[।?!.。])\s+|(?<=।)')

def sentence_chunker(
    text: str,
    max_chars: int = 600,
    min_chars: int = 60,
    metadata: Dict[str, Any] = None,
) -> List[Dict[str, Any]]:
    """
    Splits on sentence-level boundaries (., ।, ?, !).
    Accumulates sentences until max_chars would be exceeded, then emits a chunk.
    Very short segments (<min_chars) are merged with the next segment.
    Falls back to fixed-size for degenerate single-sentence texts.
    """
    text = clean_text(text)
    if not text:
        return []

    meta = _make_base_metadata(metadata or {})

    # Split into sentences
    raw_sents = _SENT_BOUNDARY.split(text)
    # Filter empty
    sents = [s.strip() for s in raw_sents if s.strip()]

    if not sents:
        return []

    # If single sentence or no useful splits, fall back to fixed-size
    if len(sents) == 1 or len(text) <= min_chars:
        return fixed_size_chunker(text, chunk_size=max_chars, overlap=50, metadata=metadata)

    chunks = []
    buffer = []
    buffer_len = 0
    char_pos = 0

    for sent in sents:
        sent_len = len(sent)

        # If this single sentence already exceeds max_chars, split it further
        if sent_len > max_chars:
            # Flush current buffer first
            if buffer:
                combined = " ".join(buffer)
                chunks.append({
                    "text": combined,
                    "start_char": char_pos - len(combined),
                    "end_char": char_pos,
                    "strategy": "sentence",
                    **meta,
                })
                buffer, buffer_len = [], 0

            # Recursively fixed-split the oversized sentence
            sub = fixed_size_chunker(sent, chunk_size=max_chars, overlap=50, metadata=metadata)
            for s in sub:
                s["strategy"] = "sentence"
                chunks.append(s)
            char_pos += sent_len + 1
            continue

        # Would adding this sentence overflow the buffer?
        if buffer_len + sent_len > max_chars and buffer_len >= min_chars:
            combined = " ".join(buffer)
            chunks.append({
                "text": combined,
                "start_char": char_pos - buffer_len,
                "end_char": char_pos,
                "strategy": "sentence",
                **meta,
            })
            buffer, buffer_len = [], 0

        buffer.append(sent)
        buffer_len += sent_len + 1  # +1 for space
        char_pos += sent_len + 1

    # Flush remaining buffer
    if buffer:
        combined = " ".join(buffer)
        chunks.append({
            "text": combined,
            "start_char": char_pos - len(combined),
            "end_char": char_pos,
            "strategy": "sentence",
            **meta,
        })

    # If nothing got chunked, return single chunk
    if not chunks:
        return [{
            "text": text,
            "start_char": 0,
            "end_char": len(text),
            "strategy": "sentence",
            **meta,
        }]

    return chunks


# ---------------------------------------------------------------------------
# Strategy 3: Metadata-aware chunker
# ---------------------------------------------------------------------------

def metadata_aware_chunker(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
    metadata: Dict[str, Any] = None,
) -> List[Dict[str, Any]]:
    """
    Fixed-size chunking that richly stamps source document metadata on every
    chunk dict.  Enables post-retrieval metadata filtering.
    """
    text = clean_text(text)
    if not text:
        return []

    meta = _make_base_metadata(metadata or {})
    chunks = fixed_size_chunker(text, chunk_size=chunk_size, overlap=overlap, metadata=metadata)

    for chunk in chunks:
        chunk["strategy"] = "metadata"
        # Ensure all metadata fields are present (fixed_size_chunker already stamps them)

    return chunks


# ---------------------------------------------------------------------------
# Strategy 4: Hybrid chunker (sentence + metadata + fixed fallback)
# ---------------------------------------------------------------------------

def hybrid_chunker(
    text: str,
    max_chars: int = 600,
    min_chars: int = 60,
    fallback_chunk_size: int = 500,
    fallback_overlap: int = 50,
    metadata: Dict[str, Any] = None,
) -> List[Dict[str, Any]]:
    """
    Combines sentence-boundary splitting with rich metadata stamping and a
    fixed-size fallback for degenerate inputs.

    Production default strategy.
    """
    text = clean_text(text)
    if not text:
        return []

    meta = _make_base_metadata(metadata or {})

    # Attempt sentence splitting
    chunks = sentence_chunker(text, max_chars=max_chars, min_chars=min_chars, metadata=metadata)

    if not chunks:
        # Degenerate: fall back to fixed-size
        chunks = fixed_size_chunker(
            text,
            chunk_size=fallback_chunk_size,
            overlap=fallback_overlap,
            metadata=metadata,
        )

    # Stamp strategy tag and ensure all metadata fields present
    for chunk in chunks:
        chunk["strategy"] = "hybrid"
        for k, v in meta.items():
            if k not in chunk:
                chunk[k] = v

    return chunks


# ---------------------------------------------------------------------------
# Strategy dispatcher
# ---------------------------------------------------------------------------

STRATEGY_FN_MAP = {
    "fixed":    fixed_size_chunker,
    "sentence": sentence_chunker,
    "metadata": metadata_aware_chunker,
    "hybrid":   hybrid_chunker,
}


def chunk_by_strategy(
    text: str,
    strategy: str = "hybrid",
    metadata: Dict[str, Any] = None,
    **kwargs,
) -> List[Dict[str, Any]]:
    """
    Dispatches to the correct chunking function by strategy name.
    Raises ValueError for unknown strategy names.
    """
    fn = STRATEGY_FN_MAP.get(strategy)
    if fn is None:
        raise ValueError(
            f"Unknown chunking strategy '{strategy}'. "
            f"Valid options: {list(STRATEGY_FN_MAP.keys())}"
        )
    return fn(text, metadata=metadata, **kwargs)
