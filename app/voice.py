"""
Voice input — Phase 5.3.

Records audio from the default microphone and transcribes with Whisper.
Endpoint: POST /voice/transcribe — accepts multipart audio file upload.
Client records via MediaRecorder API, sends WebM/MP4 blob, gets back text.

Whisper model: "base" (~74MB, fast on M2, good accuracy for English).
Model is loaded once at first call (lazy init, ~2s warm-up).
"""

import tempfile
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_model = None  # lazy-loaded


def _get_model():
    global _model
    if _model is None:
        import whisper
        logger.info("Loading Whisper base model…")
        _model = whisper.load_model("base")
        logger.info("Whisper ready")
    return _model


def transcribe_audio(audio_bytes: bytes, filename: str = "audio.webm") -> dict:
    """
    Transcribe audio bytes using Whisper.
    Returns {"text": "...", "language": "en"} or {"error": "..."}.
    """
    if not audio_bytes:
        return {"error": "No audio data received"}

    try:
        model = _get_model()

        # Write to temp file — Whisper needs a file path
        suffix = Path(filename).suffix or ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            result = model.transcribe(tmp_path, language=None, fp16=False)
            text = result.get("text", "").strip()
            lang = result.get("language", "")
            return {"text": text, "language": lang}
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    except Exception as exc:
        logger.error("Whisper transcription error: %s", exc)
        return {"error": str(exc)}
