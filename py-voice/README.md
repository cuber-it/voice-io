# voice-input — Python

Embeddable voice input library. Wake-word detection + Whisper transcription. Zero cloud, zero subscriptions. Part of [voice-io](https://github.com/cuber-it/voice-io).

## Install

```bash
pip install voice-input
```

## Use as library

```python
from voice_input import VoiceInput

voice = VoiceInput(
    wakeword="hey_jarvis",
    whisper_model="base",
    language="de",
)

# Capture one utterance (blocking):
text = voice.listen_once()
print(text)

# Continuous async loop:
async for text in voice.listen():
    print(f"You said: {text}")

# Background with callback:
voice.start(on_text=lambda t: print(t))
# ... later:
voice.stop()
```

## Run

```bash
# List microphone devices:
python3 -m voice_input --list-devices

# Listen and print:
python3 -m voice_input --wakeword hey_jarvis --model base --language de

# Capture once and exit:
python3 -m voice_input --once
```

## Pipeline

```
Microphone (sounddevice)
    ↓ float32 chunks (80ms)
WakewordDetector (openwakeword)
    ↓ triggered
AudioBuffer (record until silence)
    ↓ numpy array
Transcriber (faster-whisper)
    ↓ text
on_text callback / async yield
```

## Components

```python
from voice_input import (
    VoiceInput,          # full pipeline
    AudioStream,         # raw microphone stream
    AudioBuffer,         # record chunks into array
    WakewordDetector,    # trigger detection
    Transcriber,         # Whisper transcription
    list_input_devices,  # enumerate microphones
)
```

## Note

Hardware dependencies (sounddevice, openwakeword, faster-whisper) require system audio support.
For Docker/headless environments, use the [voice-io](https://github.com/cuber-it/voice-io) service instead.
