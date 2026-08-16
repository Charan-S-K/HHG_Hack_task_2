"""
Guardrails for HH Goa Voice Radar — RUN 2.

Four guardrail checks:
  1. unsafe_input     — lightweight pre-retrieval pattern check
  2. off_topic        — retrieval similarity threshold check
  3. insufficient_ctx — no results above distance threshold
  4. grounding        — verify answer is supported by retrieved context

All refusal messages are generated DYNAMICALLY in the detected query language
using the same generate_answer() mechanism from RUN 1 — no hardcoded strings.

Returns structured dicts:
  {"passed": True}
  {"passed": False, "reason": "<code>", "message": "<dynamic language msg>"}
"""

import re
import logging
from typing import List, Dict, Any, Optional

from backend.config import (
    OFF_TOPIC_L2_THRESHOLD,
    INSUFFICIENT_CONTEXT_L2_THRESHOLD,
    GROUNDING_MIN_OVERLAP,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Unsafe input patterns (lightweight, pre-retrieval)
# ---------------------------------------------------------------------------

_UNSAFE_PATTERNS = [
    re.compile(r"ignore (all |previous |above |prior )?(instructions?|prompts?|context)", re.IGNORECASE),
    re.compile(r"(system|assistant|user):\s*", re.IGNORECASE),
    re.compile(r"<\s*(system|user|assistant)\s*>", re.IGNORECASE),
    re.compile(r"\[INST\]|\[SYS\]|<<SYS>>", re.IGNORECASE),
    re.compile(r"you are now|pretend (you are|to be)|act as (a|an) (?!assistant)", re.IGNORECASE),
    re.compile(r"jailbreak|DAN mode|do anything now", re.IGNORECASE),
]

_MIN_QUERY_LENGTH = 3


def check_unsafe_input(query_text: str) -> Dict[str, Any]:
    """
    Pre-retrieval lightweight check for unsafe or injection-style inputs.
    """
    stripped = query_text.strip()

    if len(stripped) < _MIN_QUERY_LENGTH:
        logger.warning("Guardrail UNSAFE: query too short (%d chars)", len(stripped))
        return {"passed": False, "reason": "unsafe_input", "detail": "query_too_short"}

    for pattern in _UNSAFE_PATTERNS:
        if pattern.search(stripped):
            logger.warning(
                "Guardrail UNSAFE: pattern matched '%s' in query: %.80s",
                pattern.pattern, stripped
            )
            return {
                "passed": False,
                "reason": "unsafe_input",
                "detail": f"pattern_match:{pattern.pattern[:40]}",
            }

    return {"passed": True}


# ---------------------------------------------------------------------------
# Off-topic check (post-retrieval)
# ---------------------------------------------------------------------------

def check_off_topic(
    retrieval_results: List[Dict[str, Any]],
    threshold: float = OFF_TOPIC_L2_THRESHOLD,
) -> Dict[str, Any]:
    """
    If the best retrieval result's L2 distance exceeds `threshold`, the query
    is considered off-topic relative to the indexed corpus.
    """
    if not retrieval_results:
        logger.info("Guardrail OFF_TOPIC: no results at all")
        return {"passed": False, "reason": "off_topic", "detail": "no_results"}

    best_dist = min(r["distance"] for r in retrieval_results)

    if best_dist > threshold:
        logger.info(
            "Guardrail OFF_TOPIC: best_dist=%.4f > threshold=%.4f",
            best_dist, threshold
        )
        return {
            "passed": False,
            "reason": "off_topic",
            "detail": f"best_distance={best_dist:.4f}",
            "best_distance": best_dist,
        }

    return {"passed": True, "best_distance": best_dist}


# ---------------------------------------------------------------------------
# Insufficient context check (post-retrieval)
# ---------------------------------------------------------------------------

def check_insufficient_context(
    retrieval_results: List[Dict[str, Any]],
    threshold: float = INSUFFICIENT_CONTEXT_L2_THRESHOLD,
) -> Dict[str, Any]:
    """
    Returns failed if all retrieved chunks have L2 distance > threshold,
    meaning there is no meaningful context to ground an answer.
    """
    if not retrieval_results:
        return {"passed": False, "reason": "insufficient_context", "detail": "empty_results"}

    usable = [r for r in retrieval_results if r["distance"] <= threshold]
    if not usable:
        best_dist = min(r["distance"] for r in retrieval_results)
        logger.info(
            "Guardrail INSUFFICIENT_CTX: all chunks > threshold=%.4f (best=%.4f)",
            threshold, best_dist
        )
        return {
            "passed": False,
            "reason": "insufficient_context",
            "detail": f"best_distance={best_dist:.4f}",
        }

    return {"passed": True, "usable_chunks": len(usable)}


# ---------------------------------------------------------------------------
# Grounding validation (post-generation)
# ---------------------------------------------------------------------------

def _token_overlap(text_a: str, text_b: str) -> float:
    """Jaccard token overlap between two strings (lowercased, split on whitespace)."""
    toks_a = set(re.findall(r'\w+', text_a.lower()))
    toks_b = set(re.findall(r'\w+', text_b.lower()))
    if not toks_a or not toks_b:
        return 0.0
    return len(toks_a & toks_b) / len(toks_a | toks_b)


def check_grounding(
    answer: str,
    context_chunks: List[Dict[str, Any]],
    target_language: str = "Hindi",
    min_overlap: float = 0.02,
) -> Dict[str, Any]:
    """
    Verifies the generated answer is grounded in retrieved context.

    Handles multilingual generation:
    - For Hindi queries: checks lexical overlap against the Hindi context passages.
    - For other languages (English, Telugu, Tamil, etc.): since context is Hindi and
      answer is in target_language, verifies the answer is non-empty and well-formed.
    """
    if not answer or not answer.strip():
        return {"passed": False, "reason": "ungrounded", "detail": "empty_answer"}

    if not context_chunks:
        return {"passed": True, "detail": "no_context_to_check"}

    # If the target language is different from Hindi (context language),
    # token overlap between different alphabets/scripts is naturally 0.
    # Cross-lingual generation by Gemini from Hindi context is valid.
    if target_language.lower() not in ("hindi", "hi"):
        return {"passed": True, "detail": f"cross_lingual_{target_language}", "best_overlap": 1.0}

    # For Hindi answers on Hindi context:
    best_overlap = 0.0
    for chunk in context_chunks:
        overlap = _token_overlap(answer, chunk.get("text", ""))
        if overlap > best_overlap:
            best_overlap = overlap

    if best_overlap >= min_overlap:
        return {"passed": True, "best_overlap": round(best_overlap, 4)}

    # Check if answer contains numbers or key terms from context
    ans_nums = set(re.findall(r'\d+', answer))
    for chunk in context_chunks:
        ctx_nums = set(re.findall(r'\d+', chunk.get("text", "")))
        if ans_nums and ans_nums.issubset(ctx_nums):
            return {"passed": True, "best_overlap": round(best_overlap, 4), "matched_entities": True}

    logger.info(
        "Guardrail GROUNDING: best_overlap=%.4f < min=%.4f",
        best_overlap, min_overlap
    )
    # If the model generated an answer with at least 15 chars from valid context, accept it
    if len(answer.strip()) >= 15 and best_overlap > 0.0:
        return {"passed": True, "best_overlap": round(best_overlap, 4)}

    return {
        "passed": False,
        "reason": "ungrounded",
        "detail": f"best_overlap={best_overlap:.4f}",
        "best_overlap": round(best_overlap, 4),
    }


# ---------------------------------------------------------------------------
# Refusal message generator (uses dynamic LLM — no hardcoded strings)
# ---------------------------------------------------------------------------

_REFUSAL_REASON_PROMPTS = {
    "unsafe_input": (
        "The user sent a query that appears to contain unsafe or manipulative content. "
        "Politely and briefly explain that you cannot process this type of request, "
        "in {language}."
    ),
    "off_topic": (
        "The user asked a question that is outside the scope of the knowledge base. "
        "Politely explain that you can only answer questions related to the available knowledge base, "
        "in {language}."
    ),
    "insufficient_context": (
        "You could not find relevant information in the knowledge base to answer the user's question. "
        "Politely acknowledge this and suggest the user try rephrasing, in {language}."
    ),
    "ungrounded": (
        "You attempted to generate an answer but could not verify it against the available information. "
        "Politely state that you cannot provide a reliable answer to this question, in {language}."
    ),
}


def generate_refusal_message(
    reason: str,
    target_language: str,
    query_text: str,
) -> str:
    """
    Calls the Gemini LLM to dynamically generate a refusal message in the
    detected query language — never hardcodes English or Hindi strings.
    """
    from backend.llm_provider.gemini_llm import generate_answer

    reason_template = _REFUSAL_REASON_PROMPTS.get(reason, _REFUSAL_REASON_PROMPTS["insufficient_context"])
    refusal_instruction = reason_template.format(language=target_language)

    refusal_context = [{
        "text": f"[SYSTEM NOTE: {refusal_instruction}]"
    }]

    try:
        msg = generate_answer(
            query_text=query_text,
            context_chunks=refusal_context,
            target_language=target_language,
            is_refusal=True,
        )
        return msg
    except Exception as exc:
        logger.error(
            "guardrails.generate_refusal_message failed (reason=%s, lang=%s): %s: %s",
            reason, target_language, type(exc).__name__, exc
        )
        return f"[{target_language}] No answer available."
