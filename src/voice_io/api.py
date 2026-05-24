"""FastAPI backend for voice-io GUI."""

from __future__ import annotations

import asyncio
import logging
import shutil
import threading
import time
from pathlib import Path

import numpy as np
from fastapi import FastAPI, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from voice_io.config import Config, load_config
from voice_io.daemon import Daemon, State, next_transcript_name
from voice_io.glossary import list_glossaries, load_glossary, save_glossary, delete_glossary, build_initial_prompt
from voice_io.macros import list_macro_sets, load_macros, save_macros, delete_macros
from voice_io.cleanup import list_prompt_profiles, load_prompt, save_prompt, delete_prompt, build_system_prompt, cleanup_text
from voice_io.transcriber import preload_model
from voice_io.watcher import FolderWatcher

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

# Upload transcription progress: session_id -> {current, total, status}
_upload_progress: dict[str, dict] = {}


class ConfigUpdate(BaseModel):
    stop_phrase: str | None = None
    model: str | None = None
    chunk_duration: int | None = None
    silence_timeout: int | None = None
    silence_threshold: float | None = None
    language: str | None = None
    device: str | None = None
    wakeword_enabled: bool | None = None


class CleanupRequest(BaseModel):
    transcript_name: str
    profiles: list[str] = ["standard"]
    provider: str = "anthropic"
    model: str = "claude-haiku-4-5-20251001"

class PromptSave(BaseModel):
    content: str

class MacroEntry(BaseModel):
    trigger: str
    replacement: str = ""

class MacroSave(BaseModel):
    entries: list[MacroEntry]

class GlossaryEntry(BaseModel):
    word: str
    description: str = ""

class GlossarySave(BaseModel):
    entries: list[GlossaryEntry]

class TranscribeRequest(BaseModel):
    language: str = "de"
    model: str | None = None


def create_app(config: Config | None = None) -> FastAPI:
    if config is None:
        config = load_config()

    import os
    if config.network.hf_offline:
        os.environ["HF_HUB_OFFLINE"] = "1"

    app = FastAPI(title="voice-io", version="0.9.0")
    daemon = Daemon(config)
    daemon_thread: threading.Thread | None = None
    watcher = FolderWatcher(config)
    peak_holder = {"value": 0.0}

    original_cb = daemon._audio_callback.__func__

    def patched_cb(self, indata, detector):
        original_cb(self, indata, detector)
        peak_holder["value"] = float(np.max(np.abs(indata.astype(np.float32) / 32768.0)))

    import types
    daemon._audio_callback = types.MethodType(patched_cb, daemon)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return (STATIC_DIR / "index.html").read_text()

    # --- Status ---
    @app.get("/api/status")
    async def status():
        return _build_status(daemon, config, peak_holder)

    # --- Recording control ---
    @app.post("/api/start")
    async def start(language: str = "de", glossaries: str = "", macros: str = ""):
        if daemon.state == State.IDLE:
            glossary_names = [g.strip() for g in glossaries.split(",") if g.strip()]
            macro_names = [m.strip() for m in macros.split(",") if m.strip()]
            prompt = build_initial_prompt(config.general.vault_dir, glossary_names, language)
            daemon.start_session_with_language(language, initial_prompt=prompt, macro_names=macro_names)
        return _build_status(daemon, config, peak_holder)

    @app.post("/api/stop")
    async def stop():
        if daemon.state in (State.RECORDING, State.PAUSED):
            daemon._stop_session()
        return _build_status(daemon, config, peak_holder)

    @app.post("/api/pause")
    async def pause():
        if daemon.state == State.RECORDING:
            daemon._pause_session()
        return _build_status(daemon, config, peak_holder)

    @app.post("/api/resume")
    async def resume():
        if daemon.state == State.PAUSED:
            daemon._resume_session()
        return _build_status(daemon, config, peak_holder)


    @app.post("/api/upload")
    async def upload_audio(file: UploadFile, language: str = "de"):
        """Import an external audio file (WAV, MP3, FLAC, OGG) as a new session."""
        import datetime as dt

        now = dt.datetime.now()
        session_id = now.strftime("%Y-%m-%d_%H%M%S")
        session_dir = config.general.vault_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        _upload_progress[session_id] = {"current": 0, "total": 1, "status": "converting"}

        # save uploaded file (blocking I/O via to_thread for large files)
        upload_path = session_dir / f"upload_{file.filename}"
        content_bytes = await file.read()

        def _write_and_convert() -> str | None:
            """Write uploaded bytes, convert to WAV. Returns error message or None."""
            with open(upload_path, "wb") as fh:
                fh.write(content_bytes)
            wav_path = session_dir / "audio.wav"
            try:
                import soundfile as sf
                data, sr = sf.read(str(upload_path))
                sf.write(str(wav_path), data, sr, format="WAV")
                if upload_path != wav_path:
                    upload_path.unlink()
            except Exception:
                import subprocess
                result = subprocess.run(
                    ["ffmpeg", "-i", str(upload_path), "-ar", "16000", "-ac", "1", str(wav_path), "-y"],
                    capture_output=True, text=True,
                )
                if result.returncode != 0:
                    return f"Could not convert audio: {result.stderr[:200]}"
                upload_path.unlink()
            return None

        err = await asyncio.to_thread(_write_and_convert)
        if err is not None:
            shutil.rmtree(session_dir)
            _upload_progress.pop(session_id, None)
            return {"error": err}

        wav_path = session_dir / "audio.wav"
        md_name = next_transcript_name(session_dir, language)
        md_path = session_dir / md_name

        def do_transcribe():
            from voice_io.transcriber import StreamingTranscriber
            import soundfile as sf

            audio_data, sr = sf.read(str(wav_path))
            if audio_data.ndim > 1:
                audio_data = audio_data.mean(axis=1)
            tmp_path = md_path.with_suffix(".tmp")
            trans = StreamingTranscriber(
                output_path=tmp_path,
                model_name=config.transcription.model,
                device=config.transcription.device,
                compute_type=config.transcription.compute_type,
                language=language,
                beam_size=config.transcription.beam_size,
                chunk_duration=config.transcription.chunk_duration,
                sample_rate=sr,
                silence_threshold=config.recording.silence_threshold,
            )
            trans.start()
            chunk_size = sr * config.transcription.chunk_duration
            total_chunks = max(1, (len(audio_data) + chunk_size - 1) // chunk_size)
            _upload_progress[session_id] = {"current": 0, "total": total_chunks, "status": "transcribing"}

            # feed all chunks (fast, non-blocking)
            for start in range(0, len(audio_data), chunk_size):
                chunk = audio_data[start:start + chunk_size].astype(np.float32)
                trans.feed(chunk)

            # poll actual processing progress
            while trans.queue_size > 0:
                _upload_progress[session_id]["current"] = trans.processed_chunks
                time.sleep(0.5)

            trans.stop()
            tmp_path.rename(md_path)
            _upload_progress[session_id]["current"] = total_chunks
            _upload_progress[session_id]["status"] = "done"
            logger.info("Upload transcribed: %s/%s (lang=%s)", session_id, md_name, language)

        threading.Thread(target=do_transcribe, daemon=True).start()

        return {"status": "uploaded", "session_id": session_id, "transcript": md_name, "language": language}

    @app.get("/api/upload/progress/{session_id}")
    async def upload_progress(session_id: str):
        """Return transcription progress for an upload."""
        info = _upload_progress.get(session_id)
        if not info:
            return {"status": "unknown"}
        result = dict(info)
        if info["status"] == "done":
            _upload_progress.pop(session_id, None)
        return result

    # --- Sessions ---
    @app.get("/api/sessions")
    async def sessions():
        vault_dir = config.general.vault_dir
        if not vault_dir.exists():
            return []
        result = []
        for session_dir in sorted(vault_dir.iterdir(), reverse=True):
            if not session_dir.is_dir():
                continue
            if session_dir.name in ("glossaries", "macros", "prompts", "models", "inbox"):
                continue
            wav = session_dir / "audio.wav"
            transcripts = sorted(session_dir.glob("*.md"))
            duration_sec = 0
            size_kb = 0
            if wav.exists():
                try:
                    import soundfile as sf
                    info = sf.info(str(wav))
                    duration_sec = round(info.duration)
                    size_kb = round(wav.stat().st_size / 1024)
                except Exception:
                    pass

            transcript_list = []
            for md in transcripts:
                content = md.read_text()
                parts = content.split("---", 2)
                text = parts[2].strip() if len(parts) >= 3 else ""
                # extract language from filename like de_001.md
                lang = md.stem.split("_")[0] if "_" in md.stem else "?"
                transcript_list.append({
                    "name": md.name,
                    "language": lang,
                    "preview": text[:120] if text else "",
                    "words": len(text.split()) if text else 0,
                })

            result.append({
                "session_id": session_dir.name,
                "has_audio": wav.exists(),
                "size_kb": size_kb,
                "duration": duration_sec,
                "transcripts": transcript_list,
            })
        return result

    @app.get("/api/sessions/{session_id}")
    async def session_detail(session_id: str):
        session_dir = config.general.vault_dir / session_id
        if not session_dir.exists():
            return {"error": "not found"}
        transcripts = {}
        for md in sorted(session_dir.glob("*.md")):
            transcripts[md.name] = md.read_text()
        return {"session_id": session_id, "transcripts": transcripts}

    @app.get("/api/sessions/{session_id}/transcript/{name}")
    async def get_transcript(session_id: str, name: str):
        path = config.general.vault_dir / session_id / name
        if not path.exists():
            return {"error": "not found"}
        return {"session_id": session_id, "name": name, "content": path.read_text()}

    @app.get("/api/sessions/{session_id}/audio")
    async def session_audio(session_id: str):
        wav = config.general.vault_dir / session_id / "audio.wav"
        if not wav.exists():
            return {"error": "no audio"}
        return FileResponse(path=str(wav), media_type="audio/wav", filename=f"{session_id}.wav")

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str):
        session_dir = config.general.vault_dir / session_id
        if session_dir.exists():
            shutil.rmtree(session_dir)
            return {"deleted": session_id}
        return {"error": "not found"}


    @app.put("/api/sessions/{session_id}/rename")
    async def rename_session(session_id: str, new_name: str):
        """Rename a session directory."""
        vault_dir = config.general.vault_dir
        old_dir = vault_dir / session_id
        if not old_dir.exists():
            return {"error": "not found"}
        # sanitize: keep only safe chars
        import re
        safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", new_name.strip())[:60]
        if not safe_name:
            return {"error": "invalid name"}
        new_dir = vault_dir / safe_name
        if new_dir.exists():
            return {"error": "name already exists"}
        old_dir.rename(new_dir)
        return {"old": session_id, "new": safe_name}

    @app.delete("/api/sessions/{session_id}/transcript/{name}")
    async def delete_transcript(session_id: str, name: str):
        path = config.general.vault_dir / session_id / name
        if path.exists():
            path.unlink()
            return {"deleted": name}
        return {"error": "not found"}

    @app.post("/api/sessions/{session_id}/transcribe")
    async def transcribe_session(session_id: str, req: TranscribeRequest):
        session_dir = config.general.vault_dir / session_id
        wav_path = session_dir / "audio.wav"
        if not wav_path.exists():
            return {"error": "no audio file"}

        language = req.language
        model_name = req.model or config.transcription.model
        md_name = next_transcript_name(session_dir, language)
        md_path = session_dir / md_name

        def do_transcribe():
            from voice_io.transcriber import StreamingTranscriber
            import soundfile as sf

            data, sr = sf.read(str(wav_path))
            tmp_path = md_path.with_suffix(".tmp")
            trans = StreamingTranscriber(
                output_path=tmp_path,
                model_name=model_name,
                device=config.transcription.device,
                compute_type=config.transcription.compute_type,
                language=language,
                beam_size=config.transcription.beam_size,
                chunk_duration=config.transcription.chunk_duration,
                sample_rate=sr,
                silence_threshold=config.recording.silence_threshold,
            )
            trans.start()
            chunk_size = sr * config.transcription.chunk_duration
            for start in range(0, len(data), chunk_size):
                chunk = data[start:start + chunk_size].astype(np.float32)
                if chunk.ndim == 1:
                    chunk = chunk.reshape(-1, 1)
                trans.feed(chunk)
            trans.stop()
            tmp_path.rename(md_path)
            logger.info("Retranscribe done: %s/%s (lang=%s)", session_id, md_name, language)

        threading.Thread(target=do_transcribe, daemon=True).start()
        return {"status": "transcribing", "session_id": session_id, "transcript": md_name, "language": language}


    @app.get("/api/devices")
    async def list_devices():
        import sounddevice as sd
        devices = []
        for idx, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0:
                devices.append({
                    "index": idx,
                    "name": dev["name"],
                    "channels": dev["max_input_channels"],
                    "sample_rate": int(dev["default_samplerate"]),
                })
        current = config.recording.device or "default"
        return {"devices": devices, "current": current}




    # --- Cleanup (LLM) ---
    @app.post("/api/sessions/{session_id}/cleanup")
    async def cleanup_session(session_id: str, req: CleanupRequest):
        session_dir = config.general.vault_dir / session_id
        src_path = session_dir / req.transcript_name
        if not src_path.exists():
            return {"error": "transcript not found"}

        raw_content = src_path.read_text()
        parts = raw_content.split("---", 2)
        raw_text = parts[2].strip() if len(parts) >= 3 else raw_content

        def do_cleanup():
            try:
                system_prompt = build_system_prompt(config.general.vault_dir, req.profiles)
                cleaned = cleanup_text(
                    raw_text=raw_text,
                    system_prompt=system_prompt,
                    provider=req.provider,
                    model=req.model,
                )
                # save as clean_<lang>_NNN.md
                lang = req.transcript_name.split("_")[0]
                from voice_io.daemon import next_transcript_name
                clean_name = "clean_" + next_transcript_name(session_dir, f"clean_{lang}")
                # fix double clean_ prefix
                clean_name = clean_name.replace("clean_clean_", "clean_")
                clean_path = session_dir / clean_name

                import datetime as dt
                lines = [
                    "---",
                    f"cleaned: {dt.datetime.now().isoformat()}",
                    f"source: {req.transcript_name}",
                    f"profiles: {', '.join(req.profiles)}",
                    f"provider: {req.provider}",
                    f"model: {req.model}",
                    "---",
                    "",
                    cleaned,
                    "",
                ]
                clean_path.write_text("\n".join(lines))
                logger.info("Cleanup done: %s/%s", session_id, clean_name)
            except Exception as exc:
                logger.error("Cleanup failed: %s: %s", session_id, exc)

        threading.Thread(target=do_cleanup, daemon=True).start()
        return {"status": "cleaning", "session_id": session_id}

    # --- Prompt Profiles ---
    @app.get("/api/prompts")
    async def get_prompts():
        return list_prompt_profiles(config.general.vault_dir)

    @app.get("/api/prompts/{name}")
    async def get_prompt(name: str):
        text = load_prompt(config.general.vault_dir, name)
        return {"name": name, "content": text}

    @app.put("/api/prompts/{name}")
    async def put_prompt(name: str, data: PromptSave):
        save_prompt(config.general.vault_dir, name, data.content)
        return {"status": "saved", "name": name}

    @app.delete("/api/prompts/{name}")
    async def del_prompt(name: str):
        ok = delete_prompt(config.general.vault_dir, name)
        return {"deleted": ok}

    # --- Macros ---
    @app.get("/api/macros")
    async def get_macros():
        return list_macro_sets(config.general.vault_dir)

    @app.get("/api/macros/{name}")
    async def get_macro(name: str):
        entries = load_macros(config.general.vault_dir, name)
        return {"name": name, "entries": entries}

    @app.put("/api/macros/{name}")
    async def put_macro(name: str, data: MacroSave):
        save_macros(config.general.vault_dir, name, [e.model_dump() for e in data.entries])
        return {"status": "saved", "name": name, "entries": len(data.entries)}

    @app.delete("/api/macros/{name}")
    async def del_macro(name: str):
        ok = delete_macros(config.general.vault_dir, name)
        return {"deleted": ok}

    # --- Glossaries ---
    @app.get("/api/glossaries")
    async def get_glossaries():
        return list_glossaries(config.general.vault_dir)

    @app.get("/api/glossaries/{name}")
    async def get_glossary(name: str):
        entries = load_glossary(config.general.vault_dir, name)
        return {"name": name, "entries": entries}

    @app.put("/api/glossaries/{name}")
    async def put_glossary(name: str, data: GlossarySave):
        save_glossary(config.general.vault_dir, name, [e.model_dump() for e in data.entries])
        return {"status": "saved", "name": name, "entries": len(data.entries)}

    @app.delete("/api/glossaries/{name}")
    async def del_glossary(name: str):
        ok = delete_glossary(config.general.vault_dir, name)
        return {"deleted": ok}

    # --- Config ---
    @app.get("/api/config")
    async def get_config():
        return {
            "wakeword": config.wakeword.word,
            "wakeword_enabled": config.wakeword.enabled,
            "stop_phrase": config.wakeword.stop_phrase,
            "model": config.transcription.model,
            "realtime_model": config.transcription.realtime_model,
            "chunk_duration": config.transcription.chunk_duration,
            "silence_timeout": config.recording.silence_timeout,
            "silence_threshold": config.recording.silence_threshold,
            "language": config.transcription.language,
            "sample_rate": config.recording.sample_rate,
            "device": config.recording.device or "default",
            "vault_dir": str(config.general.vault_dir),
            "watch_dir": str(config.general.watch_dir) if config.general.watch_dir else "",
        }

    @app.put("/api/config")
    async def update_config(update: ConfigUpdate):
        if update.stop_phrase is not None:
            config.wakeword.stop_phrase = update.stop_phrase
        if update.model is not None:
            config.transcription.model = update.model
        if update.chunk_duration is not None:
            config.transcription.chunk_duration = update.chunk_duration
        if update.silence_timeout is not None:
            config.recording.silence_timeout = update.silence_timeout
        if update.silence_threshold is not None:
            config.recording.silence_threshold = update.silence_threshold
        if update.language is not None:
            config.transcription.language = update.language
        if update.device is not None:
            new_dev = update.device if update.device != "default" else None
            daemon.switch_device(new_dev)
        if update.wakeword_enabled is not None:
            daemon.set_wakeword_enabled(update.wakeword_enabled)
        return {"status": "updated"}

    @app.get("/health")
    async def health():
        return {"status": "ok", "state": daemon.state.value}

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        try:
            while True:
                await ws.send_json(_build_status(daemon, config, peak_holder))
                await asyncio.sleep(0.1)
        except WebSocketDisconnect:
            pass

    @app.on_event("startup")
    async def startup():
        nonlocal daemon_thread
        # preload both models
        def preload_both():
            preload_model(config.transcription.realtime_model, config.transcription.device, config.transcription.compute_type)
            preload_model(config.transcription.model, config.transcription.device, config.transcription.compute_type)
        threading.Thread(target=preload_both, daemon=True).start()
        daemon_thread = threading.Thread(target=daemon.run, daemon=True)
        daemon_thread.start()
        watcher.start()

    @app.on_event("shutdown")
    async def shutdown_event():
        watcher.stop()
        daemon.shutdown()
        if daemon_thread:
            daemon_thread.join(timeout=5.0)

    return app


def _build_status(daemon: Daemon, config: Config, peak_holder: dict) -> dict:
    return {
        "state": daemon.state.value,
        "session_id": daemon._session_id,
        "wakeword": config.wakeword.word,
        "stop_phrase": config.wakeword.stop_phrase,
        "model": config.transcription.model,
        "realtime_model": config.transcription.realtime_model,
        "peak": peak_holder["value"],
        "language": config.transcription.language,
        "device": config.recording.device or "default",
    }
