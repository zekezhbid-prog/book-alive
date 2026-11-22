from fastapi import APIRouter, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app import voice

router = APIRouter(prefix="/api", tags=["voice"])

# A few minutes of compressed speech; anything bigger is no note.
MAX_AUDIO = 15 * 1024 * 1024
LANGUAGES = {"", "ru", "be", "uk", "en", "pl", "de"}


class Transcript(BaseModel):
    text: str


@router.post("/transcribe")
def transcribe(file: UploadFile, language: str = Form("")) -> Transcript:
    """Voice input for the card's "Improve" and the book chat. A plain function: FastAPI
    runs it in a worker thread, the event loop is never held by the model."""
    audio = file.file.read(MAX_AUDIO + 1)
    if not audio:
        raise HTTPException(422, "audio_empty")
    if len(audio) > MAX_AUDIO:
        raise HTTPException(413, "audio_too_long")
    if language not in LANGUAGES:
        raise HTTPException(422, "bad_language")
    try:
        text = voice.transcribe(audio, language or None)
    except Exception as exc:  # a broken recording is the user's to retry
        raise HTTPException(422, "audio_unreadable") from exc
    return Transcript(text=text)
