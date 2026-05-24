"""Tests for voice_io.recorder module."""

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from voice_io.recorder import Recorder, RecordingResult, resolve_device


class TestResolveDevice:

    def test_none_returns_none(self):
        assert resolve_device(None) is None

    def test_empty_string_returns_none(self):
        assert resolve_device("") is None

    def test_unknown_device_returns_string(self):
        assert resolve_device("NONEXISTENT_XYZ_123") == "NONEXISTENT_XYZ_123"


class TestRecorderInit:

    def test_defaults(self, tmp_path):
        rec = Recorder(output_path=tmp_path / "test.wav")
        assert rec.sample_rate == 16000
        assert rec.channels == 1
        assert rec.is_recording is False

    def test_custom_params(self, tmp_path):
        rec = Recorder(output_path=tmp_path / "test.wav", sample_rate=44100, channels=2)
        assert rec.sample_rate == 44100
        assert rec.channels == 2


class TestRecorderWriteStop:

    def test_write_produces_wav(self, tmp_path):
        wav_path = tmp_path / "recording.wav"
        rec = Recorder(output_path=wav_path)
        rec.start()

        audio = np.sin(2 * np.pi * 440 * np.arange(16000) / 16000).astype(np.float32).reshape(-1, 1)
        rec.write(audio)
        result = rec.stop()

        assert isinstance(result, RecordingResult)
        assert wav_path.exists()
        assert result.peak > 0.0
        data, sr = sf.read(str(wav_path))
        assert sr == 16000
        assert len(data) == 16000

    def test_multiple_writes(self, tmp_path):
        wav_path = tmp_path / "recording.wav"
        rec = Recorder(output_path=wav_path)
        rec.start()

        for _ in range(10):
            chunk = np.random.randn(1600, 1).astype(np.float32) * 0.1
            rec.write(chunk)
        result = rec.stop()

        data, sr = sf.read(str(wav_path))
        assert len(data) == 16000

    def test_creates_parent_dirs(self, tmp_path):
        deep = tmp_path / "a" / "b" / "test.wav"
        rec = Recorder(output_path=deep)
        rec.start()
        rec.write(np.zeros((1600, 1), dtype=np.float32))
        rec.stop()
        assert deep.exists()

    def test_stop_without_start(self, tmp_path):
        rec = Recorder(output_path=tmp_path / "test.wav")
        result = rec.stop()
        assert isinstance(result, RecordingResult)

    def test_is_recording_flag(self, tmp_path):
        rec = Recorder(output_path=tmp_path / "test.wav")
        assert rec.is_recording is False
        rec.start()
        assert rec.is_recording is True
        rec.stop()
        assert rec.is_recording is False

    def test_peak_tracking(self, tmp_path):
        rec = Recorder(output_path=tmp_path / "test.wav")
        rec.start()
        rec.write(np.ones((1600, 1), dtype=np.float32) * 0.5)
        rec.write(np.ones((1600, 1), dtype=np.float32) * 0.8)
        result = rec.stop()
        assert result.peak >= 0.8


class TestRecordingResult:

    def test_fields(self):
        result = RecordingResult(path=Path("/tmp/test.wav"), duration=5.0, sample_rate=16000, channels=1, peak=0.85)
        assert result.duration == 5.0
        assert result.peak == 0.85
