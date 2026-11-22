"""Speech to text on the server: a local Whisper model, so the author's voice stays here.

The model is loaded on the first request and kept: a few seconds the first time, then a
short note takes about as long as it was spoken, on the CPU."""

import io
import threading

from app.config import settings

_model = None
_lock = threading.Lock()


def _load():
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel  # heavy: only when someone speaks

            _model = WhisperModel(
                settings.whisper_model,
                device="cpu",
                compute_type="int8",
                download_root=str(settings.data_dir / "whisper"),
            )
    return _model


def decode(audio: bytes, rate: int = 16_000):
    """A recording (webm, ogg, mp4, wav) as 16 kHz mono float samples, decoded by PyAV.
    faster-whisper's own decoder passes an argument newer PyAV no longer takes."""
    import av
    import numpy as np

    resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
    chunks = []
    with av.open(io.BytesIO(audio), mode="r") as container:
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
    for out in resampler.resample(None):  # what the resampler still holds
        chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def transcribe(audio: bytes, language: str | None = None) -> str:
    """The words of a recording; no ffmpeg needed."""
    segments, _ = _load().transcribe(
        decode(audio), language=language or None, beam_size=5, vad_filter=True
    )
    return " ".join(s.text.strip() for s in segments).strip()
