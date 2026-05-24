# voice-io — Features

## Record. Transcribe. Refine.

voice-io is a self-hosted voice recording and transcription service.
Powered by Whisper, running locally on your hardware. No cloud, no account, no subscription.

---

### Real-Time Transcription

See your words appear as you speak. voice-io uses a dual-pass approach:
a fast model transcribes in real-time during recording, while a high-quality
model automatically refines the result after you stop. Best of both worlds —
speed and accuracy.

### Multi-Language Support

Record in German, English, French, Spanish, Italian, Portuguese, Dutch,
Polish, Japanese, or Chinese. Switch languages per session. Transcribe the
same recording in multiple languages — one audio, unlimited transcripts.

### Wake-Word & Stop-Phrase

Say "Hey Jarvis" to start recording, "Over and Out" to stop.
Both fully configurable. Or use the web interface — your choice.

### Smart Glossaries

Custom word lists that improve recognition of technical terms, brand names,
and jargon. Select one or more glossaries per recording session.
Whisper understands "Claude Code" instead of guessing "Claude Coat".

### Dictation Macros

Speak trigger phrases that get replaced with configured text.
Say "new paragraph" and get a line break. Say "standard greeting" and get
your full signature block. Built-in formatting macros included,
create your own in seconds.

### AI-Powered Text Cleanup

Transform raw dictation into polished prose with one click.
Choose a writing style — standard, technical, business, or book prose.
Bring your own API key (Anthropic Claude, OpenAI, or local Ollama).
Create custom style profiles for your specific needs.

### Audio Import & Watch Folder

Record on your phone or dictation device, drop the file in the watch folder —
voice-io picks it up automatically, converts it, and transcribes.
Supports WAV, MP3, FLAC, OGG, M4A.

### Web Interface

Clean three-panel layout with live VU meter, session management,
audio player, and transcript viewer. Works on desktop, tablet, and phone.
Three themes: dark, sepia, and light. All panels resizable.

### Session Management

Each recording is a session with its own audio file and any number of
transcripts. Rename, delete, re-transcribe, clean up — all from the
web interface. Transcript tree shows all versions at a glance.

### Self-Hosted & Private

Runs as a Docker container on your own server. Audio never leaves your
network. Whisper models are cached locally after first download.
No API keys needed for recording and transcription — only for the
optional AI cleanup feature.

### Configurable Everything

Audio device, language, Whisper model, silence timeout, detection thresholds,
wake-word, stop-phrase, glossaries, macros, cleanup prompts — all configurable
via web interface or TOML config file.

---

## Tech Specs

| | |
|---|---|
| Transcription Engine | faster-whisper (CTranslate2) |
| Real-Time Model | medium (0.67x realtime on CPU) |
| Quality Model | large-v3-turbo (auto after stop) |
| Wake-Word | openwakeword (local, no API key) |
| Web Framework | FastAPI + vanilla JS |
| Container | Docker, single container |
| Audio Formats | WAV, MP3, FLAC, OGG, M4A |
| Languages | 10+ (configurable) |
| LLM Cleanup | Anthropic, OpenAI, Ollama (BYOK) |
| Port | 12120 (configurable) |

---

*voice-io is built by [cuber IT service](https://www.uc-it.de).
Available as free download. Professional support and customization available.*
