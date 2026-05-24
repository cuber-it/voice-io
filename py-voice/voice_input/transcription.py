"""Whisper-based transcription — converts audio arrays to text."""
from __future__ import annotations

import logging
import threading

import numpy as np

log = logging.getLogger(__name__)

# ── Hallucination filter ──────────────────────────────────────────────────────

_HALLUCINATIONS_EXACT = {
    "thank you", "thanks", "thanks for watching", "thanks for listening",
    "bye", "goodbye", "see you", "see you next time",
    "oh", "ah", "uh", "hmm", "you", "the end",
    "vielen dank", "danke", "tschüss", "auf wiedersehen",
    "bis zum nächsten mal", "bis dann",
    "untertitelung", "untertitel", "subtitles",
}

_HALLUCINATIONS_CONTAINS = [
    "vielen dank für", "thanks for watching", "like and subscribe",
    "amara.org", "untertitel von", "untertitelung im auftrag",
    "transkription auf", "das war mein video", "copyright wan",
]


def is_hallucination(text: str) -> bool:
    """Return True if text is a common Whisper hallucination."""
    clean = text.strip().lower().rstrip(".!?,")
    if not clean or len(clean.split()) <= 2:
        return True
    if clean in _HALLUCINATIONS_EXACT:
        return True
    for pat in _HALLUCINATIONS_CONTAINS:
        if pat in clean:
            return True
    # Repeated sentence loop
    sentences = [s.strip().rstrip(".!?,") for s in clean.split(".") if s.strip()]
    if len(sentences) >= 3 and len({s.lower() for s in sentences}) == 1:
        return True
    return False


def has_speech(audio: np.ndarray, threshold: float = 0.01) -> bool:
    """Return True if audio has signal above silence threshold."""
    return float(np.max(np.abs(audio))) >= threshold


# ── Model cache ───────────────────────────────────────────────────────────────

_cache: dict[str, object] = {}
_lock  = threading.Lock()


def _model_key(model: str, device: str, compute: str) -> str:
    return f"{model}:{device}:{compute}"


def load_model(
    model:   str = "base",
    device:  str = "cpu",
    compute: str = "int8",
) -> object:
    """Load (or return cached) Whisper model."""
    key = _model_key(model, device, compute)
    with _lock:
        if key in _cache:
            return _cache[key]
    log.info("Loading Whisper model: %s (%s/%s)", model, device, compute)
    from faster_whisper import WhisperModel
    m = WhisperModel(model, device=device, compute_type=compute)
    with _lock:
        _cache[key] = m
    log.info("Whisper model ready: %s", model)
    return m


# ── Transcriber ───────────────────────────────────────────────────────────────

class Transcriber:
    """
    Transcribes a numpy audio array to text using faster-whisper.

    Usage:
        t = Transcriber(model="base", language="de")
        text = t.transcribe(audio_array)
    """

    def __init__(
        self,
        model:    str   = "base",
        device:   str   = "cpu",
        compute:  str   = "int8",
        language: str   = "de",
        beam_size: int  = 5,
        silence_threshold: float = 0.01,
        initial_prompt: str = "",
    ):
        self.language  = language
        self.beam_size = beam_size
        self.silence_threshold = silence_threshold
        self.initial_prompt    = initial_prompt
        self._model = load_model(model, device, compute)

    def transcribe(self, audio: np.ndarray) -> str | None:
        """
        Transcribe audio array (float32, 16kHz, mono).
        Returns None if silent or hallucination detected.
        """
        if not has_speech(audio, self.silence_threshold):
            log.debug("Transcriber: silent chunk — skipped")
            return None

        segments, _ = self._model.transcribe(
            audio,
            language=self.language,
            task="transcribe",
            beam_size=self.beam_size,
            vad_filter=True,
            without_timestamps=True,
            condition_on_previous_text=True,
            initial_prompt=self.initial_prompt or None,
        )
        text = " ".join(s.text.strip() for s in segments if s.text.strip())

        if is_hallucination(text):
            log.debug("Transcriber: hallucination filtered: %s", text)
            return None

        return text or None
