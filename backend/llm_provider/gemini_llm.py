import requests
from backend.config import GEMINI_API_KEY

def generate_answer(query_text, context_chunks):
    """
    Calls the Gemini API (free-tier 1.5 Flash) via its direct REST endpoint 
    to generate a grounded answer using retrieved contexts.
    """
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set. Please add it to your .env file.")
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    # Construct context string
    context_str = "\n\n".join([f"--- संदर्भ {i+1} ---\n{chunk['text']}" for i, chunk in enumerate(context_chunks)])
    
    # Define prompt instructing the LLM to answer in Hindi based strictly on context
    prompt = (
        "आप एक सहायक हैं जो निम्नलिखित संदर्भ (Context) के आधार पर उपयोगकर्ता के प्रश्न का उत्तर देता है।\n"
        "कृपया प्रदान किए गए संदर्भ का उपयोग करके उत्तर दें। यदि संदर्भ में उत्तर नहीं मिल सकता है, "
        "तो सीधे कहें: 'मुझे खेद है, लेकिन मुझे प्रदान किए गए संदर्भ में इसका उत्तर नहीं मिला।'\n\n"
        f"संदर्भ:\n{context_str}\n\n"
        f"प्रश्न: {query_text}\n"
        "उत्तर (हिंदी में):"
    )
    
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }
    
    headers = {
        "Content-Type": "application/json"
    }
    
    print(f"Calling Gemini API to generate answer for: '{query_text[:40]}...'")
    response = requests.post(url, headers=headers, json=payload)
    
    if response.status_code != 200:
        print(f"Gemini API failed (code {response.status_code}): {response.text}")
        response.raise_for_status()
        
    res_json = response.json()
    try:
        answer = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError) as e:
        print("Failed to parse Gemini response structure:", res_json)
        raise ValueError("Error parsing response from Gemini API.") from e
        
    print(f"Gemini generation successful. Length: {len(answer)}")
    return answer
