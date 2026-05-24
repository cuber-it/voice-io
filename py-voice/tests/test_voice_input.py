"""Tests for voice_input — all hardware dependencies mocked."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ── Mocks für Hardware-Deps ───────────────────────────────────────────────────

# sounddevice
sd_mock = MagicMock()
sd_mock.query_devices.return_value = [
    {"name": "USB Microphone", "max_input_channels": 1},
    {"name": "Built-in Output", "max_input_channels": 0},
    {"name": "TONOR TM20",      "max_input_channels": 2},
]
sys.modules["sounddevice"]             = sd_mock

# soundfile
sf_mock = MagicMock()
sys.modules["soundfile"]               = sf_mock

# faster_whisper
fw_mock = MagicMock()
sys.modules["faster_whisper"]          = fw_mock

# openwakeword
oww_mock     = MagicMock()
oww_model    = MagicMock()
oww_model.models = {"hey_jarvis": MagicMock(), "alexa": MagicMock()}
oww_mock.model.Model.return_value = oww_model
sys.modules["openwakeword"]            = oww_mock
sys.modules["openwakeword.model"]      = oww_mock.model

# ── Import nach Mocks ─────────────────────────────────────────────────────────

sys.path.insert(0, str(Path(__file__).parent.parent))

from voice_input.audio        import AudioBuffer, list_input_devices, resolve_device  # noqa: E402
from voice_input.detection    import WakewordDetector  # noqa: E402
from voice_input.transcription import (  # noqa: E402
    Transcriber, has_speech, is_hallucination,
)
from voice_input.pipeline     import VoiceInput  # noqa: E402


# ── Hallucination filter ──────────────────────────────────────────────────────

class TestHallucinationFilter:

    def test_exact_matches(self):
        assert is_hallucination("thank you")
        assert is_hallucination("vielen dank")
        assert is_hallucination("tschüss")

    def test_short_words(self):
        assert is_hallucination("uh")
        assert is_hallucination("hmm")
        assert is_hallucination("oh")

    def test_real_speech(self):
        assert not is_hallucination("Bitte teste den Login-Button auf der Seite")
        assert not is_hallucination("Starte einen neuen Scan auf uc-it.de")
        assert not is_hallucination("Was hat der letzte Run gefunden?")

    def test_empty(self):
        assert is_hallucination("")
        assert is_hallucination("   ")

    def test_repeated_sentences(self):
        assert is_hallucination("Das ist toll. Das ist toll. Das ist toll. Das ist toll.")

    def test_contains_patterns(self):
        assert is_hallucination("vielen dank fürs zuschauen und bis zum nächsten mal")
        assert is_hallucination("thanks for watching and subscribing")

    def test_two_words(self):
        assert is_hallucination("auf wiedersehen")
        assert is_hallucination("bis dann")


# ── has_speech ────────────────────────────────────────────────────────────────

class TestHasSpeech:

    def test_silence(self):
        audio = np.zeros(1280, dtype=np.float32)
        assert not has_speech(audio)

    def test_loud(self):
        audio = np.ones(1280, dtype=np.float32) * 0.5
        assert has_speech(audio)

    def test_threshold(self):
        audio = np.zeros(1280, dtype=np.float32)
        audio[0] = 0.005
        assert not has_speech(audio, threshold=0.01)
        audio[0] = 0.02
        assert has_speech(audio, threshold=0.01)


# ── AudioBuffer ───────────────────────────────────────────────────────────────

class TestAudioBuffer:

    def test_empty(self):
        buf = AudioBuffer()
        buf.start()
        audio = buf.finish()
        assert len(audio) == 0
        assert audio.dtype == np.float32

    def test_accumulate(self):
        buf = AudioBuffer()
        buf.start()
        buf.write(np.zeros(1280, dtype=np.float32))
        buf.write(np.ones(1280, dtype=np.float32))
        audio = buf.finish()
        assert len(audio) == 2560
        assert audio[1280] == 1.0

    def test_duration(self):
        buf = AudioBuffer(sample_rate=16_000)
        buf.start()
        import time
        time.sleep(0.05)
        assert buf.duration >= 0.04

    def test_float32_output(self):
        buf = AudioBuffer()
        buf.start()
        buf.write(np.array([0.1, 0.2, 0.3], dtype=np.float32))
        result = buf.finish()
        assert result.dtype == np.float32

    def test_save_wav(self, tmp_path):
        buf = AudioBuffer()
        buf.start()
        buf.write(np.zeros(100, dtype=np.float32))
        path = tmp_path / "test.wav"
        buf.save_wav(path)
        sf_mock.write.assert_called_once()


# ── list_input_devices / resolve_device ──────────────────────────────────────

class TestDevices:

    def test_list_devices(self):
        devices = list_input_devices()
        assert len(devices) == 2  # only input devices
        names = [d["name"] for d in devices]
        assert "USB Microphone" in names
        assert "TONOR TM20"     in names
        assert "Built-in Output" not in names

    def test_resolve_by_name(self):
        idx = resolve_device("tonor")
        assert idx == 2

    def test_resolve_none(self):
        assert resolve_device(None) is None

    def test_resolve_not_found(self):
        assert resolve_device("nonexistent device xyz") is None


# ── WakewordDetector ──────────────────────────────────────────────────────────

class TestWakewordDetector:

    def test_load(self):
        det = WakewordDetector("hey_jarvis")
        det.load()
        assert det._model is not None

    def test_unknown_word_raises(self):
        det = WakewordDetector("unknown_word_xyz")
        det._model = oww_model
        with pytest.raises(ValueError, match="not available"):
            det.load()

    def test_normalize(self):
        assert WakewordDetector._normalize("Hey Jarvis") == "hey_jarvis"
        assert WakewordDetector._normalize("ALEXA")      == "alexa"

    def test_no_trigger(self):
        det = WakewordDetector("hey_jarvis", threshold=0.8)
        det._model = oww_model
        oww_model.prediction_buffer = {"hey_jarvis": [0.3]}
        chunk = np.zeros(1280, dtype=np.float32)
        assert not det.feed(chunk)

    def test_trigger(self):
        triggered = []
        det = WakewordDetector("hey_jarvis", threshold=0.5,
                               on_trigger=lambda: triggered.append(True))
        det._model = oww_model
        oww_model.prediction_buffer = {"hey_jarvis": [0.9]}
        chunk = np.zeros(1280, dtype=np.float32)
        assert det.feed(chunk)
        assert len(triggered) == 1

    def test_not_loaded_raises(self):
        det = WakewordDetector("hey_jarvis")
        with pytest.raises(RuntimeError, match="not loaded"):
            det.feed(np.zeros(1280, dtype=np.float32))


# ── Transcriber ───────────────────────────────────────────────────────────────

class TestTranscriber:

    def _make_transcriber(self, segments=None):
        """Build a Transcriber with mocked model."""
        if segments is None:
            segments = [MagicMock(text=" Bitte teste den Login-Button.")]

        model_mock = MagicMock()
        model_mock.transcribe.return_value = (iter(segments), MagicMock())
        fw_mock.WhisperModel.return_value = model_mock

        # Cache leeren damit jeder Test ein frisches Model bekommt
        import voice_input.transcription as tr
        tr._cache.clear()

        t = Transcriber(model="base")
        return t, model_mock

    def test_transcribe_normal(self):
        t, model = self._make_transcriber()
        audio = np.ones(16000, dtype=np.float32) * 0.5
        result = t.transcribe(audio)
        assert result == "Bitte teste den Login-Button."
        model.transcribe.assert_called_once()

    def test_transcribe_silent(self):
        t, model = self._make_transcriber()
        audio = np.zeros(16000, dtype=np.float32)
        result = t.transcribe(audio)
        assert result is None
        model.transcribe.assert_not_called()

    def test_transcribe_hallucination(self):
        t, _ = self._make_transcriber(
            segments=[MagicMock(text=" vielen dank fürs zuschauen")]
        )
        audio = np.ones(16000, dtype=np.float32) * 0.5
        result = t.transcribe(audio)
        assert result is None

    def test_transcribe_empty_segments(self):
        t, _ = self._make_transcriber(segments=[])
        audio = np.ones(16000, dtype=np.float32) * 0.5
        result = t.transcribe(audio)
        assert result is None

    def test_transcribe_multiple_segments(self):
        segs = [MagicMock(text=" Klicke auf den Login-Button"),
                MagicMock(text=" und teste das Formular")]
        t, _ = self._make_transcriber(segments=segs)
        audio = np.ones(16000, dtype=np.float32) * 0.5
        result = t.transcribe(audio)
        assert result == "Klicke auf den Login-Button und teste das Formular"


# ── VoiceInput ────────────────────────────────────────────────────────────────

class TestVoiceInput:

    def test_init(self):
        v = VoiceInput(wakeword="hey_jarvis", whisper_model="base")
        assert v._wakeword == "hey_jarvis"
        assert not v._running

    def test_listen_once_timeout(self):
        """listen_once returns None on timeout."""
        v = VoiceInput(wakeword="hey_jarvis")

        # Detector never triggers — timeout fires
        with patch.object(v._detector, "load"), \
             patch.object(v._detector, "feed", return_value=False):

            chunks_iter = iter([np.zeros(1280, dtype=np.float32)] * 5)

            with patch("voice_input.pipeline.AudioStream") as mock_stream_cls:
                mock_stream = MagicMock()
                mock_stream.chunks.return_value = chunks_iter
                mock_stream_cls.return_value    = mock_stream

                result = v.listen_once(timeout=0.1)
                assert result is None

    def test_stop_sets_running_false(self):
        v = VoiceInput()
        v._running = True
        v.stop()
        assert not v._running
