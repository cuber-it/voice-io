"""voice-input — embeddable voice input library. Wakeword + Whisper."""

__version__ = "0.1.0"

from .pipeline       import VoiceInput
from .audio          import AudioStream, AudioBuffer, list_input_devices
from .detection      import WakewordDetector
from .transcription  import Transcriber, load_model

__all__ = [
    "VoiceInput",
    "AudioStream",
    "AudioBuffer",
    "WakewordDetector",
    "Transcriber",
    "load_model",
    "list_input_devices",
]
