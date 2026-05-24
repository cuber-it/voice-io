"""Wake-word detection using openwakeword. Runs on audio chunks, fires callbacks."""

from __future__ import annotations

import logging
from typing import Callable

import numpy as np
from openwakeword.model import Model

logger = logging.getLogger(__name__)

# openwakeword expects 16kHz mono int16 frames, 1280 samples per chunk (80ms)
CHUNK_SAMPLES = 1280


class WakewordDetector:
    """Detects a wake-word in streaming audio chunks.

    Call feed() with raw int16 audio data. When the wake-word is detected
    above threshold, the on_trigger callback fires.
    """

    def __init__(
        self,
        word: str = "hey_jarvis",
        threshold: float = 0.5,
        on_trigger: Callable[[], None] | None = None,
    ):
        self.word = self._normalize_word(word)
        self.threshold = threshold
        self.on_trigger = on_trigger
        self._model = Model()

        if self.word not in self._model.models:
            available = list(self._model.models.keys())
            raise ValueError(
                f"Wake-word {self.word!r} not found. Available: {available}"
            )

        logger.info("WakewordDetector ready: word=%s threshold=%.2f", self.word, threshold)

    def feed(self, audio_chunk: np.ndarray) -> bool:
        """Feed an audio chunk (int16, 16kHz, mono). Returns True if triggered."""
        self._model.predict(audio_chunk)
        score = self._model.prediction_buffer[self.word][-1]

        if score >= self.threshold:
            logger.info("Wake-word detected: %s (score=%.3f)", self.word, score)
            self._model.reset()
            if self.on_trigger:
                self.on_trigger()
            return True

        return False

    def reset(self) -> None:
        """Reset prediction buffer."""
        self._model.reset()

    @staticmethod
    def _normalize_word(word: str) -> str:
        """Normalize wake-word name: hey jarvis -> hey_jarvis."""
        return word.strip().lower().replace(" ", "_")
