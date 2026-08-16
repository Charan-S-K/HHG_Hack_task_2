"""
Orchestrated RAG pipeline — RUN 2.

Stages:
  1. validate_input
  2. stt                  (optional, audio path)
  3. normalize_query
  4. guardrail_precheck   (unsafe input)
  5. embed_and_retrieve
  6. guardrail_postcheck  (off-topic, insufficient-context)
  7. generate
  8. grounding_check
  9. format_output

Each stage:
  - Records its own latency
  - Has controlled retries (for external calls)
  - Catches exceptions and returns a friendly structured error instead of crashing
  - Logs the REAL exception type and message internally

PipelineResult is the authoritative response structure consumed by the API.
"""

import time
import uuid
import logging
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.config import (
    RETRIEVAL_STRATEGY,
    RETRIEVAL_K,
    LLM_MAX_RETRIES,
    STT_MAX_RETRIES,
    LLM_TIMEOUT,
    STT_TIMEOUT,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    request_id: str = ""
    question: str = ""
    answer: str = ""
    strategy: str = ""

    # Guardrail fields
    refused: bool = False
    refusal_reason: str = ""    # e.g. "off_topic", "unsafe_input", "ungrounded"

    # Retrieval fields
    retrieved_chunks: List[Dict] = field(default_factory=list)
    retrieved_chunk_count: int = 0
    best_distance: float = 0.0

    # Latency breakdown (seconds)
    latencies: Dict[str, float] = field(default_factory=dict)
    total_latency: float = 0.0

    # Retry tracking
    retry_counts: Dict[str, int] = field(default_factory=dict)

    # Guardrail decisions log
    guardrail_decisions: Dict[str, Any] = field(default_factory=dict)

    # Error (non-refused failures)
    error: bool = False
    error_message: str = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _timer():
    """Returns current monotonic time."""
    return time.monotonic()


def _retry_call(fn, max_retries: int, stage_name: str, *args, **kwargs):
    """
    Calls fn(*args, **kwargs) with up to max_retries attempts on exception.
    Returns (result, retry_count).
    Raises the last exception if all retries exhausted.
    """
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            result = fn(*args, **kwargs)
            if attempt > 0:
                logger.info("[%s] Succeeded on retry %d", stage_name, attempt)
            return result, attempt
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "[%s] Attempt %d/%d failed — %s: %s",
                stage_name, attempt + 1, max_retries + 1,
                type(exc).__name__, exc
            )
            if attempt < max_retries:
                # If rate limited (HTTP 429), back off longer
                if "429" in str(exc) or "quota" in str(exc).lower():
                    sleep_time = 4.0 * (attempt + 1)
                else:
                    sleep_time = 0.5 * (attempt + 1)
                time.sleep(sleep_time)

    raise last_exc


# ---------------------------------------------------------------------------
# Stage implementations
# ---------------------------------------------------------------------------

def _stage_validate_input(query_text: str) -> Dict:
    """Stage 1: basic input validation."""
    stripped = query_text.strip() if query_text else ""
    if not stripped:
        raise ValueError("Query text cannot be empty.")
    if len(stripped) > 2000:
        raise ValueError("Query text exceeds maximum length (2000 chars).")
    return {"query_text": stripped}


def _stage_stt(audio_bytes: bytes, filename: str, result: PipelineResult) -> Dict:
    """Stage 2: STT transcription (optional — only when audio_bytes provided)."""
    from backend.stt.sarvam_stt import transcribe_audio

    def _do_stt():
        return transcribe_audio(audio_bytes, filename=filename, timeout=STT_TIMEOUT)

    transcript, language_code, retry_count = None, None, 0
    try:
        (transcript, language_code), retry_count = _retry_call(
            _do_stt, max_retries=STT_MAX_RETRIES, stage_name="stt"
        )
    except Exception as exc:
        logger.error(
            "[stt] STT failed after retries — %s: %s\n%s",
            type(exc).__name__, exc, traceback.format_exc()
        )
        raise

    result.retry_counts["stt"] = retry_count
    return {"transcript": transcript, "language_code": language_code}


def _stage_normalize_query(query_text: str, language_code: Optional[str]) -> Dict:
    """Stage 3: language detection + query normalisation."""
    from backend.utils.lang_detect import detect_language_name
    target_language = detect_language_name(query_text, language_code)
    return {"target_language": target_language}


def _stage_guardrail_precheck(query_text: str, result: PipelineResult) -> Dict:
    """Stage 4: pre-retrieval unsafe input guardrail."""
    from backend.guardrails.guardrails import check_unsafe_input
    decision = check_unsafe_input(query_text)
    result.guardrail_decisions["unsafe_input"] = decision
    return decision


def _stage_embed_and_retrieve(
    query_text: str,
    strategy: str,
    k: int,
    result: PipelineResult,
) -> Dict:
    """Stage 5: embed query and retrieve top-k chunks."""
    from backend.retrieval.retriever import retrieve_top_k, get_best_distance

    chunks = retrieve_top_k(query_text, strategy=strategy, k=k)
    best_dist = get_best_distance(chunks)
    result.retrieved_chunks = chunks
    result.retrieved_chunk_count = len(chunks)
    result.best_distance = best_dist
    return {"chunks": chunks, "best_distance": best_dist}


def _stage_guardrail_postcheck(
    chunks: List[Dict],
    result: PipelineResult,
) -> Dict:
    """Stage 6: off-topic and insufficient-context checks."""
    from backend.guardrails.guardrails import check_off_topic, check_insufficient_context

    off_topic_decision = check_off_topic(chunks)
    result.guardrail_decisions["off_topic"] = off_topic_decision
    if not off_topic_decision["passed"]:
        return {"blocked": True, "reason": "off_topic"}

    insuff_decision = check_insufficient_context(chunks)
    result.guardrail_decisions["insufficient_context"] = insuff_decision
    if not insuff_decision["passed"]:
        return {"blocked": True, "reason": "insufficient_context"}

    return {"blocked": False}


def _stage_generate(
    query_text: str,
    chunks: List[Dict],
    target_language: str,
    result: PipelineResult,
) -> str:
    """Stage 7: LLM answer generation with retries."""
    from backend.llm_provider.gemini_llm import generate_answer

    def _do_generate():
        return generate_answer(query_text, chunks, target_language=target_language)

    try:
        answer, retry_count = _retry_call(
            _do_generate, max_retries=LLM_MAX_RETRIES, stage_name="generation"
        )
    except Exception as exc:
        logger.error(
            "[generation] LLM failed after retries — %s: %s\n%s",
            type(exc).__name__, exc, traceback.format_exc()
        )
        raise

    result.retry_counts["generation"] = retry_count
    return answer


def _stage_grounding_check(
    answer: str,
    chunks: List[Dict],
    target_language: str,
    result: PipelineResult,
) -> Dict:
    """Stage 8: grounding validation."""
    from backend.guardrails.guardrails import check_grounding

    decision = check_grounding(answer, chunks, target_language=target_language)
    result.guardrail_decisions["grounding"] = decision
    return decision


def _generate_refusal(
    reason: str,
    query_text: str,
    target_language: str,
) -> str:
    """Helper to generate a dynamic language refusal message."""
    from backend.guardrails.guardrails import generate_refusal_message
    return generate_refusal_message(reason, target_language, query_text)


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------

def run_pipeline(
    query_text: str = None,
    audio_bytes: bytes = None,
    audio_filename: str = "audio.wav",
    language_code: str = None,
    strategy: str = None,
    k: int = None,
) -> PipelineResult:
    """
    Runs the full RAG pipeline for a text or audio query.

    If audio_bytes is provided, STT is run first to get query_text.
    query_text takes priority over audio_bytes if both provided.

    Returns a PipelineResult — never raises (all exceptions caught and
    mapped to result.error=True with real error detail in result.error_message).
    """
    request_id = str(uuid.uuid4())[:8]
    result = PipelineResult(request_id=request_id)
    strategy = strategy or RETRIEVAL_STRATEGY
    k = k or RETRIEVAL_K
    result.strategy = strategy

    pipeline_start = _timer()

    logger.info(
        "=== Pipeline START [%s] strategy=%s k=%d ===",
        request_id, strategy, k
    )

    target_language = "Hindi"  # default before detection

    try:
        # ── Stage 1: Input validation ──────────────────────────────────────
        t0 = _timer()
        if query_text:
            validated = _stage_validate_input(query_text)
            query_text = validated["query_text"]
        elif not audio_bytes:
            raise ValueError("Either query_text or audio_bytes must be provided.")
        result.latencies["validate_input"] = round(_timer() - t0, 4)
        logger.info("[%s] Stage 1 validate_input: %.4fs", request_id, result.latencies["validate_input"])

        # ── Stage 2: STT (optional) ────────────────────────────────────────
        t0 = _timer()
        if audio_bytes and not query_text:
            stt_out = _stage_stt(audio_bytes, audio_filename, result)
            query_text = stt_out["transcript"]
            language_code = stt_out.get("language_code") or language_code
        result.latencies["stt"] = round(_timer() - t0, 4)
        logger.info("[%s] Stage 2 stt: %.4fs", request_id, result.latencies["stt"])

        result.question = query_text or ""

        # ── Stage 3: Normalize / detect language ──────────────────────────
        t0 = _timer()
        norm_out = _stage_normalize_query(query_text, language_code)
        target_language = norm_out["target_language"]
        result.latencies["normalize"] = round(_timer() - t0, 4)
        logger.info("[%s] Stage 3 normalize: lang=%s %.4fs", request_id, target_language, result.latencies["normalize"])

        # ── Stage 4: Guardrail pre-check ──────────────────────────────────
        t0 = _timer()
        precheck = _stage_guardrail_precheck(query_text, result)
        result.latencies["guardrail_pre"] = round(_timer() - t0, 4)
        logger.info("[%s] Stage 4 guardrail_pre: passed=%s %.4fs", request_id, precheck.get("passed"), result.latencies["guardrail_pre"])

        if not precheck.get("passed"):
            result.refused = True
            result.refusal_reason = precheck.get("reason", "unsafe_input")
            result.answer = _generate_refusal(result.refusal_reason, query_text, target_language)
            result.total_latency = round(_timer() - pipeline_start, 4)
            logger.info("[%s] Pipeline REFUSED (pre): %s", request_id, result.refusal_reason)
            return result

        # ── Stage 5: Embed + Retrieve ─────────────────────────────────────
        t0 = _timer()
        retrieve_out = _stage_embed_and_retrieve(query_text, strategy, k, result)
        result.latencies["embedding_retrieval"] = round(_timer() - t0, 4)
        logger.info(
            "[%s] Stage 5 retrieve: %d chunks, best_dist=%.4f %.4fs",
            request_id, len(retrieve_out["chunks"]),
            retrieve_out["best_distance"],
            result.latencies["embedding_retrieval"]
        )

        # ── Stage 6: Guardrail post-check ─────────────────────────────────
        t0 = _timer()
        postcheck = _stage_guardrail_postcheck(retrieve_out["chunks"], result)
        result.latencies["guardrail_post"] = round(_timer() - t0, 4)
        logger.info("[%s] Stage 6 guardrail_post: blocked=%s %.4fs", request_id, postcheck.get("blocked"), result.latencies["guardrail_post"])

        if postcheck.get("blocked"):
            result.refused = True
            result.refusal_reason = postcheck.get("reason", "off_topic")
            result.answer = _generate_refusal(result.refusal_reason, query_text, target_language)
            result.total_latency = round(_timer() - pipeline_start, 4)
            logger.info("[%s] Pipeline REFUSED (post): %s", request_id, result.refusal_reason)
            return result

        # ── Stage 7: Generate ─────────────────────────────────────────────
        t0 = _timer()
        answer = _stage_generate(query_text, retrieve_out["chunks"], target_language, result)
        result.latencies["generation"] = round(_timer() - t0, 4)
        logger.info("[%s] Stage 7 generate: len=%d %.4fs", request_id, len(answer), result.latencies["generation"])

        # ── Stage 8: Grounding check ──────────────────────────────────────
        t0 = _timer()
        grounding = _stage_grounding_check(answer, retrieve_out["chunks"], target_language, result)
        result.latencies["grounding_check"] = round(_timer() - t0, 4)
        logger.info("[%s] Stage 8 grounding: passed=%s %.4fs", request_id, grounding.get("passed"), result.latencies["grounding_check"])

        if not grounding.get("passed"):
            result.refused = True
            result.refusal_reason = "ungrounded"
            result.answer = _generate_refusal("ungrounded", query_text, target_language)
            result.total_latency = round(_timer() - pipeline_start, 4)
            logger.info("[%s] Pipeline REFUSED (grounding)", request_id)
            return result

        # ── Stage 9: Format output ────────────────────────────────────────
        result.answer = answer
        result.total_latency = round(_timer() - pipeline_start, 4)

        logger.info(
            "=== Pipeline DONE [%s] total=%.4fs (excl_stt=%.4fs) ===",
            request_id,
            result.total_latency,
            result.total_latency - result.latencies.get("stt", 0.0),
        )
        return result

    except Exception as exc:
        # Catch-all — must log real exception type and message
        logger.error(
            "=== Pipeline ERROR [%s] — %s: %s ===\n%s",
            request_id, type(exc).__name__, exc, traceback.format_exc()
        )
        result.error = True
        result.error_message = f"{type(exc).__name__}: {exc}"
        result.total_latency = round(_timer() - pipeline_start, 4)
        return result
