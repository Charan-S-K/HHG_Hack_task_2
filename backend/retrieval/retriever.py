import os
import json
import faiss
import numpy as np
from backend.config import FAISS_INDEX_DIR, METADATA_PATH, RETRIEVAL_K
from backend.embeddings.embedder import embed_query

_index = None
_metadata = None

def load_retriever():
    """
    Loads FAISS index and metadata. Bypasses reloading if already in memory.
    """
    global _index, _metadata
    if _index is None or _metadata is None:
        index_file = os.path.join(FAISS_INDEX_DIR, "index.faiss")
        if not os.path.exists(index_file) or not os.path.exists(METADATA_PATH):
            raise FileNotFoundError("FAISS index or metadata files not found. Please build the index first.")
            
        print("Loading FAISS index and metadata...")
        _index = faiss.read_index(index_file)
        
        with open(METADATA_PATH, "r", encoding="utf-8") as f:
            _metadata = json.load(f)
            
        print(f"Loaded index size: {_index.ntotal}, Metadata records: {len(_metadata)}")
        
    return _index, _metadata

def retrieve_top_k(query_text, k=RETRIEVAL_K):
    """
    Embeds query and searches the FAISS index.
    Returns a list of matching metadata dictionaries.
    """
    index, metadata = load_retriever()
    
    # Generate query embedding
    query_emb = embed_query(query_text).reshape(1, -1).astype('float32')
    
    # Search index
    distances, indices = index.search(query_emb, k)
    
    results = []
    for dist, idx in zip(distances[0], indices[0]):
        if idx < 0 or idx >= len(metadata):
            continue
        record = metadata[idx].copy()
        record["distance"] = float(dist)
        results.append(record)
        
    return results
