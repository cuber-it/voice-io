"""Main daemon loop: single mic stream feeds wakeword, recorder and transcriber.

States:
  IDLE      - listening for wake-word
  RECORDING - capturing audio, transcribing in realtime
  PAUSED    - silence timeout, session alive, waiting for wake-word to resume
"""

from __future__ import annotations

import datetime as dt
import enum
import logging
import signal
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

from voice_io.config import Config
from voice_io.recorder import Recorder, resolve_device
from voice_io.transcriber import StreamingTranscriber
from voice_io.wakeword import WakewordDetector, CHUNK_SAMPLES

logger = logging.getLogger(__name__)


class State(enum.Enum):
    IDLE = "idle"
    RECORDING = "recording"
    PAUSED = "paused"


def next_transcript_name(session_dir: Path, language: str) -> str:
    """Find next available transcript name like de_001.md, de_002.md."""
    existing = list(session_dir.glob(f"{language}_*.md"))
    num = len(existing) + 1
    return f"{language}_{num:03d}.md"


class Daemon:
    """Main daemon: single mic -> wakeword + recorder + transcriber."""

    def __init__(self, config: Config):
        self.config = config
        self._state = State.IDLE
        self._shutdown = threading.Event()
        self._restart_stream = threading.Event()
        self._recorder: Recorder | None = None
        self._transcriber: StreamingTranscriber | None = None
        self._session_id: str | None = None
        self._session_dir: Path | None = None
        self._last_voice_time: float = 0.0
        self._language: str | None = None
        self._initial_prompt: str = ""
        self._macro_names: list[str] = []
        self._detector: WakewordDetector | None = None

    @property
    def state(self) -> State:
        return self._state

    def run(self) -> None:
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, self._handle_signal)
            signal.signal(signal.SIGTERM, self._handle_signal)

        vault_dir = self.config.general.vault_dir
        vault_dir.mkdir(parents=True, exist_ok=True)

        if self.config.wakeword.enabled:
            self._detector = WakewordDetector(
                word=self.config.wakeword.word,
                threshold=self.config.wakeword.threshold,
                on_trigger=self._on_wakeword,
            )
            logger.info(
                "Daemon started. wake-word='%s' (threshold=%.2f), stop='%s', silence_timeout=%ds",
                self.config.wakeword.word,
                self.config.wakeword.threshold,
                self.config.wakeword.stop_phrase,
                self.config.recording.silence_timeout,
            )
        else:
            self._detector = None
            logger.info(
                "Daemon started. Wake-word DISABLED (GUI-only), stop='%s', silence_timeout=%ds",
                self.config.wakeword.stop_phrase,
                self.config.recording.silence_timeout,
            )
        logger.info("Output dir: %s", vault_dir)

        while not self._shutdown.is_set():
            self._restart_stream.clear()
            device = resolve_device(self.config.recording.device)
            logger.info("Opening audio stream: device=%s", device or "default")

            try:
                with sd.InputStream(
                    samplerate=self.config.recording.sample_rate,
                    channels=self.config.recording.channels,
                    device=device,
                    blocksize=CHUNK_SAMPLES,
                    dtype="int16",
                    callback=self._raw_audio_callback,
                ):
                    # wait until shutdown or stream restart requested
                    while not self._shutdown.is_set() and not self._restart_stream.is_set():
                        self._shutdown.wait(timeout=0.5)
            except Exception as exc:
                logger.error("Audio stream error: %s", exc)
                if not self._shutdown.is_set():
                    time.sleep(2.0)

            if self._restart_stream.is_set():
                logger.info("Restarting audio stream with new device")

        if self._state in (State.RECORDING, State.PAUSED):
            self._stop_session()

        logger.info("Daemon stopped.")

    def set_wakeword_enabled(self, enabled: bool) -> None:
        """Enable or disable wake-word detection at runtime."""
        self.config.wakeword.enabled = enabled
        if enabled and self._detector is None:
            self._detector = WakewordDetector(
                word=self.config.wakeword.word,
                threshold=self.config.wakeword.threshold,
                on_trigger=self._on_wakeword,
            )
            logger.info("Wake-word ENABLED at runtime")
        elif not enabled and self._detector is not None:
            self._detector = None
            logger.info("Wake-word DISABLED at runtime")

    def switch_device(self, device_name: str | None) -> None:
        """Switch audio device at runtime. Triggers stream restart."""
        self.config.recording.device = device_name
        if self._state in (State.RECORDING, State.PAUSED):
            self._stop_session()
        self._restart_stream.set()
        logger.info("Device switch requested: %s", device_name or "default")

    def _raw_audio_callback(self, indata, frames, time_info, status) -> None:
        """Raw sounddevice callback — delegates to _audio_callback."""
        self._audio_callback(indata, self._detector)

    def _audio_callback(self, indata: np.ndarray, detector: WakewordDetector | None) -> None:
        if detector is not None:
            mono = indata[:, 0] if indata.ndim > 1 else indata
            detector.feed(mono)

        if self._state == State.RECORDING:
            float_data = indata.astype(np.float32) / 32768.0

            if self._recorder:
                self._recorder.write(float_data)
            if self._transcriber:
                self._transcriber.feed(float_data)

            peak = float(np.max(np.abs(float_data)))
            if peak >= self.config.recording.silence_threshold:
                self._last_voice_time = time.monotonic()
            elif self._silence_exceeded():
                self._pause_session()

    def _silence_exceeded(self) -> bool:
        if self._last_voice_time == 0.0:
            return False
        return (time.monotonic() - self._last_voice_time) >= self.config.recording.silence_timeout

    def _on_wakeword(self) -> None:
        if self._state == State.IDLE:
            self._start_session()
        elif self._state == State.PAUSED:
            self._resume_session()

    def _on_stop_phrase(self) -> None:
        logger.info("Stop phrase detected, ending session")
        threading.Thread(target=self._stop_session, daemon=True).start()

    def start_session_with_language(self, language: str, initial_prompt: str = "", macro_names: list[str] | None = None) -> None:
        self._language = language
        self._initial_prompt = initial_prompt
        self._macro_names = macro_names or []
        self._start_session()

    def _start_session(self) -> None:
        now = dt.datetime.now()
        self._session_id = now.strftime("%Y-%m-%d_%H%M%S")
        vault_dir = self.config.general.vault_dir
        self._session_dir = vault_dir / self._session_id
        self._session_dir.mkdir(parents=True, exist_ok=True)

        language = self._language or self.config.transcription.language
        wav_path = self._session_dir / "audio.wav"
        md_name = next_transcript_name(self._session_dir, language)
        md_path = self._session_dir / md_name

        cfg = self.config
        self._recorder = Recorder(
            output_path=wav_path,
            sample_rate=cfg.recording.sample_rate,
            channels=cfg.recording.channels,
        )
        self._transcriber = StreamingTranscriber(
            output_path=md_path,
            model_name=cfg.transcription.realtime_model,
            device=cfg.transcription.device,
            compute_type=cfg.transcription.compute_type,
            language=language,
            beam_size=cfg.transcription.beam_size,
            chunk_duration=cfg.transcription.chunk_duration,
            sample_rate=cfg.recording.sample_rate,
            silence_threshold=cfg.recording.silence_threshold,
            stop_phrase=cfg.wakeword.stop_phrase,
            on_stop_phrase=self._on_stop_phrase,
            initial_prompt=self._initial_prompt,
            macro_table=self._build_macro_table(),
        )

        self._recorder.start()
        self._transcriber.start()
        self._last_voice_time = time.monotonic()
        self._state = State.RECORDING
        self._language = None
        self._initial_prompt = ""
        self._macro_names = []

        logger.info("Session started: %s (lang=%s)", self._session_id, language)

    def _pause_session(self) -> None:
        if self._state != State.RECORDING:
            return
        self._state = State.PAUSED
        logger.info("Session paused: %s", self._session_id)

    def _resume_session(self) -> None:
        if self._state != State.PAUSED:
            return
        self._last_voice_time = time.monotonic()
        self._state = State.RECORDING
        logger.info("Session resumed: %s", self._session_id)

    def _stop_session(self) -> None:
        if self._state == State.IDLE:
            return
        self._state = State.IDLE

        # stop recorder immediately (fast)
        recorder = self._recorder
        transcriber = self._transcriber
        session_id = self._session_id
        self._recorder = None
        self._transcriber = None

        if recorder:
            result = recorder.stop()
            logger.info("Recording done: %.1fs, peak=%.3f", result.duration, result.peak)

        # let transcriber finish remaining chunks in background
        if transcriber:
            def finish_and_retranscribe():
                word_count = transcriber.stop()
                logger.info("Realtime transcription done: %s (%d words)", session_id, word_count)
                # auto re-transcribe with full quality model if different
                cfg = self.config
                if cfg.transcription.realtime_model != cfg.transcription.model:
                    self._auto_retranscribe(session_id, transcriber.language)
            threading.Thread(target=finish_and_retranscribe, daemon=True).start()
        else:
            logger.info("Session stopped: %s", session_id)

    def _build_macro_table(self) -> list:
        if not self._macro_names:
            return []
        from voice_io.macros import build_macro_table
        return build_macro_table(self.config.general.vault_dir, self._macro_names)

    def _auto_retranscribe(self, session_id: str, language: str) -> None:
        """Re-transcribe a session with the full quality model after recording."""
        try:
            import soundfile as sf
            from voice_io.transcriber import StreamingTranscriber

            cfg = self.config
            session_dir = cfg.general.vault_dir / session_id
            wav_path = session_dir / "audio.wav"
            if not wav_path.exists():
                return

            md_name = next_transcript_name(session_dir, language)
            md_path = session_dir / md_name

            logger.info("Auto re-transcribe: %s with %s", session_id, cfg.transcription.model)

            tmp_path = md_path.with_suffix(".tmp")
            data, sr = sf.read(str(wav_path))
            trans = StreamingTranscriber(
                output_path=tmp_path,
                model_name=cfg.transcription.model,
                device=cfg.transcription.device,
                compute_type=cfg.transcription.compute_type,
                language=language,
                beam_size=cfg.transcription.beam_size,
                chunk_duration=cfg.transcription.chunk_duration,
                sample_rate=sr,
                silence_threshold=cfg.recording.silence_threshold,
            )
            trans.start()
            chunk_size = sr * cfg.transcription.chunk_duration
            for start in range(0, len(data), chunk_size):
                chunk = data[start:start + chunk_size].astype(np.float32)
                if chunk.ndim == 1:
                    chunk = chunk.reshape(-1, 1)
                trans.feed(chunk)
            word_count = trans.stop()
            tmp_path.rename(md_path)
            logger.info("Re-transcribe done: %s/%s (%d words)", session_id, md_name, word_count)
        except Exception as exc:
            logger.error("Re-transcribe failed: %s: %s", session_id, exc)

    def _handle_signal(self, signum, frame) -> None:
        logger.info("Signal %d received, shutting down...", signum)
        self._shutdown.set()

    def shutdown(self) -> None:
        self._shutdown.set()
