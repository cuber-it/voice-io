"""Streaming transcriber: processes audio chunks and appends text to a .md file.

Uses a global model cache so the Whisper model is loaded once and reused
across sessions. No lazy loading — model must be preloaded via preload_model().
"""

from __future__ import annotations

import datetime as dt
import logging
import queue
import threading
from pathlib import Path
from typing import Callable

import numpy as np

logger = logging.getLogger(__name__)

# --- Global model cache ---
_model_cache: dict[str, object] = {}
_model_lock = threading.Lock()


def preload_model(model_name: str, device: str = "cpu", compute_type: str = "int8") -> None:
    """Load a Whisper model into the global cache. Call at app startup."""
    key = f"{model_name}:{device}:{compute_type}"
    with _model_lock:
        if key in _model_cache:
            logger.info("Model already cached: %s", key)
            return
    logger.info("Preloading whisper model: %s", key)
    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    with _model_lock:
        _model_cache[key] = model
    logger.info("Model preloaded: %s", key)


def get_model(model_name: str, device: str = "cpu", compute_type: str = "int8") -> object:
    """Get a model from cache, loading it if necessary."""
    key = f"{model_name}:{device}:{compute_type}"
    with _model_lock:
        if key in _model_cache:
            return _model_cache[key]
    # not cached — load now
    preload_model(model_name, device, compute_type)
    with _model_lock:
        return _model_cache[key]


# --- Hallucination filter ---
HALLUCINATION_EXACT = {
    "thank you", "thanks", "thanks for watching", "thanks for listening",
    "bye", "goodbye", "see you", "see you next time",
    "oh", "ah", "uh", "hmm",
    "you", "the end", "i'm",
    "untertitelung", "untertitel", "subtitles",
    "copyright", "amara.org",
    # German hallucinations
    "vielen dank", "danke", "tschüss", "auf wiedersehen",
    "bis zum nächsten mal", "bis dann",
}

HALLUCINATION_CONTAINS = [
    "vielen dank für's zuschauen",
    "vielen dank fürs zuschauen",
    "vielen dank für's zuhören",
    "vielen dank fürs zuhören",
    "das war's für heute",
    "das war mein video",
    "transkription auf de",
    "transkription auf deutsch",
    "thanks for watching",
    "subscribe to my channel",
    "like and subscribe",
    "amara.org",
    "untertitel von",
    "untertitelung im auftrag",
    "copyright wan",
    "sdr 1",
]


def is_hallucination(text: str) -> bool:
    """Detect common Whisper hallucinations."""
    clean = text.strip().lower().rstrip(".!?,")
    if not clean:
        return True
    if clean in HALLUCINATION_EXACT:
        return True
    words = clean.split()
    if len(words) <= 2:
        return True
    # check substring patterns
    for pattern in HALLUCINATION_CONTAINS:
        if pattern in clean:
            return True
    # repeated sentences (stuck in a loop)
    sentences = [s.strip().rstrip(".!?,") for s in text.split(".") if s.strip()]
    if len(sentences) >= 3 and len(set(s.lower() for s in sentences)) == 1:
        return True
    # repeated dots/ellipsis (silence hallucination)
    if clean.replace(".", "").replace(" ", "") == "":
        return True
    return False


def audio_has_speech(audio: np.ndarray, threshold: float = 0.01) -> bool:
    """Check if audio chunk has signal above silence threshold."""
    return float(np.max(np.abs(audio))) >= threshold


class StreamingTranscriber:
    """Accumulates audio chunks and transcribes them periodically.

    Audio is fed via feed(). A background thread collects chunks,
    and every chunk_duration seconds worth of audio, runs whisper
    and appends the result to the output .md file.
    """

    def __init__(
        self,
        output_path: Path,
        model_name: str = "large-v3-turbo",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str = "de",
        beam_size: int = 5,
        chunk_duration: int = 4,
        sample_rate: int = 16000,
        silence_threshold: float = 0.01,
        title: str | None = None,
        stop_phrase: str | None = None,
        on_stop_phrase: Callable[[], None] | None = None,
        initial_prompt: str = "",
        macro_table: list | None = None,
    ):
        self.output_path = output_path
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.beam_size = beam_size
        self.chunk_duration = chunk_duration
        self.sample_rate = sample_rate
        self.silence_threshold = silence_threshold
        self.title = title
        self.stop_phrase = stop_phrase.lower().strip() if stop_phrase else None
        self.on_stop_phrase = on_stop_phrase
        self.initial_prompt = initial_prompt
        self.macro_table = macro_table or []

        self._audio_buffer: list[np.ndarray] = []
        self._buffer_samples = 0
        self._chunk_target = sample_rate * chunk_duration
        self._lock = threading.Lock()
        self._transcribe_queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._model = None
        self._word_count = 0
        self._processed_chunks = 0
        self._started_at: dt.datetime | None = None

    @property
    def processed_chunks(self) -> int:
        """Number of audio chunks fully processed by the transcription loop."""
        return self._processed_chunks

    @property
    def queue_size(self) -> int:
        """Current size of the internal transcription queue."""
        return self._transcribe_queue.qsize()

    def start(self) -> None:
        """Start the transcriber. Loads model from cache, writes frontmatter."""
        self._stop_event.clear()
        self._started_at = dt.datetime.now()
        self._model = get_model(self.model_name, self.device, self.compute_type)
        self._write_frontmatter()
        self._thread = threading.Thread(target=self._transcribe_loop, daemon=True)
        self._thread.start()
        logger.info("StreamingTranscriber started: %s (model ready)", self.output_path)

    def feed(self, audio_chunk: np.ndarray) -> None:
        """Feed an audio chunk from the recorder. Thread-safe."""
        with self._lock:
            self._audio_buffer.append(audio_chunk.copy())
            self._buffer_samples += len(audio_chunk)

            if self._buffer_samples >= self._chunk_target:
                combined = np.concatenate(self._audio_buffer)
                if combined.ndim > 1:
                    combined = combined.squeeze()
                self._transcribe_queue.put(combined)
                self._audio_buffer.clear()
                self._buffer_samples = 0

    def stop(self) -> int:
        """Stop transcriber. Processes remaining buffer. Returns total word count."""
        with self._lock:
            if self._audio_buffer:
                combined = np.concatenate(self._audio_buffer)
                if combined.ndim > 1:
                    combined = combined.squeeze()
                self._transcribe_queue.put(combined)
                self._audio_buffer.clear()
                self._buffer_samples = 0

        self._stop_event.set()
        if self._thread:
            self._thread.join()
            self._thread = None

        logger.info("StreamingTranscriber stopped: %d words", self._word_count)
        return self._word_count

    def _transcribe_loop(self) -> None:
        while not self._stop_event.is_set() or not self._transcribe_queue.empty():
            try:
                audio = self._transcribe_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if not audio_has_speech(audio, self.silence_threshold):
                logger.debug("Skipping silent chunk")
                self._processed_chunks += 1
                continue

            text = self._transcribe_chunk(audio)
            if not text:
                self._processed_chunks += 1
                continue

            if is_hallucination(text):
                logger.debug("Filtered hallucination: %s", text)
                self._processed_chunks += 1
                continue

            if self._check_stop_phrase(text):
                clean = self._remove_stop_phrase(text)
                if clean and not is_hallucination(clean):
                    expanded = self._expand_macros(clean)
                    self._append_text(expanded)
                    self._word_count += len(expanded.split())
                logger.info("Stop phrase detected in: %s", text)
                if self.on_stop_phrase:
                    self.on_stop_phrase()
                return

            expanded = self._expand_macros(text)
            self._append_text(expanded)
            self._word_count += len(expanded.split())
            self._processed_chunks += 1

    def _expand_macros(self, text: str) -> str:
        if not self.macro_table:
            return text
        from voice_io.macros import expand_macros
        return expand_macros(text, self.macro_table)

    def _check_stop_phrase(self, text: str) -> bool:
        if not self.stop_phrase:
            return False
        return self.stop_phrase in text.lower()

    def _remove_stop_phrase(self, text: str) -> str:
        if not self.stop_phrase:
            return text
        idx = text.lower().find(self.stop_phrase)
        if idx >= 0:
            return text[:idx].strip()
        return text

    def _transcribe_chunk(self, audio: np.ndarray) -> str:
        """Transcribe a single audio chunk using cached model."""
        segments, info = self._model.transcribe(
            audio,
            language=self.language,
            task="transcribe",
            beam_size=self.beam_size,
            vad_filter=True,
            without_timestamps=True,
            condition_on_previous_text=True,
            initial_prompt=self.initial_prompt or None,
        )
        parts = [seg.text.strip() for seg in segments if seg.text.strip()]
        return " ".join(parts)

    def _write_frontmatter(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "---",
            f"started: {self._started_at.isoformat()}",
            f"model: {self.model_name}",
            f"language: {self.language}",
            f"chunk_duration: {self.chunk_duration}",
        ]
        if self.title:
            lines.append(f"title: {self.title}")
        lines.extend(["---", "", ""])
        self.output_path.write_text("\n".join(lines))

    def _append_text(self, text: str) -> None:
        with open(self.output_path, "a") as fh:
            fh.write(text + "\n")
            fh.flush()
        logger.debug("Appended %d chars", len(text))
