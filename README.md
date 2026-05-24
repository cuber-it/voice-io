# voice-io

Local voice recording and transcription. Whisper-powered.
No cloud, no account, no subscription.

**Speak. Transcribe. Done.**

---

## What it does

Record your voice, get a clean transcript.

- Dual-pass transcription: fast real-time preview + high-quality result after stop
- Smart glossaries for technical terms and jargon
- Dictation macros: trigger phrases → replacement text
- Watch folder: drop an audio file, get a transcript
- Wake-word activation and stop-phrase
- Web interface with session management
- Everything runs locally on your own hardware

---

## Tech Stack

| | |
|---|---|
| Transcription | faster-whisper (CTranslate2) |
| Real-time model | medium |
| Quality model | large-v3-turbo |
| Wake-word | openwakeword (local) |
| Web backend | FastAPI |
| Frontend | Vanilla JS |
| Container | Docker, single container |
| Default port | 12120 |

---

## Quick Start (Docker)

```bash
git clone https://github.com/cuber-it/voice-io
cd voice-io
cp config.example.toml config/config.toml
# edit config/config.toml — set your audio device
docker compose up -d
```

Open http://localhost:12120

### Find your audio device

```bash
docker run --rm --device /dev/snd voice-io python -c \
  "import sounddevice as sd; print(sd.query_devices())"
```

Set `device` in config.toml under `[recording]`.

### macOS

Docker on macOS cannot directly access the host microphone.
Options:
- Use the **watch folder** — record with QuickTime or your phone, drop the file in
- Route audio via BlackHole or Soundflower

Native macOS support is on the roadmap.

---

## Configuration

```toml
[recording]
device = "TONOR TM20"          # partial match, empty = system default

[transcription]
model = "large-v3-turbo"       # quality model (after recording)
realtime_model = "medium"      # fast model (during recording)
language = "de"                # de, en, fr, es, ...

[wakeword]
enabled = false                # true = wake-word start, false = GUI only
word = "hey jarvis"
stop_phrase = "over and out"
```

Full reference: `config.example.toml`

---

## Development

Linux, Python 3.12+.

```bash
git clone https://github.com/cuber-it/voice-io
cd voice-io
./scripts/setup.sh
source .venv/bin/activate
python -m voice_io.daemon
```

```bash
.venv/bin/pytest tests/
```

---

## Roadmap

v0.9.x — current: recording, transcription, web GUI, Docker

v1.0.0 — planned:
- AI text cleanup (Anthropic / OpenAI / Ollama)
- TTS output (Piper local, Edge TTS)
- Conversation mode
- MCP server (voice_record, voice_transcribe, voice_speak)
- Native macOS

---

## Disclaimer

This software is provided as-is, without warranty of any kind. It is a personal
project shared with the community. Use at your own risk. The authors are not
responsible for any data loss, missed recordings, or inaccurate transcriptions.
Whisper models may produce errors, hallucinations, or offensive content —
always review transcripts before use.

## License

MIT — see LICENSE.

*Built by [cuber IT service](https://www.uc-it.de).*
