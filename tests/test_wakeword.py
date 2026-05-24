"""Tests for voice_io.wakeword module."""

import numpy as np
import pytest

from voice_io.wakeword import WakewordDetector, CHUNK_SAMPLES


class TestWakewordDetector:

    def test_init_default_word(self):
        det = WakewordDetector()
        assert det.word == "hey_jarvis"

    def test_init_normalizes_word(self):
        det = WakewordDetector(word="hey jarvis")
        assert det.word == "hey_jarvis"

    def test_init_normalizes_case(self):
        det = WakewordDetector(word="Hey Jarvis")
        assert det.word == "hey_jarvis"

    def test_init_invalid_word_raises(self):
        with pytest.raises(ValueError, match="not found"):
            WakewordDetector(word="nonexistent_word_xyz")

    def test_silence_does_not_trigger(self):
        triggered = []
        det = WakewordDetector(
            threshold=0.5,
            on_trigger=lambda: triggered.append(True),
        )
        silence = np.zeros(CHUNK_SAMPLES, dtype=np.int16)
        for _ in range(10):
            result = det.feed(silence)
            assert result is False
        assert len(triggered) == 0

    def test_noise_does_not_trigger(self):
        det = WakewordDetector(threshold=0.5)
        rng = np.random.default_rng(42)
        noise = (rng.random(CHUNK_SAMPLES) * 1000).astype(np.int16)
        for _ in range(10):
            assert det.feed(noise) is False

    def test_reset_clears_buffer(self):
        det = WakewordDetector()
        silence = np.zeros(CHUNK_SAMPLES, dtype=np.int16)
        det.feed(silence)
        det.reset()
        # after reset, prediction buffer should still work
        result = det.feed(silence)
        assert result is False

    def test_callback_not_required(self):
        det = WakewordDetector(on_trigger=None)
        silence = np.zeros(CHUNK_SAMPLES, dtype=np.int16)
        result = det.feed(silence)
        assert result is False

    def test_chunk_samples_constant(self):
        assert CHUNK_SAMPLES == 1280

    def test_threshold_stored(self):
        det = WakewordDetector(threshold=0.8)
        assert det.threshold == 0.8
