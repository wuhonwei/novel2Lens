# -*- coding: utf-8 -*-
"""Unload local Ollama models so Comfy can claim VRAM."""
from __future__ import annotations

import logging
from typing import Any
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

DEFAULT_OLLAMA = "http://127.0.0.1:11434"


def list_ollama_running(base_url: str = DEFAULT_OLLAMA, *, timeout: float = 5.0) -> list[str]:
    """Return model names currently loaded in Ollama (best-effort)."""
    url = base_url.rstrip("/") + "/api/ps"
    try:
        with urlopen(url, timeout=timeout) as resp:  # noqa: S310 — local
            import json

            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        log.debug("ollama ps failed: %s", exc)
        return []
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return []
    names: list[str] = []
    for row in models:
        if not isinstance(row, dict):
            continue
        name = (row.get("name") or row.get("model") or "").strip()
        if name:
            names.append(name)
    return names


def unload_ollama_model(name: str, base_url: str = DEFAULT_OLLAMA, *, timeout: float = 15.0) -> None:
    """Ask Ollama to drop a model from VRAM (keep_alive=0)."""
    import json

    url = base_url.rstrip("/") + "/api/generate"
    body = json.dumps({"model": name, "prompt": "", "keep_alive": 0, "stream": False}).encode("utf-8")
    req = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310 — local
            resp.read()
    except Exception as exc:  # noqa: BLE001
        log.warning("unload ollama %s failed: %s", name, exc)


def unload_all_ollama(base_url: str = DEFAULT_OLLAMA) -> list[str]:
    """Unload every running Ollama model. Returns names attempted."""
    names = list_ollama_running(base_url)
    done: list[str] = []
    for name in names:
        unload_ollama_model(name, base_url)
        done.append(name)
    return done
