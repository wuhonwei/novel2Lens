"""Deprecated: 造像 HTTP client removed — use embedded ImageWorker + ComfyUI."""
from __future__ import annotations


class ZaoxiangError(RuntimeError):
    """Kept for any lingering imports; prefer ComfyError / HTTPException."""
