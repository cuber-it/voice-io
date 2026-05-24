"""Tests for voice_io.daemon module."""

import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
from dataclasses import dataclass

import numpy as np
import pytest
import sounddevice as sd

from voice_io.config import Config
from voice_io.daemon import Daemon, State
from voice_io.transcriber import _model_cache, _model_lock


class FakeInputStream:
    def __init__(self, **kwargs):
        self.callback = kwargs.get("callback")
        self.blocksize = kwargs.get("blocksize", 1280)
        self.channels = kwargs.get("channels", 1)
        self._stop = threading.Event()

    def __enter__(self):
        def feeder():
            for _ in range(40):
                if self._stop.is_set():
                    break
                # feed audible signal, not silence
                chunk = (np.random.randn(self.blocksize, self.channels) * 3000).astype(np.int16)
                if self.callback:
                    self.callback(chunk, self.blocksize, None, None)
                time.sleep(0.05)
        self._thread = threading.Thread(target=feeder, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *args):
        self._stop.set()


@dataclass
class FakeSegment:
    text: str


class FakeWhisperModel:
    def __init__(self, *args, **kwargs):
        self._n = 0

    def transcribe(self, audio, **kwargs):
        self._n += 1
        return [FakeSegment(text=f"Dies ist Testsatz Nummer {self._n}")], MagicMock(language="de", duration=1.0)


def _inject_fake_model(daemon):
    if daemon._transcriber:
        key = f"{daemon._transcriber.model_name}:{daemon._transcriber.device}:{daemon._transcriber.compute_type}"
        with _model_lock:
            _model_cache[key] = FakeWhisperModel()
        daemon._transcriber._model = FakeWhisperModel()


class TestState:

    def test_initial_state_is_idle(self):
        assert Daemon(Config()).state == State.IDLE

    def test_shutdown_flag(self):
        d = Daemon(Config())
        d.shutdown()
        assert d._shutdown.is_set()


class TestSessionLifecycle:

    def test_start_sets_recording(self, tmp_path):
        config = Config()
        config.general.vault_dir = tmp_path
        d = Daemon(config)
        d._start_session()
        _inject_fake_model(d)
        assert d.state == State.RECORDING
        d._stop_session()

    def test_stop_sets_idle(self, tmp_path):
        config = Config()
        config.general.vault_dir = tmp_path
        d = Daemon(config)
        d._start_session()
        _inject_fake_model(d)
        d._stop_session()
        assert d.state == State.IDLE

    def test_pause_sets_paused(self, tmp_path):
        config = Config()
        config.general.vault_dir = tmp_path
        d = Daemon(config)
        d._start_session()
        _inject_fake_model(d)
        d._pause_session()
        assert d.state == State.PAUSED
        d._stop_session()

    def test_resume_sets_recording(self, tmp_path):
        config = Config()
        config.general.vault_dir = tmp_path
        d = Daemon(config)
        d._start_session()
        _inject_fake_model(d)
        d._pause_session()
        d._resume_session()
        assert d.state == State.RECORDING
        d._stop_session()

    def test_wakeword_in_idle_starts(self, tmp_path):
        config = Config()
        config.general.vault_dir = tmp_path
        d = Daemon(config)
        d._on_wakeword()
        _inject_fake_model(d)
        assert d.state == State.RECORDING
        d._stop_session()

    def test_wakeword_in_paused_resumes(self, tmp_path):
        config = Config()
        config.general.vault_dir = tmp_path
        d = Daemon(config)
        d._start_session()
        _inject_fake_model(d)
        d._pause_session()
        d._on_wakeword()
        assert d.state == State.RECORDING
        d._stop_session()

    def test_wakeword_while_recording_ignored(self, tmp_path):
        config = Config()
        config.general.vault_dir = tmp_path
        d = Daemon(config)
        d._on_wakeword()
        _inject_fake_model(d)
        sid = d._session_id
        d._on_wakeword()
        assert d._session_id == sid
        d._stop_session()

    def test_stop_phrase_ends_session(self, tmp_path):
        config = Config()
        config.general.vault_dir = tmp_path
        d = Daemon(config)
        d._start_session()
        _inject_fake_model(d)
        d._on_stop_phrase()
        time.sleep(0.3)
        assert d.state == State.IDLE


class TestSilenceTimeout:

    def test_silence_exceeded_false_initially(self):
        assert Daemon(Config())._silence_exceeded() is False

    def test_silence_exceeded_after_timeout(self, tmp_path):
        config = Config()
        config.recording.silence_timeout = 1
        d = Daemon(config)
        d._last_voice_time = time.monotonic() - 2.0
        assert d._silence_exceeded() is True

    def test_silence_not_exceeded_within_timeout(self):
        config = Config()
        config.recording.silence_timeout = 30
        d = Daemon(config)
        d._last_voice_time = time.monotonic()
        assert d._silence_exceeded() is False


class TestAudioCallback:

    def test_recording_feeds_recorder_and_transcriber(self, tmp_path):
        config = Config()
        config.general.vault_dir = tmp_path
        config.recording.silence_threshold = 0.001
        d = Daemon(config)
        d._start_session()
        _inject_fake_model(d)

        # simulate audio callback
        chunk = (np.ones((1280, 1), dtype=np.int16) * 5000)
        detector = MagicMock()
        detector.feed = MagicMock()
        d._audio_callback(chunk, detector)

        assert d._recorder._peak > 0.0
        d._stop_session()

    def test_paused_does_not_feed(self, tmp_path):
        config = Config()
        config.general.vault_dir = tmp_path
        d = Daemon(config)
        d._start_session()
        _inject_fake_model(d)
        d._pause_session()

        rec_write = MagicMock()
        d._recorder.write = rec_write
        trans_feed = MagicMock()
        d._transcriber.feed = trans_feed

        chunk = np.zeros((1280, 1), dtype=np.int16)
        detector = MagicMock()
        detector.feed = MagicMock()
        d._audio_callback(chunk, detector)

        rec_write.assert_not_called()
        trans_feed.assert_not_called()
        d._stop_session()


class TestFileOutput:

    def test_files_created(self, tmp_path):
        config = Config()
        config.general.vault_dir = tmp_path
        d = Daemon(config)
        d._start_session()
        _inject_fake_model(d)
        # write some audio to recorder
        d._recorder.write(np.random.randn(16000, 1).astype(np.float32) * 0.1)
        d._stop_session()

        session_dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
        assert len(session_dirs) == 1
        sdir = session_dirs[0]
        assert len(list(sdir.glob("*.md"))) == 1
        wav = sdir / "audio.wav"
        assert wav.exists()
        assert wav.stat().st_size > 44  # more than just header

    def test_creates_vault_dir(self, tmp_path):
        new_dir = tmp_path / "sub" / "vault"
        config = Config()
        config.general.vault_dir = new_dir
        d = Daemon(config)

        def auto_shutdown():
            time.sleep(0.3)
            d.shutdown()

        threading.Thread(target=auto_shutdown, daemon=True).start()
        with patch("voice_io.daemon.sd.InputStream", FakeInputStream):
            d.run()

        assert new_dir.exists()
