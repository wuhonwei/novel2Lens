"""Image QA helpers for the embedded Comfy pipeline.

Full PIL-based heuristics from 造像 are deferred: ``assess_image_bytes`` soft-passes
so downstream workers can run without optional Pillow/heavy QA dependencies.
"""

from __future__ import annotations

from typing import Any


def assess_image_bytes(data: bytes, **kwargs: Any) -> dict[str, Any]:
    """Soft-pass QA stub until full heuristics are wired in."""
    _ = data, kwargs
    return {"ok": True}
