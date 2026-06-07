"""Lazy mic: the daemon must not hold the mic open when idle (GUI-only mode)."""

from voice_io.config import Config
from voice_io.daemon import Daemon, State


def _daemon(wakeword: bool = False) -> Daemon:
    cfg = Config()
    cfg.wakeword.enabled = wakeword
    return Daemon(cfg)


def test_gui_idle_does_not_capture():
    d = _daemon(wakeword=False)
    assert d.state is State.IDLE
    assert d._should_capture() is False


def test_recording_captures():
    d = _daemon(wakeword=False)
    d._state = State.RECORDING
    assert d._should_capture() is True


def test_paused_keeps_capturing():
    d = _daemon(wakeword=False)
    d._state = State.PAUSED
    assert d._should_capture() is True


def test_wakeword_always_captures_even_idle():
    d = _daemon(wakeword=True)
    assert d.state is State.IDLE
    assert d._should_capture() is True
