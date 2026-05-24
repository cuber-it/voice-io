# Changelog

## [0.9.0] — 2026-04-17

### Added
- Web GUI with three-panel layout, VU meter, session management
- Dual-pass transcription (real-time medium + quality large-v3-turbo)
- Wake-word detection (openwakeword) with runtime on/off toggle
- Stop-phrase detection during recording
- Audio import with progress dialog (WAV, MP3, FLAC, OGG, M4A)
- Watch folder for automatic import
- Smart glossaries for improved term recognition
- Dictation macros with trigger phrase replacement
- AI text cleanup (Anthropic, OpenAI, Ollama)
- Multi-language support (10 languages)
- Multiple transcripts per session
- Audio player in transcript view
- Three themes (dark, sepia, light)
- Stereo-to-mono conversion for imported files
- Whisper hallucination filter
- Silence detection with auto-pause
- Docker support (Dockerfile + compose.yml)
- 73 tests

### Fixed
- Stereo WAV import crash (VAD requires mono)
- Upload progress tracking (now based on actual processing, not queue fill)

## [0.1.0] — 2026-04-12

### Added
- Project setup (pyproject.toml, venv, scripts)
- Initial structure evolved from diktaphon prototype
