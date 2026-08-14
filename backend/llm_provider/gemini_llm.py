import requests
from backend.config import GEMINI_API_KEY

def generate_answer(query_text, context_chunks, target_language="Hindi"):
    """
    Calls the Gemini API (free-tier 3.5 Flash Lite) via its direct REST endpoint 
    to generate a grounded answer using retrieved contexts in the target language.
    """
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set. Please add it to your .env file.")
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={GEMINI_API_KEY}"
    
    # Construct context string
    context_str = "\n\n".join([f"--- संदर्भ {i+1} ---\n{chunk['text']}" for i, chunk in enumerate(context_chunks)])
    
    # Define prompt instructing the LLM to answer based strictly on context in the target language,
    # and to generate its own refusal message dynamically in that same target language.
    prompt = (
        f"You are an assistant that answers the user's question in {target_language} based on the provided context (which is in Hindi).\n"
        f"Please answer the question in {target_language} using ONLY the provided context.\n"
        f"If the answer cannot be found in the provided context, respond with a refusal message (e.g., stating that you cannot find the answer in the context) written in {target_language}.\n\n"
        f"Context:\n{context_str}\n\n"
        f"Question: {query_text}\n"
        f"Answer (in {target_language}):"
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
    
    print(f"Calling Gemini API to generate answer in {target_language} for: '{query_text[:40]}...'")
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
