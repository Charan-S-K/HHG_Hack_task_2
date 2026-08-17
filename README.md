# HH Goa Voice Radar — RUN 3 Refinement

A multilingual, voice-enabled RAG (Retrieval-Augmented Generation) system built on FAISS + sentence-transformers (local) + Gemini API (generation) + Sarvam AI (STT). Supports queries in any Indian language and returns grounded answers in the same language the question was asked.

> [!NOTE]
> **Multilingual Grounding Design Choice**: Answers in non-Hindi languages are LLM-generated translations grounded in Hindi source content, not retrieved from native-language passages. This is a deliberate design choice to prevent index fragmentation while preserving grounding fidelity.

### Paid Services & Free-Tier Limits
The app requires no paid services beyond the explicitly approved developer API keys. It relies upon the following limits:
* **Gemini API (gemini-flash-lite-latest)**: Relies on free-tier request limits (15 RPM / 1500 RPD).
* **Sarvam AI STT API (saaras:v3)**: Relies on developer subscription free usage credits.
* **Embedding Model (multilingual-e5-small)**: Runs locally on CPU (unlimited, zero-cost).
* **Vector Index (FAISS)**: Runs locally on CPU (unlimited, zero-cost).

---

## What's New in RUN 2

| Feature | Detail |
|---------|--------|
| **Multi-strategy chunking** | 4 strategies: `fixed` (RUN 1), `sentence`, `metadata`, `hybrid` (default) |
| **Per-strategy FAISS indexes** | Each strategy has its own persisted index under `data/faiss_index/<strategy>/` |
| **Retrieval refinement** | Top-k tuning, metadata filtering, dedup, context compression |
| **Guardrails** | Off-topic, unsafe input, grounding validation, insufficient context — all in query language |
| **Pipeline harness** | 9 explicit stages, per-stage timing, retries, graceful error recovery |
| **Real benchmark** | 100 queries from committed subset; P50/P70/P100/avg/min/max; STT excluded explicitly |
| **HOLOGRAM mode** | Animated SVG orb with 6 distinct visual states |
| **TAP TO SPEAK mode** | Mic + live transcript + answer + expandable Sources accordion |
| **Performance dashboard** | Live benchmark trigger + real latency table in UI |
| **Prompt injection resistance** | DATA/INSTRUCTIONS separation in LLM prompt template |
| **Structured API response** | `refused`, `reason`, `strategy`, `latencies`, `guardrail_decisions`, `context` |

---

## Technical Stack

| Component | Technology |
|-----------|-----------|
| API Server | FastAPI + uvicorn |
| Vector Index | FAISS IndexFlatL2 (384-dim) |
| Embedding Model | `intfloat/multilingual-e5-small` |
| LLM | Google Gemini 2.0 Flash Lite (REST) |
| STT | Sarvam AI `saaras:v3` (REST) |
| Language Detection | `langdetect` + Unicode script ranges + `langcodes` |
| Python | 3.11+ |

---

## Directory Layout

```
/
├── data/
│   ├── subset.jsonl                      # Committed 100-record subset (RUN 1, seed=42)
│   ├── faiss_index/
│   │   ├── fixed/                         # Fixed-size chunking index (RUN 1 migrated)
│   │   ├── sentence/                      # Sentence-boundary index
│   │   ├── metadata/                      # Metadata-aware index
│   │   └── hybrid/                        # Hybrid index (production default)
│   └── benchmark_results.json             # Live benchmark output (gitignored)
├── backend/
│   ├── config.py                          # All settings + env loading
│   ├── dataset_ingestion/loader.py
│   ├── chunking/chunker.py                # 4 strategies + dispatcher
│   ├── embeddings/embedder.py             # multilingual-e5-small singleton
│   ├── vector_store/indexer.py            # Multi-strategy index builder
│   ├── retrieval/retriever.py             # Retrieve + dedup + compress
│   ├── guardrails/guardrails.py           # 4 guardrail checks + dynamic refusals
│   ├── pipeline/pipeline.py               # 9-stage orchestrated harness
│   ├── benchmark/harness.py               # Real latency benchmark
│   ├── stt/sarvam_stt.py
│   ├── llm_provider/gemini_llm.py         # Injection-resistant prompt template
│   ├── utils/lang_detect.py
│   └── api/server.py                      # FastAPI endpoints
├── frontend/
│   ├── index.html                         # HOLOGRAM + TAP TO SPEAK + dashboard
│   ├── style.css
│   └── app.js
├── DATA_HANDOFF.md                        # Dataset + index reproducibility
├── RETRIEVAL_NOTES.md                     # Strategy comparison + benchmark results
├── requirements.txt
└── .env.example
```

---

## Setup & Running

### 1. Create virtual environment

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env with your SARVAM_API_KEY and GEMINI_API_KEY
```

### 4. Build indexes

```bash
# Build all 4 strategy indexes (required for first run):
python -m backend.vector_store.indexer --strategy all

# Or build just the production default:
python -m backend.vector_store.indexer --strategy hybrid
```

### 5. Start the server

```bash
uvicorn backend.api.server:app --reload --port 8000
```

Open `http://127.0.0.1:8000` in your browser.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/status` | Health check |
| POST | `/api/stt` | Audio → transcript (Sarvam AI) |
| POST | `/api/query` | Full RAG pipeline (text query) |
| POST | `/api/benchmark/run` | Trigger live benchmark |
| GET | `/api/benchmark/results` | Get benchmark results |
| POST | `/api/index/build` | Build a strategy index |

### Query Response Structure

```json
{
  "request_id": "abc12345",
  "question": "...",
  "answer": "...",
  "refused": false,
  "refusal_reason": "",
  "strategy": "hybrid",
  "retrieved_chunk_count": 5,
  "latencies": { "embedding_retrieval": 0.08, "generation": 1.2, ... },
  "total_latency": 1.42,
  "excl_stt_latency": 1.42,
  "guardrail_decisions": { "off_topic": { "passed": true }, ... },
  "context": [ { "text": "...", "relevance_score": 0.85, "strategy": "hybrid", ... } ]
}
```

---

## Guardrails

| Guardrail | Trigger | Response |
|-----------|---------|----------|
| Unsafe input | Regex/injection patterns | Dynamic refusal in query language |
| Off-topic | L2 distance > 1.5 | Dynamic refusal in query language |
| Insufficient context | All distances > 2.0 | Dynamic refusal in query language |
| Ungrounded answer | Token overlap < 10% | Dynamic refusal in query language |

All refusals are generated by Gemini in the detected query language. No hardcoded English/Hindi strings.

---

## Documentation

- [DATA_HANDOFF.md](DATA_HANDOFF.md) — Dataset + index reproducibility
- [RETRIEVAL_NOTES.md](RETRIEVAL_NOTES.md) — Strategy comparison + benchmark results
- [DATASET_NOTES.md](DATASET_NOTES.md) — Dataset schema and notes