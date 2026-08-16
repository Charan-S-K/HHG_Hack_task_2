"""
Benchmark harness — RUN 2.

Samples a reproducible set of queries from the committed MSMARCO-XI subset
(data/subset.jsonl, the SAME subset as RUN 1) and runs them through the LIVE
pipeline (no mocking).

Results:
  - P50, P70, P100 (= max), avg, min, max per stage and overall
  - Latency both including and excluding the STT stage
    (STT stage is N/A for text queries — documented below)
  - Saved to data/benchmark_results.json

STT NOTE:
  The benchmark drives the pipeline via the text path only (no audio).
  The PDF's 200ms target is ambiguous about whether STT time counts.
  We report:
    - "excl_stt_latency":  total pipeline time excluding the STT stage
      (this is what the 200ms target should be measured against)
    - "total_latency":     same as excl_stt here because no audio was sent;
      for real voice queries, total_latency includes STT.
  Both are reported explicitly so no silent cherry-picking occurs.

Query set:
  - Source: data/subset.jsonl, field: "query" (Hindi, native dataset language)
  - Seed:   42 (same as RUN 1, fixed for reproducibility)
  - Count:  up to BENCHMARK_MAX_QUERIES (default 100)
"""

import json
import time
import random
import logging
import traceback
from typing import List, Dict, Any

import numpy as np

from backend.config import (
    SUBSET_PATH,
    BENCHMARK_SEED,
    BENCHMARK_MAX_QUERIES,
    BENCHMARK_RESULTS_PATH,
    RETRIEVAL_STRATEGY,
)
from backend.pipeline.pipeline import run_pipeline

logger = logging.getLogger(__name__)

STAGE_KEYS = [
    "validate_input",
    "stt",
    "normalize",
    "guardrail_pre",
    "embedding_retrieval",
    "guardrail_post",
    "generation",
    "grounding_check",
]


def _load_benchmark_queries(max_queries: int = BENCHMARK_MAX_QUERIES) -> List[str]:
    """
    Loads queries from data/subset.jsonl using a fixed seed.
    Uses the SAME committed subset as RUN 1 — never re-samples.
    """
    records = []
    with open(SUBSET_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                q = rec.get("query", "").strip()
                if q:
                    records.append(q)

    rng = random.Random(BENCHMARK_SEED)
    if len(records) > max_queries:
        records = rng.sample(records, max_queries)
    else:
        rng.shuffle(records)

    return records


def _percentile(values: List[float], p: float) -> float:
    """Compute p-th percentile (0–100) of a list of floats."""
    if not values:
        return 0.0
    arr = np.array(sorted(values))
    return float(np.percentile(arr, p))


def _compute_stats(values: List[float]) -> Dict[str, float]:
    """Returns P50/P70/P100/avg/min/max for a list of floats."""
    if not values:
        return {"p50": 0.0, "p70": 0.0, "p100": 0.0, "avg": 0.0, "min": 0.0, "max": 0.0, "n": 0}
    return {
        "p50": round(_percentile(values, 50), 4),
        "p70": round(_percentile(values, 70), 4),
        "p100": round(_percentile(values, 100), 4),
        "avg": round(float(np.mean(values)), 4),
        "min": round(float(np.min(values)), 4),
        "max": round(float(np.max(values)), 4),
        "n":   len(values),
    }


def run_benchmark(
    strategy: str = None,
    max_queries: int = None,
    progress_callback=None,
) -> Dict[str, Any]:
    """
    Runs the benchmark harness against the live pipeline.

    Args:
        strategy:          Chunking/retrieval strategy (defaults to RETRIEVAL_STRATEGY).
        max_queries:       Max number of queries to run (defaults to BENCHMARK_MAX_QUERIES).
        progress_callback: Optional callable(done, total, result_dict) for streaming progress.

    Returns:
        Dict with latency stats, per-query results, and metadata.

    IMPORTANT: Numbers are NEVER hardcoded. If the pipeline fails for a query,
    that query is recorded as an error and excluded from stats (not fabricated).
    """
    strategy    = strategy or RETRIEVAL_STRATEGY
    max_queries = max_queries or BENCHMARK_MAX_QUERIES

    logger.info("Benchmark START: strategy=%s, max_queries=%d, seed=%d",
                strategy, max_queries, BENCHMARK_SEED)

    queries = _load_benchmark_queries(max_queries)
    total = len(queries)
    logger.info("Loaded %d queries from subset", total)

    per_query_results = []
    stage_latencies: Dict[str, List[float]] = {k: [] for k in STAGE_KEYS}
    total_latencies    = []
    excl_stt_latencies = []

    benchmark_start = time.time()

    for i, query in enumerate(queries):
        q_start = time.monotonic()

        try:
            pipeline_result = run_pipeline(
                query_text=query,
                strategy=strategy,
            )
        except Exception as exc:
            # Should not happen (pipeline catches everything), but defensive
            logger.error(
                "Benchmark: unexpected exception for query %d: %s: %s\n%s",
                i, type(exc).__name__, exc, traceback.format_exc()
            )
            per_query_results.append({
                "index": i,
                "query": query[:80],
                "error": True,
                "error_message": f"{type(exc).__name__}: {exc}",
            })
            if progress_callback:
                progress_callback(i + 1, total, per_query_results[-1])
            continue

        lats = pipeline_result.latencies
        total_lat    = pipeline_result.total_latency
        excl_stt_lat = total_lat - lats.get("stt", 0.0)

        if not pipeline_result.error:
            total_latencies.append(total_lat)
            excl_stt_latencies.append(excl_stt_lat)
            for stage_key in STAGE_KEYS:
                val = lats.get(stage_key)
                if val is not None:
                    stage_latencies[stage_key].append(val)

        q_record = {
            "index":           i,
            "query":           query[:80],
            "refused":         pipeline_result.refused,
            "refusal_reason":  pipeline_result.refusal_reason,
            "error":           pipeline_result.error,
            "error_message":   pipeline_result.error_message,
            "total_latency":   total_lat,
            "excl_stt_latency": excl_stt_lat,
            "latencies":       lats,
            "retry_counts":    pipeline_result.retry_counts,
            "chunks_retrieved": pipeline_result.retrieved_chunk_count,
        }
        per_query_results.append(q_record)

        logger.info(
            "Benchmark [%d/%d]: total=%.3fs excl_stt=%.3fs refused=%s error=%s",
            i + 1, total,
            total_lat, excl_stt_lat,
            pipeline_result.refused, pipeline_result.error
        )

        if progress_callback:
            progress_callback(i + 1, total, q_record)

        # Brief pause to avoid bursting API rate limit
        time.sleep(0.5)

    benchmark_elapsed = round(time.time() - benchmark_start, 2)

    # Compute stats
    total_stats    = _compute_stats(total_latencies)
    excl_stt_stats = _compute_stats(excl_stt_latencies)
    per_stage_stats = {}
    for stage_key, vals in stage_latencies.items():
        if vals:
            per_stage_stats[stage_key] = _compute_stats(vals)

    error_count   = sum(1 for r in per_query_results if r.get("error"))
    refused_count = sum(1 for r in per_query_results if r.get("refused"))
    success_count = total - error_count

    report = {
        "metadata": {
            "strategy":          strategy,
            "total_queries":     total,
            "success_count":     success_count,
            "error_count":       error_count,
            "refused_count":     refused_count,
            "benchmark_elapsed_s": benchmark_elapsed,
            "seed":              BENCHMARK_SEED,
            "subset_path":       str(SUBSET_PATH),
            "stt_included":      False,
            "stt_note": (
                "STT stage was NOT executed during this benchmark (text path only). "
                "'total_latency' == 'excl_stt_latency' here. "
                "For real voice queries, STT time must be added to total_latency. "
                "The PDF 200ms target is measured against 'excl_stt_latency'."
            ),
        },
        "overall": {
            "total_latency_s":    total_stats,
            "excl_stt_latency_s": excl_stt_stats,
        },
        "per_stage_s":     per_stage_stats,
        "per_query":       per_query_results,
        "meets_200ms_target": (
            excl_stt_stats.get("p50", 999) < 0.200
        ),
        "bottleneck_stage": (
            max(per_stage_stats.items(), key=lambda x: x[1].get("avg", 0))[0]
            if per_stage_stats else "unknown"
        ),
    }

    # Save to disk
    try:
        with open(BENCHMARK_RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info("Benchmark results saved to %s", BENCHMARK_RESULTS_PATH)
    except Exception as exc:
        logger.error("Failed to save benchmark results: %s: %s", type(exc).__name__, exc)

    return report


def load_last_results() -> Dict[str, Any]:
    """Loads the last saved benchmark results from disk, or returns empty dict."""
    try:
        with open(BENCHMARK_RESULTS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.error("Failed to load benchmark results: %s: %s", type(exc).__name__, exc)
        return {}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    strategy = sys.argv[1] if len(sys.argv) > 1 else RETRIEVAL_STRATEGY
    report = run_benchmark(strategy=strategy)
    print(json.dumps(report["overall"], indent=2))
    print(f"\nBottleneck stage: {report['bottleneck_stage']}")
    print(f"Meets 200ms target (P50 excl STT): {report['meets_200ms_target']}")
