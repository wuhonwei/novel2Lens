from __future__ import annotations

import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from app.config import settings
from app.h3_pipeline.comfy_client import H3ComfyClient

log = logging.getLogger(__name__)

_process: subprocess.Popen[Any] | None = None
_lock = threading.Lock()


def _build_launch_command() -> list[str]:
    return [
        str(settings.h3_comfy_python),
        "-s",
        str(settings.h3_comfy_main),
        "--listen",
        settings.h3_comfy_host,
        "--port",
        str(settings.h3_comfy_port),
        "--models-directory",
        str(settings.h3_shared_models),
        "--input-directory",
        str(settings.h3_shared_input),
        "--output-directory",
        str(settings.h3_shared_output),
        "--disable-pinned-memory",
        "--disable-async-offload",
    ]


def ensure_h3_comfy_running(client: H3ComfyClient | None = None) -> dict[str, Any]:
    """Start H3 Comfy headless if needed. Never kill on backend exit."""
    global _process
    client = client or H3ComfyClient()
    with _lock:
        if client.is_ready():
            info = client.describe_server()
            return {
                "status": "already_running",
                "url": settings.h3_comfy_base_url,
                "pid": None,
                **info,
            }

        occupied = client.describe_server()
        if occupied.get("up") and not occupied.get("h3"):
            raise RuntimeError(
                f"{settings.h3_comfy_base_url} 已被非 MiniMax H3 的 ComfyUI "
                f"(version={occupied.get('version')}) 占用。请先关闭该进程后再启动引擎。"
            )

        if _process is not None and _process.poll() is None:
            log.info("Waiting for existing H3 Comfy child process pid=%s", _process.pid)
            client.wait_until_ready()
            info = client.describe_server()
            return {
                "status": "starting",
                "url": settings.h3_comfy_base_url,
                "pid": _process.pid,
                **info,
            }

        python = Path(settings.h3_comfy_python)
        main = Path(settings.h3_comfy_main)
        models = Path(settings.h3_shared_models)
        if not python.exists():
            raise FileNotFoundError(f"H3 Comfy python not found: {python}")
        if not main.exists():
            raise FileNotFoundError(f"H3 Comfy main.py not found: {main}")
        if not models.exists():
            raise FileNotFoundError(f"Shared models missing: {models}")

        cmd = _build_launch_command()
        log.info("Launching H3 ComfyUI: %s", " ".join(cmd))
        creationflags = 0
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        _process = subprocess.Popen(
            cmd,
            cwd=str(settings.h3_comfy_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        client.wait_until_ready()
        info = client.describe_server()
        return {
            "status": "started",
            "url": settings.h3_comfy_base_url,
            "pid": _process.pid,
            **info,
        }


def h3_comfy_process_info() -> dict[str, Any]:
    if _process is None:
        return {"managed": False, "pid": None, "alive": False}
    alive = _process.poll() is None
    return {"managed": True, "pid": _process.pid, "alive": alive}


def _kill_h3_port_listeners() -> None:
    """Force-stop whatever is listening on the H3 Comfy port (Windows-first)."""
    port = int(settings.h3_comfy_port)
    script = (
        f"$conns = Get-NetTCPConnection -LocalPort {port} -State Listen "
        "-ErrorAction SilentlyContinue; "
        "foreach ($c in @($conns)) { "
        "if ($c.OwningProcess) { Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue } "
        "}"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def release_h3_for_image_work() -> dict[str, Any]:
    """Make room for image/first-frame Comfy on a shared GPU.

    H3 fl2va (UNET + Qwen3-VL) and Qwen Image Edit cannot coexist safely on one
    card — leaving H3 warm after video gen is a common OOM freeze trigger.
    """
    global _process
    client = H3ComfyClient()
    info = client.describe_server()
    if not info.get("up"):
        return {"status": "h3_down", **info}

    with _lock:
        try:
            client.interrupt()
        except Exception:
            pass
        client.free_memory()
        if not settings.h3_stop_for_image:
            return {"status": "freed", **client.describe_server()}

        if _process is not None and _process.poll() is None:
            try:
                _process.terminate()
                _process.wait(timeout=8)
            except Exception:
                try:
                    _process.kill()
                except Exception:
                    pass
            _process = None

        _kill_h3_port_listeners()
        time.sleep(1.0)
        return {"status": "stopped_for_image", "url": settings.h3_comfy_base_url}
