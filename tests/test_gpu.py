"""Tests for GPU device resolution (gpu.resolve_devices)."""

import voice_io.gpu as gpu


def test_explicit_cpu_used_for_both():
    assert gpu.resolve_devices("cpu") == ("cpu", "cpu")


def test_explicit_cuda_used_for_both():
    assert gpu.resolve_devices("cuda") == ("cuda", "cuda")


def test_auto_without_cuda_is_all_cpu(monkeypatch):
    monkeypatch.setattr(gpu, "cuda_available", lambda: False)
    assert gpu.resolve_devices("auto") == ("cpu", "cpu")


def test_auto_with_big_gpu_uses_gpu_for_both(monkeypatch):
    monkeypatch.setattr(gpu, "cuda_available", lambda: True)
    monkeypatch.setattr(gpu, "gpu_total_vram_mb", lambda: 24000)
    assert gpu.resolve_devices("auto") == ("cuda", "cuda")


def test_auto_with_small_gpu_splits(monkeypatch):
    # MX150 case: 2 GB -> realtime on GPU, quality on CPU
    monkeypatch.setattr(gpu, "cuda_available", lambda: True)
    monkeypatch.setattr(gpu, "gpu_total_vram_mb", lambda: 2048)
    assert gpu.resolve_devices("auto") == ("cuda", "cpu")


def test_auto_with_unknown_vram_plays_safe(monkeypatch):
    # VRAM query failed -> keep quality on CPU
    monkeypatch.setattr(gpu, "cuda_available", lambda: True)
    monkeypatch.setattr(gpu, "gpu_total_vram_mb", lambda: None)
    assert gpu.resolve_devices("auto") == ("cuda", "cpu")


def test_threshold_boundary_is_inclusive(monkeypatch):
    monkeypatch.setattr(gpu, "cuda_available", lambda: True)
    monkeypatch.setattr(gpu, "gpu_total_vram_mb", lambda: gpu.DUAL_GPU_VRAM_MB)
    assert gpu.resolve_devices("auto") == ("cuda", "cuda")


def test_load_config_fills_resolved_devices(monkeypatch, tmp_path):
    import voice_io.config as cfgmod

    monkeypatch.setattr("voice_io.gpu.resolve_devices", lambda d: ("cuda", "cpu"))
    cfg = cfgmod.load_config(tmp_path / "nope.toml")  # missing -> defaults
    assert cfg.transcription.realtime_device == "cuda"
    assert cfg.transcription.quality_device == "cpu"
