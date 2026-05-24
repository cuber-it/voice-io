"""Tests for voice_io.config module."""

import textwrap
from pathlib import Path

from voice_io.config import Config, load_config, _parse


class TestDefaults:

    def test_default_config_loads(self):
        config = load_config(Path("/nonexistent/path.toml"))
        assert isinstance(config, Config)

    def test_default_vault_dir(self):
        config = load_config(Path("/nonexistent/path.toml"))
        assert config.general.vault_dir == Path.home() / "Vault" / "voice-io"

    def test_default_wakeword(self):
        config = load_config(Path("/nonexistent/path.toml"))
        assert config.wakeword.word == "hey jarvis"
        assert config.wakeword.threshold == 0.7
        assert config.wakeword.enabled is False
        assert config.wakeword.stop_phrase == "over and out"

    def test_default_recording(self):
        config = load_config(Path("/nonexistent/path.toml"))
        assert config.recording.sample_rate == 16000
        assert config.recording.channels == 1
        assert config.recording.device is None
        assert config.recording.silence_timeout == 30
        assert config.recording.silence_threshold == 0.01

    def test_default_transcription(self):
        config = load_config(Path("/nonexistent/path.toml"))
        assert config.transcription.model == "large-v3-turbo"
        assert config.transcription.device == "cpu"
        assert config.transcription.compute_type == "int8"
        assert config.transcription.language == "de"
        assert config.transcription.chunk_duration == 4
        assert config.transcription.beam_size == 5

    def test_default_daemon(self):
        config = load_config(Path("/nonexistent/path.toml"))
        assert config.daemon.pid_file == "/tmp/voice-io.pid"


class TestFromFile:

    def test_load_full_config(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(textwrap.dedent("""\
            [general]
            vault_dir = "/data/my-vault"

            [wakeword]
            word = "computer"
            threshold = 0.8
            stop_phrase = "end recording"

            [recording]
            sample_rate = 44100
            channels = 2
            device = "TONOR"
            silence_timeout = 60
            silence_threshold = 0.02

            [transcription]
            model = "large-v3"
            chunk_duration = 6
            beam_size = 3

            [daemon]
            log_file = "/var/log/voice.log"
            pid_file = "/run/voice.pid"
        """))
        config = load_config(toml_file)

        assert config.general.vault_dir == Path("/data/my-vault")
        assert config.wakeword.word == "computer"
        assert config.wakeword.threshold == 0.8
        assert config.wakeword.stop_phrase == "end recording"
        assert config.recording.sample_rate == 44100
        assert config.recording.channels == 2
        assert config.recording.device == "TONOR"
        assert config.recording.silence_timeout == 60
        assert config.recording.silence_threshold == 0.02
        assert config.transcription.model == "large-v3"
        assert config.transcription.chunk_duration == 6
        assert config.daemon.log_file == "/var/log/voice.log"

    def test_partial_config(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(textwrap.dedent("""\
            [wakeword]
            word = "alexa"
        """))
        config = load_config(toml_file)

        assert config.wakeword.word == "alexa"
        assert config.wakeword.threshold == 0.7
        assert config.wakeword.enabled is False
        assert config.recording.silence_timeout == 30
        assert config.transcription.model == "large-v3-turbo"

    def test_vault_dir_tilde_expansion(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(textwrap.dedent("""\
            [general]
            vault_dir = "~/my-notes/voice"
        """))
        config = load_config(toml_file)
        assert "~" not in str(config.general.vault_dir)
        assert config.general.vault_dir == Path.home() / "my-notes" / "voice"

    def test_empty_file_returns_defaults(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text("")
        config = load_config(toml_file)
        assert config.wakeword.word == "hey jarvis"
        assert config.recording.silence_timeout == 30


class TestParse:

    def test_empty_dict(self):
        config = _parse({})
        assert isinstance(config, Config)
        assert config.wakeword.word == "hey jarvis"

    def test_unknown_sections_ignored(self):
        config = _parse({"unknown": {"foo": "bar"}})
        assert isinstance(config, Config)
