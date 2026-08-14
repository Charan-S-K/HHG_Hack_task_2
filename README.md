# HH Goa Voice Radar (RAG Voice Assistant)

HH Goa Voice Radar is a voice-enabled RAG (Retrieval-Augmented Generation) system built using local embedding search (FAISS + sentence-transformers) and API-based generation (Gemini API) and transcription (Sarvam STT). It targets queries in Hindi using the `ai4bharat/MSMARCO-XI` dataset.

---

## Technical Stack & Environment

This repository has pinned the following runtime versions for reproducibility:
*   **Python**: `3.13.2` (Specified in [runtime.txt](file:///Users/charantejsk/Documents/HHG/HHG_TASK_2/runtime.txt))
*   **Node.js**: `24.14.0` (Specified in [.nvmrc](file:///Users/charantejsk/Documents/HHG/HHG_TASK_2/.nvmrc))
*   **Key Python Dependencies**:
    *   `fastapi` (API Web Server)
    *   `faiss-cpu` (Vector Indexing & L2 Similarity Search)
    *   `sentence-transformers` (Local embeddings using `all-MiniLM-L6-v2`)
    *   `datasets` (Loading parquet data structures)
    *   `pandas`, `pyarrow` (Parquet parsing)

Exact pip versions are pinned in [requirements.txt](file:///Users/charantejsk/Documents/HHG/HHG_TASK_2/requirements.txt).

---

## Directory Layout

```
/
├── data/
│   ├── subset.jsonl                 # Persistent dataset subset (100 records)
│   ├── faiss_index/                 # Persisted FAISS index
│   └── metadata.json                # Chunk metadata mapping
├── backend/
│   ├── config.py                    # Config loading (from env)
│   ├── dataset_ingestion/
│   │   └── loader.py                # Loader for JSONL subset
│   ├── chunking/
│   │   └── chunker.py               # Text cleaning and fixed-size overlap chunking
│   ├── embeddings/
│   │   └── embedder.py              # Local sentence-transformers loader
│   ├── vector_store/
│   │   └── indexer.py               # FAISS index builder/loader
│   ├── retrieval/
│   │   └── retriever.py             # Top-k vector retriever
│   ├── stt/
│   │   └── sarvam_stt.py            # Sarvam AI STT client (REST)
│   ├── llm_provider/
│   │   └── gemini_llm.py            # Gemini RAG answer generator
│   └── api/
│       └── server.py                # FastAPI server (STT, Retrieve, and RAG endpoints)
├── frontend/
│   ├── index.html                   # HTML structure
│   ├── style.css                    # Styling for the UI (Dark green, cream, pink)
│   └── app.js                       # Audio recording and API handling
├── .env.example
├── .gitignore
├── requirements.txt
├── runtime.txt
└── .nvmrc
```

---

## Setup & Running Instructions

### 1. Set Up Virtual Environment

Create and activate a virtual environment, then install requirements:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment Secrets

Create a `.env` file in the root directory:

```bash
cp .env.example .env
```

Open `.env` and fill in your API keys:
*   `SARVAM_API_KEY`: Get from the [Sarvam AI Dashboard](https://dashboard.sarvam.ai/).
*   `GEMINI_API_KEY`: Get a free key from [Google AI Studio](https://aistudio.google.com/).

### 3. Build/Verify the Vector Index

The FAISS index has already been built and committed to the repository at [data/faiss_index/index.faiss](file:///Users/charantejsk/Documents/HHG/HHG_TASK_2/data/faiss_index/index.faiss). You can optionally rebuild it by running:

```bash
python3 -m backend.vector_store.indexer
```

### 4. Run the Backend API & Frontend Server

Start the uvicorn development server:

```bash
uvicorn backend.api.server:app --reload --port 8000
```

The application will be accessible at `http://127.0.0.1:8000`.

---

## Verification & Testing Fallback

If you are running the application in a headless remote server or environment without microphone support:
*   **Double-click** the microphone button on the frontend UI to prompt a text input dialog, allowing you to submit text queries directly to the RAG retriever and generator.

---

## Documentation

*   [DATASET_NOTES.md](file:///Users/charantejsk/Documents/HHG/HHG_TASK_2/DATASET_NOTES.md): Dataset schema, languages, and sampling rationale.
*   [DATA_HANDOFF.md](file:///Users/charantejsk/Documents/HHG/HHG_TASK_2/DATA_HANDOFF.md): Technical parameters for dataset reproduction (seed, split, revision).