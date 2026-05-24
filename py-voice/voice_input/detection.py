"""Wake-word detection — listens for a trigger word in an audio stream."""
from __future__ import annotations

import logging
from collections.abc import Callable

import numpy as np

log = logging.getLogger(__name__)

CHUNK_SAMPLES = 1_280   # 80ms at 16kHz — openwakeword requirement
SAMPLE_RATE   = 16_000


class WakewordDetector:
    """
    Detects a wake-word in streaming audio chunks.

    Feed float32 audio via feed(). When the wake-word score
    exceeds the threshold, on_trigger fires and feed() returns True.
    """

    def __init__(
        self,
        word: str = "hey_jarvis",
        threshold: float = 0.5,
        on_trigger: Callable[[], None] | None = None,
    ):
        self.word      = self._normalize(word)
        self.threshold = threshold
        self.on_trigger = on_trigger
        self._model    = None

    def load(self) -> None:
        """Load the openwakeword model. Call once at startup."""
        from openwakeword.model import Model
        self._model = Model()
        if self.word not in self._model.models:
            available = list(self._model.models.keys())
            raise ValueError(
                f"Wake-word {self.word!r} not available. Choose from: {available}"
            )
        log.info("WakewordDetector ready: %s (threshold=%.2f)", self.word, self.threshold)

    def feed(self, chunk: np.ndarray) -> bool:
        """
        Feed an audio chunk (float32, 16kHz, mono).
        Returns True if wake-word detected.
        """
        if self._model is None:
            raise RuntimeError("WakewordDetector not loaded — call load() first")

        # openwakeword expects int16
        int16 = (chunk * 32767).astype(np.int16)
        self._model.predict(int16)
        score = self._model.prediction_buffer[self.word][-1]

        if score >= self.threshold:
            log.info("Wake-word detected: %s (score=%.3f)", self.word, score)
            self._model.reset()
            if self.on_trigger:
                self.on_trigger()
            return True
        return False

    def reset(self) -> None:
        if self._model:
            self._model.reset()

    @staticmethod
    def _normalize(word: str) -> str:
        return word.strip().lower().replace(" ", "_")
