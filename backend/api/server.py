import os
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.config import PROJECT_ROOT, HOST, PORT
from backend.stt.sarvam_stt import transcribe_audio
from backend.retrieval.retriever import retrieve_top_k
from backend.llm_provider.gemini_llm import generate_answer
from backend.utils.lang_detect import detect_language_name

app = FastAPI(title="HH Goa Voice Radar API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class QueryRequest(BaseModel):
    query: str
    language_code: str = None

class QueryResponse(BaseModel):
    question: str
    answer: str
    retrieved_chunk_count: int
    context: list

@app.get("/api/status")
def get_status():
    """
    Status and healthcheck endpoint.
    """
    return {
        "status": "online",
        "service": "HH Goa Voice Radar",
        "environment": "RAG RUN 1"
    }

@app.post("/api/stt")
async def handle_stt(file: UploadFile = File(...)):
    """
    Receives an audio file upload, transcribes it using Sarvam AI, and returns the transcript.
    """
    try:
        audio_bytes = await file.read()
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Uploaded audio file is empty.")
            
        transcript, language_code = transcribe_audio(audio_bytes, filename=file.filename)
        return {"transcript": transcript, "language_code": language_code}
    except Exception as e:
        print(f"Error during transcription: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/query", response_model=QueryResponse)
def handle_query(payload: QueryRequest):
    """
    Receives a query text, retrieves matching passages from the FAISS index, 
    calls Gemini LLM, and returns the structured answer.
    """
    query_text = payload.query.strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="Query text cannot be empty.")
        
    try:
        # 1. Detect target language based on query text and STT hints
        target_language = detect_language_name(query_text, payload.language_code)
        
        # 2. Retrieve top-k context chunks
        context_chunks = retrieve_top_k(query_text)
        
        # 3. Call LLM to generate answer
        answer = generate_answer(query_text, context_chunks, target_language=target_language)
        
        # 4. Formulate response
        return QueryResponse(
            question=query_text,
            answer=answer,
            retrieved_chunk_count=len(context_chunks),
            context=[{
                "text": chunk["text"],
                "query_id": chunk["query_id"],
                "distance": chunk["distance"],
                "is_selected": chunk["is_selected"]
            } for chunk in context_chunks]
        )
    except Exception as e:
        print(f"Error during RAG pipeline: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Mount frontend static files
frontend_dir = os.path.join(PROJECT_ROOT, "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
else:
    @app.get("/")
    def read_root():
        return {"message": "HH Goa Voice Radar API running. Frontend folder not found."}
