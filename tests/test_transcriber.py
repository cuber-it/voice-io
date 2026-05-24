"""Tests for voice_io.transcriber module."""

import time
from pathlib import Path
from unittest.mock import MagicMock
from dataclasses import dataclass

import numpy as np
import pytest

from voice_io.transcriber import (
    StreamingTranscriber,
    is_hallucination,
    audio_has_speech,
    _model_cache,
    _model_lock,
)


@dataclass
class FakeSegment:
    text: str


class FakeWhisperModel:
    def __init__(self, *args, **kwargs):
        self._n = 0

    def transcribe(self, audio, **kwargs):
        self._n += 1
        return [FakeSegment(text=f"Dies ist ein Testsatz Nummer {self._n}")], MagicMock(language="de", duration=1.0)


class TestHallucinationFilter:

    def test_thank_you_is_hallucination(self):
        assert is_hallucination("Thank you.") is True

    def test_thanks_for_watching(self):
        assert is_hallucination("Thanks for watching") is True

    def test_oh(self):
        assert is_hallucination("Oh.") is True

    def test_repeated_phrase(self):
        assert is_hallucination("Thank you. Thank you. Thank you.") is True

    def test_empty_is_hallucination(self):
        assert is_hallucination("") is True
        assert is_hallucination("  ") is True

    def test_short_two_words(self):
        assert is_hallucination("I'm") is True

    def test_real_speech_not_hallucination(self):
        assert is_hallucination("Dies ist ein Test mit mehreren Woertern") is False

    def test_subtitle_hallucination(self):
        assert is_hallucination("Untertitelung") is True

    def test_real_sentence_passes(self):
        assert is_hallucination("Heute gehen wir in den Park und schauen uns die Enten an") is False


class TestAudioHasSpeech:

    def test_silence_below_threshold(self):
        silence = np.zeros(16000, dtype=np.float32)
        assert audio_has_speech(silence, threshold=0.01) is False

    def test_loud_above_threshold(self):
        loud = np.ones(16000, dtype=np.float32) * 0.5
        assert audio_has_speech(loud, threshold=0.01) is True

    def test_barely_above(self):
        audio = np.ones(16000, dtype=np.float32) * 0.02
        assert audio_has_speech(audio, threshold=0.01) is True

    def test_barely_below(self):
        audio = np.ones(16000, dtype=np.float32) * 0.005
        assert audio_has_speech(audio, threshold=0.01) is False


class TestTranscriberInit:

    def test_defaults(self, tmp_path):
        trans = StreamingTranscriber(output_path=tmp_path / "out.md")
        assert trans.model_name == "large-v3-turbo"
        assert trans.chunk_duration == 4
        assert trans.silence_threshold == 0.01

    def test_custom_params(self, tmp_path):
        trans = StreamingTranscriber(
            output_path=tmp_path / "out.md",
            model_name="large-v3",
            chunk_duration=6,
            language="en",
            silence_threshold=0.05,
            title="Test Title",
        )
        assert trans.model_name == "large-v3"
        assert trans.silence_threshold == 0.05


class TestTranscriberFrontmatter:

    def test_writes_frontmatter_on_start(self, tmp_path):
        md_path = tmp_path / "out.md"
        trans = StreamingTranscriber(output_path=md_path, title="My Recording")
        with _model_lock:
            _model_cache[f"{trans.model_name}:{trans.device}:{trans.compute_type}"] = FakeWhisperModel()
        trans.start()
        time.sleep(0.2)
        trans.stop()

        content = md_path.read_text()
        assert content.startswith("---\n")
        assert "model: large-v3-turbo" in content
        assert "title: My Recording" in content

    def test_frontmatter_without_title(self, tmp_path):
        md_path = tmp_path / "out.md"
        trans = StreamingTranscriber(output_path=md_path)
        with _model_lock:
            _model_cache[f"{trans.model_name}:{trans.device}:{trans.compute_type}"] = FakeWhisperModel()
        trans.start()
        time.sleep(0.1)
        trans.stop()
        assert "title:" not in md_path.read_text()


class TestTranscriberStreaming:

    def test_feed_and_transcribe(self, tmp_path):
        md_path = tmp_path / "out.md"
        trans = StreamingTranscriber(
            output_path=md_path,
            chunk_duration=1,
            sample_rate=16000,
            silence_threshold=0.0,  # accept everything for test
        )
        with _model_lock:
            _model_cache[f"{trans.model_name}:{trans.device}:{trans.compute_type}"] = FakeWhisperModel()
        trans.start()

        chunk_size = 1600
        audio = np.ones(16000 * 2, dtype=np.float32) * 0.1
        for start in range(0, len(audio), chunk_size):
            trans.feed(audio[start:start + chunk_size].reshape(-1, 1))

        time.sleep(1.0)
        word_count = trans.stop()

        content = md_path.read_text()
        assert "Testsatz" in content
        assert word_count > 0

    def test_silent_chunks_skipped(self, tmp_path):
        md_path = tmp_path / "out.md"
        trans = StreamingTranscriber(
            output_path=md_path,
            chunk_duration=1,
            sample_rate=16000,
            silence_threshold=0.1,  # high threshold
        )
        with _model_lock:
            _model_cache[f"{trans.model_name}:{trans.device}:{trans.compute_type}"] = FakeWhisperModel()
        trans.start()

        # feed silence
        silence = np.zeros(16000 * 2, dtype=np.float32).reshape(-1, 1)
        trans.feed(silence)

        time.sleep(0.5)
        word_count = trans.stop()

        assert word_count == 0

    def test_remaining_buffer_flushed_on_stop(self, tmp_path):
        md_path = tmp_path / "out.md"
        trans = StreamingTranscriber(
            output_path=md_path,
            chunk_duration=10,
            sample_rate=16000,
            silence_threshold=0.0,
        )
        with _model_lock:
            _model_cache[f"{trans.model_name}:{trans.device}:{trans.compute_type}"] = FakeWhisperModel()
        trans.start()

        audio = np.ones(16000, dtype=np.float32).reshape(-1, 1) * 0.1
        trans.feed(audio)
        word_count = trans.stop()

        assert "Testsatz" in md_path.read_text()
        assert word_count > 0

    def test_empty_session(self, tmp_path):
        md_path = tmp_path / "out.md"
        trans = StreamingTranscriber(output_path=md_path)
        with _model_lock:
            _model_cache[f"{trans.model_name}:{trans.device}:{trans.compute_type}"] = FakeWhisperModel()
        trans.start()
        time.sleep(0.1)
        word_count = trans.stop()
        assert word_count == 0
        assert md_path.exists()

    def test_creates_parent_dirs(self, tmp_path):
        md_path = tmp_path / "a" / "b" / "out.md"
        trans = StreamingTranscriber(output_path=md_path)
        with _model_lock:
            _model_cache[f"{trans.model_name}:{trans.device}:{trans.compute_type}"] = FakeWhisperModel()
        trans.start()
        time.sleep(0.1)
        trans.stop()
        assert md_path.exists()
