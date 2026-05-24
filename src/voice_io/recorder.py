"""Audio recorder that writes chunks to WAV. Fed externally, no own InputStream."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

logger = logging.getLogger(__name__)


@dataclass
class RecordingResult:
    path: Path
    duration: float
    sample_rate: int
    channels: int
    peak: float


def resolve_device(device: str | None) -> int | str | None:
    """Partial match on device name. Returns device index or None."""
    if not device:
        return None
    needle = device.lower()
    for idx, info in enumerate(sd.query_devices()):
        if info["max_input_channels"] <= 0:
            continue
        if needle in info["name"].lower():
            return idx
    return device


class Recorder:
    """Records audio to WAV file. Chunks are fed externally via write()."""

    def __init__(
        self,
        output_path: Path,
        sample_rate: int = 16000,
        channels: int = 1,
    ):
        self.output_path = output_path
        self.sample_rate = sample_rate
        self.channels = channels
        self._peak = 0.0
        self._file: sf.SoundFile | None = None
        self._start_time = 0.0
        self._lock = threading.Lock()

    def start(self) -> None:
        """Open the WAV file for writing."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._peak = 0.0
        self._start_time = time.monotonic()
        self._file = sf.SoundFile(
            str(self.output_path),
            mode="w",
            samplerate=self.sample_rate,
            channels=self.channels,
            format="WAV",
        )
        logger.info("Recording started: %s", self.output_path)

    def write(self, chunk: np.ndarray) -> None:
        """Write an audio chunk to the WAV file. Thread-safe."""
        with self._lock:
            if self._file is None:
                return
            self._file.write(chunk)
            peak = float(np.max(np.abs(chunk))) if chunk.size else 0.0
            if peak > self._peak:
                self._peak = peak

    def stop(self) -> RecordingResult:
        """Close the WAV file and return result."""
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None

        duration = time.monotonic() - self._start_time
        logger.info("Recording stopped: %.1fs, peak=%.3f", duration, self._peak)

        return RecordingResult(
            path=self.output_path,
            duration=duration,
            sample_rate=self.sample_rate,
            channels=self.channels,
            peak=self._peak,
        )

    @property
    def is_recording(self) -> bool:
        return self._file is not None
