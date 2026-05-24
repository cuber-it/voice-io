"""
VoiceInput — Main pipeline: microphone → wakeword → record → transcribe → text.

Usage:
    from voice_input import VoiceInput

    voice = VoiceInput(wakeword="hey qataki")

    # Synchronous — blocks until one utterance is captured:
    text = voice.listen_once()
    print(text)

    # Async generator — yields each utterance:
    async for text in voice.listen():
        print(text)

    # With callback:
    def handle(text):
        print(f"You said: {text}")

    voice.start(on_text=handle)
    # ... voice.stop()
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import AsyncGenerator, Callable

import numpy as np

from .audio import AudioBuffer, AudioStream, SAMPLE_RATE
from .detection import WakewordDetector
from .transcription import Transcriber

log = logging.getLogger(__name__)

# How long to wait for speech after wake-word before timing out (seconds)
DEFAULT_RECORD_TIMEOUT = 10.0
# Silence after speech ends recording (seconds)
DEFAULT_SILENCE_TIMEOUT = 1.5


class VoiceInput:
    """
    Complete voice input pipeline.

    1. Streams microphone audio continuously
    2. Runs wake-word detection on every chunk
    3. After trigger: records until silence or timeout
    4. Transcribes the recording
    5. Returns the text

    Hardware (sounddevice, openwakeword, faster-whisper) is loaded lazily.
    """

    def __init__(
        self,
        wakeword:         str   = "hey_jarvis",
        wakeword_threshold: float = 0.5,
        whisper_model:    str   = "base",
        whisper_device:   str   = "cpu",
        whisper_compute:  str   = "int8",
        language:         str   = "de",
        device:           str | None = None,     # microphone device name
        record_timeout:   float = DEFAULT_RECORD_TIMEOUT,
        silence_timeout:  float = DEFAULT_SILENCE_TIMEOUT,
        silence_threshold: float = 0.01,
        initial_prompt:   str   = "",
    ):
        self._wakeword         = wakeword
        self._ww_threshold     = wakeword_threshold
        self._record_timeout   = record_timeout
        self._silence_timeout  = silence_timeout
        self._silence_threshold = silence_threshold
        self._mic_device       = device

        self._detector    = WakewordDetector(wakeword, wakeword_threshold)
        self._transcriber = Transcriber(
            model=whisper_model, device=whisper_device, compute=whisper_compute,
            language=language, silence_threshold=silence_threshold,
            initial_prompt=initial_prompt,
        )

        self._running   = False
        self._thread:   threading.Thread | None = None
        self._on_text:  Callable[[str], None] | None = None
        self._text_queue: asyncio.Queue[str | None] | None = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self, on_text: Callable[[str], None]) -> None:
        """Start background listening. Calls on_text(text) for each utterance."""
        if self._running:
            return
        self._detector.load()
        self._on_text = on_text
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("VoiceInput started (wakeword=%s)", self._wakeword)

    def start_direct(self, on_text: Callable[[str], None],
                     stop_phrase: str | None = None,
                     on_stop: Callable[[], None] | None = None) -> None:
        """
        Start recording immediately — no wakeword needed.
        Records until stop_phrase is detected or stop() is called.
        Used for push-to-talk: button press → speak → stop_phrase.
        """
        if self._running:
            return
        self._on_text  = on_text
        self._running  = True
        self._thread   = threading.Thread(
            target=self._loop_direct,
            args=(stop_phrase, on_stop),
            daemon=True,
        )
        self._thread.start()
        log.info("VoiceInput direct-start (stop_phrase=%r)", stop_phrase)

    def stop(self) -> None:
        """Stop background listening."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        log.info("VoiceInput stopped")

    def listen_once(self, timeout: float = 30.0) -> str | None:
        """
        Block until one utterance is captured and transcribed.
        Returns transcribed text or None on timeout.
        """
        result: list[str | None] = []
        done   = threading.Event()

        def handle(text: str) -> None:
            result.append(text)
            done.set()
            self.stop()

        self.start(on_text=handle)
        done.wait(timeout=timeout)
        return result[0] if result else None

    async def listen(self) -> AsyncGenerator[str, None]:
        """
        Async generator — yields each transcribed utterance.

        Usage:
            async for text in voice.listen():
                print(text)
        """
        loop  = asyncio.get_event_loop()
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._text_queue = queue

        def handle(text: str) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, text)

        self.start(on_text=handle)
        try:
            while True:
                text = await queue.get()
                if text is None:
                    break
                yield text
        finally:
            self.stop()

    # ── Internal loop ──────────────────────────────────────────────────────────

    def _loop(self) -> None:
        """Main capture loop — runs in background thread."""
        stream = AudioStream(device=self._mic_device)
        stream.start()
        try:
            log.info("Listening for wake-word: %s", self._wakeword)
            for chunk in stream.chunks():
                if not self._running:
                    break
                if self._detector.feed(chunk):
                    log.info("Wake-word detected — recording")
                    text = self._record_and_transcribe(stream)
                    if text and self._on_text:
                        self._on_text(text)
                    log.info("Listening for wake-word: %s", self._wakeword)
        finally:
            stream.stop()

    def _loop_direct(self, stop_phrase: str | None,
                     on_stop: Callable[[], None] | None) -> None:
        """Direct recording loop — no wakeword, records immediately."""
        stream = AudioStream(device=self._mic_device)
        stream.start()
        try:
            log.info("Direct recording started (stop_phrase=%r)", stop_phrase)
            text = self._record_and_transcribe(stream, stop_phrase=stop_phrase)
            if text and self._on_text:
                self._on_text(text)
            if on_stop:
                on_stop()
        finally:
            self._running = False
            stream.stop()

    def _record_and_transcribe(self, stream: AudioStream,
                               stop_phrase: str | None = None) -> str | None:
        """Record until silence (or stop_phrase) then transcribe."""
        buf            = AudioBuffer(SAMPLE_RATE)
        buf.start()
        deadline       = time.monotonic() + self._record_timeout
        last_speech    = time.monotonic()
        has_any_speech = False
        stop_norm      = stop_phrase.lower().strip() if stop_phrase else None

        for chunk in stream.chunks():
            if not self._running:
                break

            buf.write(chunk)
            is_speech = float(np.max(np.abs(chunk))) >= self._silence_threshold

            if is_speech:
                last_speech    = time.monotonic()
                has_any_speech = True

            now = time.monotonic()

            if now > deadline:
                log.info("Record timeout reached")
                break

            if has_any_speech and (now - last_speech) >= self._silence_timeout:
                log.info("Silence detected — stopping recording")
                break

        if not has_any_speech:
            return None

        audio = buf.finish()
        text  = self._transcriber.transcribe(audio)

        if text and stop_norm and stop_norm in text.lower():
            idx  = text.lower().find(stop_norm)
            text = text[:idx].strip() or None
            log.info("Stop-phrase removed from text")

        return text
