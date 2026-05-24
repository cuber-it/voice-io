# Konzept: Voice-to-Claude Frontend

## Idee

voice-io wird zum universellen Sprach-Frontend fuer Claude (und andere LLMs).
User redet, Claude antwortet — gesprochen. Wie ein Sprachassistent,
aber mit Claude-Intelligenz dahinter.

## Architektur

```
         Browser / Mic
              |
              v
    +-------------------+
    |     voice-io      |
    |  (bestehendes     |
    |   System)         |
    +-------------------+
    | Whisper (STT)     |  <-- haben wir schon
    | Audio Capture     |  <-- haben wir schon
    | Web GUI           |  <-- haben wir schon
    +--------+----------+
             |
             | Text (User-Frage)
             v
    +-------------------+
    |  Conversation     |
    |  Manager          |
    +-------------------+
    | Chat History      |
    | System Prompt     |
    | Tool Routing      |
    +--------+----------+
             |
             | API Call
             v
    +-------------------+
    |  Provider Layer   |
    +-------------------+
    | Claude API        |  <-- Anthropic SDK
    | OpenAI API        |  <-- optional
    | Ollama (lokal)    |  <-- fuer schnelle Antworten
    +--------+----------+
             |
             | Text (Antwort)
             v
    +-------------------+
    |  TTS Engine       |
    +-------------------+
    | Piper (lokal)     |  <-- Open Source, schnell, deutsch
    | Edge TTS          |  <-- Microsoft, kostenlos, gut
    | OpenAI TTS        |  <-- beste Qualitaet, kostet
    +--------+----------+
             |
             v
         Speaker / Browser Audio
```

## Bausteine

### Schon vorhanden (voice-io)
- Mic-Capture + Streaming
- Whisper Realtime-Transkription
- Web-GUI mit WebSocket
- Wake-Word Detection
- Docker-Deployment

### Neu zu bauen

#### 1. Conversation Manager
- Chat-History pro Gespraech (in-memory + optional persistent)
- System-Prompt konfigurierbar (Persona, Kontext, Regeln)
- Konversations-Modi:
  - **Frage/Antwort** — einzelne Fragen, keine History
  - **Gespraech** — mit History, Kontext bleibt erhalten
  - **Diktat-Assistent** — korrigiert, strukturiert, fragt nach

#### 2. Provider Layer
```toml
[llm]
# Primaer-Provider fuer Konversation
provider = "claude"           # claude | openai | ollama
model = "claude-sonnet-4-6"

# API Key (oder aus Env)
api_key_env = "ANTHROPIC_API_KEY"

# Fallback fuer schnelle Antworten
fast_provider = "ollama"
fast_model = "llama3.2"

# Max Tokens, Temperature etc.
max_tokens = 1024
temperature = 0.7
```

Implementierung via Anthropic Python SDK:
```python
from anthropic import Anthropic

client = Anthropic()  # API Key aus ENV
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    system="Du bist ein hilfreicher Assistent...",
    messages=conversation_history,
)
```

#### 3. TTS Engine
Beste Option fuer lokal + deutsch: **Piper TTS**
- Open Source, laeuft auf CPU
- Deutsche Stimmen verfuegbar (thorsten, eva)
- ~200ms Latenz, Streaming moeglich
- Kein API Key, kein Netz

```toml
[tts]
engine = "piper"              # piper | edge | openai | none
model = "de_DE-thorsten-high"
speed = 1.0
```

Fallback: **Edge TTS** (Microsoft, kostenlos, sehr gute Qualitaet, braucht Netz)

#### 4. GUI-Erweiterung
Neuer Modus in der Web-GUI: "Conversation"
- Chat-Ansicht statt Transkript-Ansicht
- User-Nachrichten (aus Whisper) + Claude-Antworten
- Antwort wird gesprochen UND als Text angezeigt
- Toggle: Auto-TTS an/aus
- Provider-Auswahl in Settings

## Datenfluesse

### Sprach-Eingabe → Claude → Sprach-Ausgabe
```
1. User sagt "Hey Jarvis"           → Wake-Word
2. User spricht Frage               → Whisper transkribiert live
3. User sagt "Over and out"         → Stop-Phrase
4. Transkript geht an Conv. Manager → baut Messages-Array
5. API-Call an Claude                → Antwort-Text
6. Text an TTS                      → Audio-Stream
7. Audio an Browser/Speaker          → User hoert Antwort
8. Alles in Chat-History gespeichert
```

### Latenz-Budget (realistisch)
| Schritt | Dauer |
|---------|-------|
| Whisper Transkription | ~2-4s (nach Stop) |
| Claude API (Sonnet) | ~1-3s |
| Piper TTS | ~0.5s |
| **Gesamt** | **~4-8s** |

Nicht Echtzeit-Konversation, aber akzeptabel fuer Frage/Antwort.
Mit Ollama lokal statt Claude API: ~2-4s gesamt.

## MCP-Integration

voice-io kann als MCP-Server Tools bereitstellen:

```json
{
  "tools": [
    {
      "name": "voice_record",
      "description": "Start recording from microphone"
    },
    {
      "name": "voice_transcribe",
      "description": "Transcribe an audio file"
    },
    {
      "name": "voice_speak",
      "description": "Speak text via TTS"
    },
    {
      "name": "voice_listen",
      "description": "Listen for speech and return text"
    }
  ]
}
```

Damit kann jeder MCP-Client (Claude Code, heinzel, etc.)
Sprach-I/O nutzen ohne eigene Audio-Implementierung.

## Umsetzung — Phasen

### Phase A: TTS einbauen
- Piper TTS in Docker installieren
- TTS-Endpoint in API: POST /api/speak { text, lang }
- Play-Button bei Claude-Antworten in GUI

### Phase B: Conversation Manager
- Chat-History Modul
- Claude API Anbindung (Anthropic SDK)
- Conversation-Mode in GUI

### Phase C: Voice Loop
- Automatischer Roundtrip: Whisper → Claude → TTS
- Wake-Word startet Frage, Stop-Phrase sendet ab
- Antwort wird automatisch gesprochen

### Phase D: MCP Server
- voice-io als MCP-Server
- Tools: record, transcribe, speak, listen
- Nutzbar aus Claude Code und heinzel

## Abhaengigkeiten

```
anthropic>=0.40        # Claude API SDK
piper-tts>=1.0         # oder edge-tts>=6.0
```

## Abgrenzung

Das ist KEIN Klon von Alexa/Siri/Google Assistant.
Das ist ein **programmierbares Sprach-Interface** fuer LLMs.
Offen, lokal, konfigurierbar, erweiterbar.
