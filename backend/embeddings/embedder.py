from sentence_transformers import SentenceTransformer
from backend.config import EMBEDDING_MODEL_NAME

_model = None

def get_embedding_model():
    """
    Singleton provider for the local embedding model.
    """
    global _model
    if _model is None:
        print(f"Loading embedding model '{EMBEDDING_MODEL_NAME}'...")
        # Force CPU device to avoid MPS/CUDA overhead
        model = SentenceTransformer(EMBEDDING_MODEL_NAME, device="cpu")
        
        # Apply 8-bit dynamic quantization to keep memory footprint low
        import torch
        import gc
        try:
            model = torch.quantization.quantize_dynamic(
                model, {torch.nn.Linear}, dtype=torch.qint8
            )
            print("Embedding model dynamically quantized to 8-bit successfully.")
        except Exception as q_err:
            print(f"Dynamic quantization skipped: {q_err}")
            
        _model = model
        gc.collect()
        print("Embedding model loaded successfully.")
    return _model

def embed_texts(texts):
    """
    Generates embeddings for a list of texts.
    Returns a numpy array of embeddings.
    """
    model = get_embedding_model()
    # Prepend 'passage: ' prefix required by E5 models
    prefixed_texts = [f"passage: {t}" for t in texts]
    return model.encode(prefixed_texts, convert_to_numpy=True)

def embed_query(query):
    """
    Generates embedding for a single text query.
    Returns a numpy array representation.
    """
    model = get_embedding_model()
    # Prepend 'query: ' prefix required by E5 models
    prefixed_query = f"query: {query}"
    return model.encode(prefixed_query, convert_to_numpy=True)
