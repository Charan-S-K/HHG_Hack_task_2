from langdetect import detect, LangDetectException

def detect_language_name(query_text: str, stt_language_code: str = None) -> str:
    """
    Detects the language of the query text.
    Returns 'Hindi' or 'English'.
    """
    # 1. Check if STT language code is provided and use it directly
    if stt_language_code:
        # Standardize: take primary code (e.g. 'hi-IN' -> 'hi')
        code = stt_language_code.split("-")[0].lower()
        if code == "hi":
            return "Hindi"
        elif code == "en":
            return "English"
            
    # 2. Fallback: use langdetect library
    try:
        detected_code = detect(query_text)
        code = detected_code.split("-")[0].lower()
        if code == "hi":
            return "Hindi"
        elif code == "en":
            return "English"
    except LangDetectException:
        pass
        
    # 3. Fallback: check Devanagari Unicode range
    if any("\u0900" <= char <= "\u097f" for char in query_text):
        return "Hindi"
        
    return "English"
