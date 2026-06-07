"""Config loading from TOML with sensible defaults."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_CONFIG_PATHS = [
    Path.home() / ".config" / "voice-io" / "config.toml",
    Path("/config/config.toml"),
]


@dataclass
class GeneralConfig:
    vault_dir: Path = field(
        default_factory=lambda: Path.home() / "Vault" / "voice-io"
    )
    watch_dir: Path | None = None


@dataclass
class WakewordConfig:
    enabled: bool = False
    word: str = "hey jarvis"
    threshold: float = 0.7
    stop_phrase: str = "over and out"


@dataclass
class RecordingConfig:
    sample_rate: int = 16000
    channels: int = 1
    device: str | None = None
    silence_timeout: int = 30
    silence_threshold: float = 0.01


@dataclass
class TranscriptionConfig:
    model: str = "large-v3-turbo"
    realtime_model: str = "medium"
    device: str = "auto"  # auto | cpu | cuda
    compute_type: str = "int8"
    language: str = "de"
    chunk_duration: int = 4
    beam_size: int = 5
    # Resolved from `device` at load time (see gpu.resolve_devices):
    realtime_device: str = "cpu"
    quality_device: str = "cpu"


@dataclass
class NetworkConfig:
    hf_offline: bool = False


@dataclass
class DaemonConfig:
    log_file: str = "voice-io.log"
    pid_file: str = "/tmp/voice-io.pid"


@dataclass
class Config:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    wakeword: WakewordConfig = field(default_factory=WakewordConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)
    transcription: TranscriptionConfig = field(default_factory=TranscriptionConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    daemon: DaemonConfig = field(default_factory=DaemonConfig)


def load_config(path: Path | None = None) -> Config:
    """Load config from TOML file. Returns defaults if no file found."""
    config_path = path
    if config_path is None:
        for candidate in DEFAULT_CONFIG_PATHS:
            if candidate.exists():
                config_path = candidate
                break

    if config_path is None or not config_path.exists():
        cfg = Config()
    else:
        with config_path.open("rb") as fh:
            data = tomllib.load(fh)
        cfg = _parse(data)

    _resolve_devices(cfg)
    return cfg


def _resolve_devices(cfg: Config) -> None:
    """Fill realtime_device/quality_device from the configured device."""
    from voice_io.gpu import resolve_devices

    rt, q = resolve_devices(cfg.transcription.device)
    cfg.transcription.realtime_device = rt
    cfg.transcription.quality_device = q


def _parse(data: dict) -> Config:
    general = data.get("general", {})
    wakeword = data.get("wakeword", {})
    recording = data.get("recording", {})
    transcription = data.get("transcription", {})
    network = data.get("network", {})
    daemon = data.get("daemon", {})

    vault_raw = general.get("vault_dir")
    vault_dir = (
        Path(vault_raw).expanduser() if vault_raw
        else Path.home() / "Vault" / "voice-io"
    )

    watch_raw = general.get("watch_dir")
    watch_dir = Path(watch_raw).expanduser() if watch_raw else None

    return Config(
        general=GeneralConfig(
            vault_dir=vault_dir,
            watch_dir=watch_dir,
        ),
        wakeword=WakewordConfig(
            enabled=wakeword.get("enabled", False),
            word=wakeword.get("word", "hey jarvis"),
            threshold=wakeword.get("threshold", 0.7),
            stop_phrase=wakeword.get("stop_phrase", "over and out"),
        ),
        recording=RecordingConfig(
            sample_rate=recording.get("sample_rate", 16000),
            channels=recording.get("channels", 1),
            device=recording.get("device"),
            silence_timeout=recording.get("silence_timeout", 30),
            silence_threshold=recording.get("silence_threshold", 0.01),
        ),
        transcription=TranscriptionConfig(
            model=transcription.get("model", "large-v3-turbo"),
            realtime_model=transcription.get("realtime_model", "medium"),
            device=transcription.get("device", "auto"),
            compute_type=transcription.get("compute_type", "int8"),
            language=transcription.get("language", "de"),
            chunk_duration=transcription.get("chunk_duration", 4),
            beam_size=transcription.get("beam_size", 5),
        ),
        network=NetworkConfig(
            hf_offline=network.get("hf_offline", False),
        ),
        daemon=DaemonConfig(
            log_file=daemon.get("log_file", "voice-io.log"),
            pid_file=daemon.get("pid_file", "/tmp/voice-io.pid"),
        ),
    )
