"""
FastAPI server — RUN 2.

New/updated endpoints:
  GET  /api/status
  POST /api/stt
  POST /api/query          ← now routes through pipeline; structured response
  POST /api/benchmark/run  ← triggers live benchmark
  GET  /api/benchmark/results
  POST /api/index/build    ← builds strategy index
"""

import os
import logging
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from backend.config import (
    PROJECT_ROOT,
    RETRIEVAL_STRATEGY,
    RETRIEVAL_K,
)
from backend.pipeline.pipeline import run_pipeline, PipelineResult
from backend.benchmark.harness import run_benchmark, load_last_results
from backend.vector_store.indexer import build_index, build_all_strategies, migrate_run1_index

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

SUPPORTED_STT_LANGUAGES = {
    "en", "as", "bn", "gu", "hi", "kn", "ml", "mr", "ne", "or", "pa", "sa",
    "ta", "te", "ur", "brx", "doi", "ks", "kok", "mai", "mni", "sat", "sd"
}

VALID_STRATEGIES_LIST = ["fixed", "sentence", "metadata", "hybrid"]

@asynccontextmanager
async def lifespan(app_: FastAPI):
    """Run startup tasks before serving requests."""
    try:
        migrate_run1_index()
        logger.info("Startup index migration complete.")
    except Exception as exc:
        logger.error(
            "Startup migration failed — %s: %s\n%s",
            type(exc).__name__, exc, traceback.format_exc()
        )
    yield


app = FastAPI(title="HH Goa Voice Radar API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Benchmark state (shared across requests) ──────────────────────────────
_benchmark_running = False
_benchmark_progress: List[Dict] = []
_benchmark_total = 0


# ── Pydantic models ───────────────────────────────────────────────────────

class QueryHistoryItem(BaseModel):
    question: str
    answer: str


class QueryRequest(BaseModel):
    query: str
    language_code: Optional[str] = None
    strategy: Optional[str] = None
    k: Optional[int] = None
    history: Optional[List[QueryHistoryItem]] = None


class QueryResponse(BaseModel):
    request_id: str
    question: str
    answer: str
    refused: bool
    refusal_reason: str
    strategy: str
    retrieved_chunk_count: int
    best_distance: float
    latencies: Dict[str, float]
    total_latency: float
    excl_stt_latency: float
    guardrail_decisions: Dict[str, Any]
    retry_counts: Dict[str, int]
    context: List[Dict]
    error: bool
    error_message: str


class BenchmarkRequest(BaseModel):
    strategy: Optional[str] = None
    max_queries: Optional[int] = None


class IndexBuildRequest(BaseModel):
    strategy: str = "hybrid"
    force: bool = False


# ── Helpers ───────────────────────────────────────────────────────────────

def _pipeline_result_to_response(r: PipelineResult) -> QueryResponse:
    """Converts PipelineResult dataclass to Pydantic response model."""
    stt_lat = r.latencies.get("stt", 0.0)
    excl_stt = round(r.total_latency - stt_lat, 4)

    # Build context list for frontend (sources panel)
    context = []
    for chunk in r.retrieved_chunks:
        context.append({
            "text":            chunk.get("text", "")[:400],  # snippet
            "full_text":       chunk.get("text", ""),
            "query_id":        chunk.get("query_id"),
            "source_query":    chunk.get("source_query", ""),
            "query_type":      chunk.get("query_type", ""),
            "passage_index":   chunk.get("passage_index"),
            "is_selected":     chunk.get("is_selected", 0),
            "distance":        chunk.get("distance", 0.0),
            "relevance_score": chunk.get("relevance_score", 0.0),
            "strategy":        chunk.get("strategy", r.strategy),
            "truncated":       chunk.get("truncated", False),
        })

    return QueryResponse(
        request_id=r.request_id,
        question=r.question,
        answer=r.answer,
        refused=r.refused,
        refusal_reason=r.refusal_reason,
        strategy=r.strategy,
        retrieved_chunk_count=r.retrieved_chunk_count,
        best_distance=round(r.best_distance, 4),
        latencies=r.latencies,
        total_latency=r.total_latency,
        excl_stt_latency=excl_stt,
        guardrail_decisions=r.guardrail_decisions,
        retry_counts=r.retry_counts,
        context=context,
        error=r.error,
        error_message=r.error_message,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────



@app.get("/api/status")
def get_status():
    """Health check / status endpoint."""
    commit_hash = "unknown"
    
    # Try reading from a built commit.txt file first
    commit_file = os.path.join(os.path.dirname(__file__), "commit.txt")
    if os.path.exists(commit_file):
        try:
            with open(commit_file, "r") as f:
                commit_hash = f.read().strip()
        except Exception:
            pass
            
    # Fallback to calling git
    if commit_hash == "unknown":
        try:
            import subprocess
            commit_hash = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
        except Exception:
            pass
            
    return {
        "status": "online",
        "service": "HH Goa Voice Radar",
        "environment": "RAG RUN 2",
        "commit": commit_hash,
        "default_strategy": RETRIEVAL_STRATEGY,
        "available_strategies": VALID_STRATEGIES_LIST,
    }


@app.post("/api/stt")
async def handle_stt(file: UploadFile = File(...)):
    """
    Receives an audio file, transcribes via Sarvam AI, returns transcript.
    This endpoint is used directly by the frontend for pre-transcription.
    The full pipeline (POST /api/query) is used after transcription.
    """
    try:
        audio_bytes = await file.read()
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Uploaded audio file is empty.")

        from backend.stt.sarvam_stt import transcribe_audio
        import time

        last_exc = None
        max_attempts = 3
        transcript, language_code = None, None

        for attempt in range(max_attempts):
            try:
                transcript, language_code = transcribe_audio(audio_bytes, filename=file.filename)
                break
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "STT attempt %d failed — %s: %s. Retrying in 0.5s...",
                    attempt + 1, type(exc).__name__, exc
                )
                time.sleep(0.5)
        else:
            raise last_exc

        if language_code:
            code = language_code.split("-")[0].lower()
            if code not in SUPPORTED_STT_LANGUAGES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Language code '{language_code}' is not supported for voice input.",
                )

        return {"transcript": transcript, "language_code": language_code}

    except HTTPException as he:
        raise he
    except Exception as exc:
        logger.error(
            "STT endpoint error — %s: %s\n%s",
            type(exc).__name__, exc, traceback.format_exc()
        )
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/query", response_model=QueryResponse)
def handle_query(payload: QueryRequest):
    """
    Main RAG query endpoint. Routes through the full pipeline:
      validate → normalize → guardrail_pre → retrieve → guardrail_post →
      generate → grounding_check → format

    Response always includes structured refused/reason fields.
    """
    query_text = payload.query.strip() if payload.query else ""
    if not query_text:
        raise HTTPException(status_code=400, detail="Query text cannot be empty.")

    strategy = payload.strategy or RETRIEVAL_STRATEGY
    if strategy not in VALID_STRATEGIES_LIST:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown strategy '{strategy}'. Valid: {VALID_STRATEGIES_LIST}"
        )

    k = payload.k or RETRIEVAL_K

    try:
        history_list = None
        if payload.history:
            history_list = [{"question": h.question, "answer": h.answer} for h in payload.history]

        result = run_pipeline(
            query_text=query_text,
            language_code=payload.language_code,
            strategy=strategy,
            k=k,
            history=history_list,
        )
        return _pipeline_result_to_response(result)

    except Exception as exc:
        # Should not happen (pipeline is fully defensive), but just in case
        logger.error(
            "Query endpoint unexpected error — %s: %s\n%s",
            type(exc).__name__, exc, traceback.format_exc()
        )
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@app.post("/api/benchmark/run")
async def run_benchmark_endpoint(
    payload: BenchmarkRequest,
    background_tasks: BackgroundTasks,
):
    """
    Triggers the live benchmark harness.
    Runs in a background thread to avoid blocking.
    Returns immediately with a status; poll /api/benchmark/results for completion.
    """
    global _benchmark_running, _benchmark_progress, _benchmark_total

    if _benchmark_running:
        return JSONResponse(
            status_code=409,
            content={"error": "Benchmark already running. Wait for it to complete."}
        )

    strategy = payload.strategy or RETRIEVAL_STRATEGY
    if strategy not in VALID_STRATEGIES_LIST:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown strategy '{strategy}'. Valid: {VALID_STRATEGIES_LIST}"
        )

    max_q = payload.max_queries or 100
    _benchmark_running = True
    _benchmark_progress = []
    _benchmark_total = 0

    def _run():
        global _benchmark_running, _benchmark_progress, _benchmark_total
        try:
            def progress_cb(done, total, record):
                global _benchmark_progress, _benchmark_total
                _benchmark_total = total
                _benchmark_progress.append({
                    "done": done,
                    "total": total,
                    "latest": record,
                })

            run_benchmark(strategy=strategy, max_queries=max_q, progress_callback=progress_cb)
        except Exception as exc:
            logger.error(
                "Benchmark background task failed — %s: %s\n%s",
                type(exc).__name__, exc, traceback.format_exc()
            )
        finally:
            _benchmark_running = False

    background_tasks.add_task(_run)

    return {
        "status": "started",
        "strategy": strategy,
        "max_queries": max_q,
        "message": "Benchmark running in background. Poll /api/benchmark/results for completion.",
    }


@app.get("/api/benchmark/results")
def get_benchmark_results():
    """Returns last saved benchmark results + current run progress if running."""
    global _benchmark_running, _benchmark_progress, _benchmark_total

    results = load_last_results()
    return {
        "running": _benchmark_running,
        "progress": {
            "done": len(_benchmark_progress),
            "total": _benchmark_total,
        },
        "results": results,
    }


@app.post("/api/index/build")
async def build_index_endpoint(
    payload: IndexBuildRequest,
    background_tasks: BackgroundTasks,
):
    """Triggers index building for a strategy in the background."""
    strategy = payload.strategy
    if strategy not in VALID_STRATEGIES_LIST + ["all"]:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown strategy '{strategy}'. Valid: {VALID_STRATEGIES_LIST + ['all']}"
        )

    def _build():
        try:
            if strategy == "all":
                build_all_strategies(force=payload.force)
            else:
                build_index(strategy, force=payload.force)
        except Exception as exc:
            logger.error(
                "Index build task failed (%s) — %s: %s\n%s",
                strategy, type(exc).__name__, exc, traceback.format_exc()
            )

    background_tasks.add_task(_build)
    return {
        "status": "started",
        "strategy": strategy,
        "force": payload.force,
        "message": f"Index build for '{strategy}' started in background.",
    }


# ── Static frontend serving ───────────────────────────────────────────────

frontend_dir = os.path.join(PROJECT_ROOT, "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
else:
    @app.get("/")
    def read_root():
        return {"message": "HH Goa Voice Radar API running. Frontend folder not found."}
