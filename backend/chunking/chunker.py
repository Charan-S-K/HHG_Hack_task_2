import re

def clean_text(text):
    """
    Cleans text by normalizing whitespace, removing extra line breaks, and stripping boundaries.
    """
    if not text:
        return ""
    # Replace multiple spaces/newlines with a single space
    cleaned = re.sub(r'\s+', ' ', text)
    return cleaned.strip()

def chunk_text(text, chunk_size=500, overlap=50):
    """
    Chunks a text using a fixed-size character window with overlapping boundaries.
    Returns a list of dicts with the chunk text, start position, and end position.
    """
    text = clean_text(text)
    if not text:
        return []
        
    if len(text) <= chunk_size:
        return [{"text": text, "start_char": 0, "end_char": len(text)}]
        
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk_str = text[start:end]
        chunks.append({
            "text": chunk_str,
            "start_char": start,
            "end_char": min(end, len(text))
        })
        start += (chunk_size - overlap)
        if start >= len(text):
            break
            
    return chunks
