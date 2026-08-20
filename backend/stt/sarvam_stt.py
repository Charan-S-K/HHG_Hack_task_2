"""
Sarvam AI STT client — RUN 2.
Updated: timeout parameter support, real exception propagation.
"""

import os
import requests
import logging
from backend.config import STT_TIMEOUT

logger = logging.getLogger(__name__)


def transcribe_audio(audio_bytes: bytes, filename: str = "audio.wav", timeout: int = STT_TIMEOUT):
    """
    Sends binary audio data to Sarvam STT REST API for transcription.

    Args:
        audio_bytes: Raw audio bytes.
        filename:    Filename hint (controls MIME type inference).
        timeout:     HTTP request timeout in seconds.

    Returns:
        (transcript: str, language_code: str | None)

    Raises real exceptions — never masks them behind a generic message.
    """
    api_key = os.getenv("SARVAM_API_KEY")
    if not api_key:
        raise ValueError(
            "SARVAM_API_KEY is not set. Please add it to your .env file."
        )

    url = "https://api.sarvam.ai/speech-to-text"
    headers = {"api-subscription-key": api_key.strip()}

    # Determine correct MIME type from filename extension
    ext = os.path.splitext(filename)[1].lower()
    mime_type = "audio/wav"
    if ext == ".webm":
        mime_type = "audio/webm"
    elif ext in (".ogg", ".opus"):
        mime_type = "audio/ogg"
    elif ext in (".mp4", ".m4a"):
        mime_type = "audio/mp4"
    elif ext == ".mp3":
        mime_type = "audio/mpeg"

    files = {"file": (filename, audio_bytes, mime_type)}
    data  = {"model": "saaras:v3", "mode": "transcribe"}

    logger.info("Sarvam STT request: %d bytes, file=%s", len(audio_bytes), filename)

    response = requests.post(url, headers=headers, files=files, data=data, timeout=timeout)

    if response.status_code != 200:
        logger.error(
            "Sarvam STT HTTP %d: %s", response.status_code, response.text[:300]
        )
        response.raise_for_status()

    res_json = response.json()
    transcript    = res_json.get("transcript", "")
    language_code = res_json.get("language_code", None)

    logger.info("Sarvam STT result: transcript='%.60s', lang=%s", transcript, language_code)
    return transcript, language_code
