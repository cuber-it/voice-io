"""Hardware detection for transcription device selection.

Decides whether the realtime and quality Whisper models run on GPU or CPU.
Both models stay cached together (see transcriber.py — no unloading), so on a
small GPU loading both would blow the VRAM. resolve_devices() splits them:
realtime on GPU, quality on CPU, when the GPU is too small for both.
"""

from __future__ import annotations

import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)

# Rough VRAM (MiB) needed to hold BOTH models on the GPU at once
# (e.g. medium + large-v3-turbo int8 + CUDA context). Below this, only the
# realtime model goes on the GPU and quality runs on CPU.
DUAL_GPU_VRAM_MB = 6000


def cuda_available() -> bool:
    """True if CTranslate2 (the faster-whisper backend) sees a CUDA device."""
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception as exc:  # noqa: BLE001
        logger.debug("CUDA check failed: %s", exc)
        return False


def gpu_total_vram_mb() -> int | None:
    """Total VRAM of GPU 0 in MiB via nvidia-smi, or None if unavailable."""
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return int(out.stdout.strip().splitlines()[0])
    except Exception as exc:  # noqa: BLE001
        logger.debug("VRAM query failed: %s", exc)
        return None


def resolve_devices(device: str, threshold_mb: int = DUAL_GPU_VRAM_MB) -> tuple[str, str]:
    """Resolve (realtime_device, quality_device) from a configured device.

    - explicit "cpu" / "cuda": used as-is for both stages (manual override).
    - "auto":
        no CUDA               -> ("cpu", "cpu")
        CUDA, VRAM >= threshold -> ("cuda", "cuda")   both models fit
        CUDA, VRAM <  threshold -> ("cuda", "cpu")    realtime GPU, quality CPU
    """
    dev = (device or "auto").strip().lower()
    if dev in ("cpu", "cuda"):
        return dev, dev

    if not cuda_available():
        logger.info("No CUDA device -> realtime=cpu, quality=cpu")
        return "cpu", "cpu"

    vram = gpu_total_vram_mb()
    if vram is not None and vram >= threshold_mb:
        logger.info("CUDA with %d MiB VRAM -> realtime=cuda, quality=cuda", vram)
        return "cuda", "cuda"

    logger.info("CUDA with %s MiB VRAM (< %d) -> realtime=cuda, quality=cpu",
                vram, threshold_mb)
    return "cuda", "cpu"
