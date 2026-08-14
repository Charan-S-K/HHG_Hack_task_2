import requests
from backend.config import SARVAM_API_KEY

def transcribe_audio(audio_bytes, filename="audio.wav"):
    """
    Sends binary audio data to Sarvam STT REST API for transcription/translation.
    """
    if not SARVAM_API_KEY:
        raise ValueError("SARVAM_API_KEY is not set. Please add it to your .env file.")
        
    url = "https://api.sarvam.ai/speech-to-text"
    headers = {
        "api-subscription-key": SARVAM_API_KEY
    }
    
    # Send request with multipart/form-data
    files = {
        "file": (filename, audio_bytes, "audio/wav")
    }
    data = {
        "model": "saaras:v3",
        "mode": "transcribe"  # Default transcription mode
    }
    
    print(f"Sending audio request to Sarvam STT... (file size: {len(audio_bytes)} bytes)")
    response = requests.post(url, headers=headers, files=files, data=data)
    
    if response.status_code != 200:
        print(f"Sarvam STT failed (code {response.status_code}): {response.text}")
        response.raise_for_status()
        
    res_json = response.json()
    transcript = res_json.get("transcript", "")
    language_code = res_json.get("language_code", None)
    print(f"Transcription successful: '{transcript}', language_code: '{language_code}'")
    return transcript, language_code
