import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Base directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = BASE_DIR
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
SUBSET_PATH = os.path.join(DATA_DIR, "subset.jsonl")
METADATA_PATH = os.path.join(DATA_DIR, "metadata.json")  # RUN 1 compat alias

# Per-strategy index directories
FAISS_INDEX_BASE = os.path.join(DATA_DIR, "faiss_index")
FAISS_INDEX_DIR = os.path.join(FAISS_INDEX_BASE, "fixed")   # RUN 1 baseline (renamed)
FAISS_INDEX_SENTENCE = os.path.join(FAISS_INDEX_BASE, "sentence")
FAISS_INDEX_METADATA = os.path.join(FAISS_INDEX_BASE, "metadata")
FAISS_INDEX_HYBRID = os.path.join(FAISS_INDEX_BASE, "hybrid")

STRATEGY_INDEX_DIRS = {
    "fixed":    FAISS_INDEX_DIR,
    "sentence": FAISS_INDEX_SENTENCE,
    "metadata": FAISS_INDEX_METADATA,
    "hybrid":   FAISS_INDEX_HYBRID,
}

# API Keys
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Server configuration
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "127.0.0.1")

# Chunking settings (RUN 1 baseline)
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50

# Retrieval settings
RETRIEVAL_K = int(os.getenv("RETRIEVAL_K", "5"))
RETRIEVAL_STRATEGY = os.getenv("RETRIEVAL_STRATEGY", "hybrid")  # production default

# Guardrail thresholds (calibrated from real distance measurements)
# In-topic distances: 0.18–0.33, Off-topic: 0.37–0.45. Threshold at 0.365.
OFF_TOPIC_L2_THRESHOLD = float(os.getenv("OFF_TOPIC_L2_THRESHOLD", "0.365"))
INSUFFICIENT_CONTEXT_L2_THRESHOLD = float(os.getenv("INSUFFICIENT_CONTEXT_L2_THRESHOLD", "0.45"))
DEDUP_SIMILARITY_THRESHOLD = float(os.getenv("DEDUP_SIMILARITY_THRESHOLD", "0.92"))
GROUNDING_MIN_OVERLAP = float(os.getenv("GROUNDING_MIN_OVERLAP", "0.10"))
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "2000"))

# External call timeouts & retries
STT_TIMEOUT = int(os.getenv("STT_TIMEOUT", "20"))
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "30"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))
STT_MAX_RETRIES = int(os.getenv("STT_MAX_RETRIES", "1"))

# Embedding settings
EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-small"

# Benchmark settings
BENCHMARK_SEED = 42
BENCHMARK_MAX_QUERIES = int(os.getenv("BENCHMARK_MAX_QUERIES", "100"))
BENCHMARK_RESULTS_PATH = os.path.join(DATA_DIR, "benchmark_results.json")
