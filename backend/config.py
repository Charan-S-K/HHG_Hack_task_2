import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Base directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = BASE_DIR
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
FAISS_INDEX_DIR = os.path.join(DATA_DIR, "faiss_index")
METADATA_PATH = os.path.join(DATA_DIR, "metadata.json")
SUBSET_PATH = os.path.join(DATA_DIR, "subset.jsonl")

# API Keys
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Server configuration
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "127.0.0.1")

# Chunking settings
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
RETRIEVAL_K = 3

# Embedding settings
EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-small"
