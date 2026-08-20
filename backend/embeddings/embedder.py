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
        
        # Cast to bfloat16 to cut memory footprint in half (~230MB)
        import torch
        import gc
        try:
            model = model.to(torch.bfloat16)
            print("Embedding model cast to bfloat16 successfully.")
        except Exception as err:
            print(f"Failed to cast to bfloat16: {err}")
            
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
