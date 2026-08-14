import os
import json
import numpy as np
import faiss
from backend.config import FAISS_INDEX_DIR, METADATA_PATH, CHUNK_SIZE, CHUNK_OVERLAP
from backend.dataset_ingestion.loader import load_subset_data
from backend.chunking.chunker import chunk_text
from backend.embeddings.embedder import embed_texts

def build_index(force=False):
    """
    Builds the FAISS index and metadata store from the subset data.
    If the index files already exist, it will skip building unless force=True.
    """
    # Check if index and metadata already exist
    index_file = os.path.join(FAISS_INDEX_DIR, "index.faiss")
    if os.path.exists(index_file) and os.path.exists(METADATA_PATH) and not force:
        print("Persisted FAISS index and metadata found. Skipping build.")
        return

    print("Building FAISS index and metadata from subset...")
    records = load_subset_data()
    
    chunks_metadata = []
    chunk_texts_list = []
    
    # Process each record and its passages
    for r in records:
        q_id = r.get("query_id")
        source_q = r.get("query")
        source_ans = r.get("Answer")
        passages = r.get("passages", {})
        
        # We index the translated (Hindi) passages
        translated_passages = passages.get("Translated_passages", [])
        is_selected_flags = passages.get("is_selected", [0]*len(translated_passages))
        
        for p_idx, p_text in enumerate(translated_passages):
            is_sel = is_selected_flags[p_idx] if p_idx < len(is_selected_flags) else 0
            
            # Chunk the passage
            p_chunks = chunk_text(p_text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
            
            for c_idx, chunk in enumerate(p_chunks):
                chunk_text_str = chunk["text"]
                chunk_texts_list.append(chunk_text_str)
                
                chunks_metadata.append({
                    "chunk_id": len(chunks_metadata),
                    "query_id": q_id,
                    "text": chunk_text_str,
                    "passage_index": p_idx,
                    "chunk_index": c_idx,
                    "is_selected": is_sel,
                    "source_query": source_q,
                    "source_answer": source_ans
                })
                
    if not chunk_texts_list:
        print("No chunks found to index.")
        return
        
    print(f"Total chunks created: {len(chunk_texts_list)}")
    
    # Generate embeddings
    print("Generating embeddings for all chunks...")
    embeddings = embed_texts(chunk_texts_list)
    dimension = embeddings.shape[1]
    print(f"Embeddings shape: {embeddings.shape}, Dimension: {dimension}")
    
    # Create FAISS index
    index = faiss.IndexFlatL2(dimension)
    # FAISS expects float32
    index.add(embeddings.astype('float32'))
    
    # Save index and metadata
    os.makedirs(FAISS_INDEX_DIR, exist_ok=True)
    faiss.write_index(index, index_file)
    
    with open(METADATA_PATH, "w", encoding="utf-8") as f:
        json.dump(chunks_metadata, f, ensure_ascii=False, indent=2)
        
    print(f"FAISS index and metadata successfully saved to disk.")

if __name__ == "__main__":
    build_index(force=True)
