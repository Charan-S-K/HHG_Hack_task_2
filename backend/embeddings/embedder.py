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
        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
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
