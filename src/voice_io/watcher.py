"""Watch a directory for new audio files. Import and transcribe automatically."""

from __future__ import annotations

import datetime as dt
import logging
import shutil
import threading
import time
from pathlib import Path

import numpy as np

from voice_io.config import Config

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".wma", ".aac"}
POLL_INTERVAL = 5  # seconds


class FolderWatcher:
    """Watches a directory for new audio files, imports them as sessions."""

    def __init__(self, config: Config):
        self.config = config
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._known_files: set[str] = set()

    def start(self) -> None:
        watch_dir = self.config.general.watch_dir
        if not watch_dir:
            logger.info("No watch_dir configured, watcher disabled")
            return

        watch_dir.mkdir(parents=True, exist_ok=True)
        # seed known files so we don't re-import existing ones
        self._known_files = {f.name for f in watch_dir.iterdir() if f.is_file()}

        self._stop.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("FolderWatcher started: %s", watch_dir)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("FolderWatcher stopped")

    def _poll_loop(self) -> None:
        watch_dir = self.config.general.watch_dir
        while not self._stop.is_set():
            try:
                self._check_new_files(watch_dir)
            except Exception as exc:
                logger.error("Watcher error: %s", exc)
            self._stop.wait(timeout=POLL_INTERVAL)

    def _check_new_files(self, watch_dir: Path) -> None:
        for file_path in watch_dir.iterdir():
            if not file_path.is_file():
                continue
            if file_path.name in self._known_files:
                continue
            if file_path.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            # skip files that might still be copying (modified in last 2 seconds)
            if time.time() - file_path.stat().st_mtime < 2.0:
                continue

            self._known_files.add(file_path.name)
            logger.info("New audio detected: %s", file_path.name)
            threading.Thread(
                target=self._import_file,
                args=(file_path,),
                daemon=True,
            ).start()

    def _import_file(self, file_path: Path) -> None:
        """Import an audio file as a new session and transcribe it."""
        try:
            now = dt.datetime.now()
            session_id = now.strftime("%Y-%m-%d_%H%M%S")
            session_dir = self.config.general.vault_dir / session_id
            session_dir.mkdir(parents=True, exist_ok=True)

            wav_path = session_dir / "audio.wav"

            # convert to WAV
            import soundfile as sf
            try:
                data, sr = sf.read(str(file_path))
                sf.write(str(wav_path), data, sr, format="WAV")
            except Exception:
                import subprocess
                result = subprocess.run(
                    ["ffmpeg", "-i", str(file_path), "-ar", "16000", "-ac", "1",
                     str(wav_path), "-y"],
                    capture_output=True, text=True,
                )
                if result.returncode != 0:
                    logger.error("Conversion failed for %s: %s", file_path.name, result.stderr[:200])
                    shutil.rmtree(session_dir)
                    return

            # move original to session dir for reference
            imported_path = session_dir / f"original_{file_path.name}"
            shutil.move(str(file_path), str(imported_path))

            # transcribe
            language = self.config.transcription.language
            from voice_io.daemon import next_transcript_name
            md_name = next_transcript_name(session_dir, language)
            md_path = session_dir / md_name

            from voice_io.transcriber import StreamingTranscriber
            data, sr = sf.read(str(wav_path))
            # stereo to mono
            if data.ndim > 1:
                data = data.mean(axis=1)
            trans = StreamingTranscriber(
                output_path=md_path,
                model_name=self.config.transcription.model,
                device=self.config.transcription.device,
                compute_type=self.config.transcription.compute_type,
                language=language,
                beam_size=self.config.transcription.beam_size,
                chunk_duration=self.config.transcription.chunk_duration,
                sample_rate=sr,
                silence_threshold=self.config.recording.silence_threshold,
            )
            trans.start()
            chunk_size = sr * self.config.transcription.chunk_duration
            for start in range(0, len(data), chunk_size):
                chunk = data[start:start + chunk_size].astype(np.float32)
                trans.feed(chunk)
            word_count = trans.stop()

            logger.info(
                "Imported %s -> session %s (%d words, lang=%s)",
                file_path.name, session_id, word_count, language,
            )

        except Exception as exc:
            logger.error("Import failed for %s: %s", file_path.name, exc)
