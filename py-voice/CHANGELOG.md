# Changelog — voice-input (Python)

## 0.1.0 — 2026-05-22

- Initial extraction from voice-io service
- VoiceInput: full pipeline (wakeword → record → transcribe)
- AudioStream: continuous microphone stream
- AudioBuffer: collects chunks into numpy array
- WakewordDetector: openwakeword wrapper (float32 input)
- Transcriber: faster-whisper wrapper with hallucination filter
- CLI: `voice-input --wakeword hey_jarvis --model base`
- Async generator API: `async for text in voice.listen()`
