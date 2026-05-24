"""Audio recording — captures microphone input to a buffer or WAV file."""
from __future__ import annotations

import logging
import queue
import time
from collections.abc import Generator
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
CHANNELS    = 1
CHUNK_SIZE  = 1_280   # 80ms at 16kHz — matches openwakeword expectations


def list_input_devices() -> list[dict]:
    """List available microphone devices."""
    import sounddevice as sd
    return [
        {"index": i, "name": d["name"], "channels": d["max_input_channels"]}
        for i, d in enumerate(sd.query_devices())
        if d["max_input_channels"] > 0
    ]


def resolve_device(name: str | None) -> int | None:
    """Find device index by partial name match."""
    import sounddevice as sd
    if not name:
        return None
    needle = name.lower()
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and needle in d["name"].lower():
            return i
    return None


class AudioStream:
    """
    Continuous microphone stream — yields chunks as numpy arrays.
    Thread-safe, can be stopped from any thread.
    """

    def __init__(self, device: str | int | None = None,
                 sample_rate: int = SAMPLE_RATE,
                 chunk_size: int = CHUNK_SIZE):
        self.sample_rate = sample_rate
        self.chunk_size  = chunk_size
        self._device     = resolve_device(device) if isinstance(device, str) else device
        self._queue: queue.Queue[np.ndarray | None] = queue.Queue()
        self._stream = None

    def _callback(self, indata: np.ndarray, frames: int, t, status) -> None:
        if status:
            log.warning("AudioStream: %s", status)
        self._queue.put(indata[:, 0].copy())

    def start(self) -> None:
        import sounddevice as sd
        self._stream = sd.InputStream(
            device=self._device,
            samplerate=self.sample_rate,
            channels=CHANNELS,
            dtype="float32",
            blocksize=self.chunk_size,
            callback=self._callback,
        )
        self._stream.start()
        log.info("AudioStream started (device=%s, %dHz)", self._device, self.sample_rate)

    def stop(self) -> None:
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._queue.put(None)

    def chunks(self) -> Generator[np.ndarray, None, None]:
        """Yields audio chunks until stop() is called."""
        while True:
            chunk = self._queue.get()
            if chunk is None:
                break
            yield chunk

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()


class AudioBuffer:
    """
    Accumulates audio chunks into a single numpy array.
    Used to collect a recording for transcription.
    """

    def __init__(self, sample_rate: int = SAMPLE_RATE):
        self.sample_rate = sample_rate
        self._chunks: list[np.ndarray] = []
        self._start = 0.0

    def start(self) -> None:
        self._chunks = []
        self._start  = time.monotonic()

    def write(self, chunk: np.ndarray) -> None:
        self._chunks.append(chunk)

    def finish(self) -> np.ndarray:
        """Returns accumulated audio as float32 array."""
        if not self._chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self._chunks).astype(np.float32)

    @property
    def duration(self) -> float:
        return time.monotonic() - self._start

    def save_wav(self, path: Path) -> None:
        """Save buffer to WAV file."""
        import soundfile as sf
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(path), self.finish(), self.sample_rate)
