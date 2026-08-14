import langcodes
from langcodes.tag_parser import LanguageTagError
from langdetect import detect, LangDetectException

def detect_language_name(query_text: str, stt_language_code: str = None) -> str:
    """
    Detects the language of the query text and maps it to its full English name
    (e.g., 'Telugu', 'Tamil', 'Bengali', 'Hindi', 'English', etc.) using the
    langcodes library. Falls back gracefully to 'English' if parsing fails.
    """
    raw_code = None

    # 1. Check if STT language code is provided and use it directly
    if stt_language_code:
        # Standardize: take primary code (e.g. 'hi-IN' -> 'hi')
        raw_code = stt_language_code.split("-")[0].lower()
            
    # 2. Fallback: use langdetect library
    if not raw_code:
        try:
            detected_code = detect(query_text)
            raw_code = detected_code.split("-")[0].lower()
        except LangDetectException:
            pass
            
    # 3. Fallback: check Devanagari Unicode range
    if not raw_code:
        if any("\u0900" <= char <= "\u097f" for char in query_text):
            raw_code = "hi"

    # 4. If no code was resolved, default to "en"
    if not raw_code:
        raw_code = "en"

    # 5. Map code to full language name using langcodes library
    try:
        lang = langcodes.Language.get(raw_code)
        name = lang.display_name()
        if name:
            # Map "Bangla" -> "Bengali"
            if name.lower() == "bangla":
                return "Bengali"
            return name
    except LanguageTagError:
        pass
        
    # Deliberate fallback-of-last-resort: English
    # Unrecognized or garbage code falls back to English here.
    return "English"
