from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from app.comfy_pipeline.comfy import ComfyClient


def _default_is_up(base_url: str) -> bool:
    return bool(ComfyClient(base_url).health().get("ok"))


def _default_start_process(*, python: str, root: str, port: int) -> None:
    subprocess.Popen(
        [python, "main.py", "--listen", "127.0.0.1", "--port", str(port)],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _default_stop_process(port: int) -> None:
    _kill_port_listeners(port)


def _kill_port_listeners(port: int) -> None:
    """Kill processes listening on *port* (Windows-first, mirrors aiImage Stop-PortListeners)."""
    script = (
        f"$conns = Get-NetTCPConnection -LocalPort {int(port)} -State Listen "
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


def _port_from_url(base_url: str, default: int = 8189) -> int:
    parsed = urlparse(base_url)
    if parsed.port:
        return int(parsed.port)
    return default


class ComfySupervisor:
    """On-demand ComfyUI process + idle model unload (/free) and optional process stop."""

    def __init__(
        self,
        *,
        base_url: str,
        root: str,
        python: str,
        idle_seconds: int = 180,
        stop_when_idle: bool = True,
        prefer_unload_over_restart: bool = True,
        client_factory: Callable[[str], Any] | None = None,
        start_process: Callable[[], None] | None = None,
        stop_process: Callable[[], None] | None = None,
        is_up: Callable[[], bool] | None = None,
        ready_timeout_seconds: float = 180.0,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.root = root
        self.python = python
        self.idle_seconds = idle_seconds
        self.stop_when_idle = stop_when_idle
        self.prefer_unload_over_restart = prefer_unload_over_restart
        self.ready_timeout_seconds = ready_timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self._port = _port_from_url(self.base_url)

        self._client_factory = client_factory or (lambda url: ComfyClient(url))
        self._start_process = start_process or (
            lambda: _default_start_process(python=self.python, root=self.root, port=self._port)
        )
        self._stop_process = stop_process or (lambda: _default_stop_process(self._port))
        self._is_up = is_up or (lambda: _default_is_up(self.base_url))

        self._last_activity_at: float | None = None
        self._idle_handled = False

    def _client(self) -> Any:
        return self._client_factory(self.base_url)

    def ensure_running(self) -> None:
        if self._health_ok():
            return
        self._start_process()
        deadline = time.monotonic() + self.ready_timeout_seconds
        while time.monotonic() < deadline:
            if self._health_ok() or self._is_up():
                self.note_activity()
                return
            time.sleep(self.poll_interval_seconds)
        raise TimeoutError(f"ComfyUI did not become ready at {self.base_url} within {self.ready_timeout_seconds}s")

    def _health_ok(self) -> bool:
        try:
            return bool(self._client().health().get("ok"))
        except Exception:
            return False

    def free_models(self) -> None:
        try:
            self._client().free_memory()
        except Exception:
            pass

    def release_for_llm(self) -> None:
        """Free Comfy VRAM so local LLMs can load.

        By default prefers /free unload without killing the process (faster flip).
        Full process stop still happens on idle timeout when stop_when_idle is True,
        or when prefer_unload_over_restart is False.
        """
        self.free_models()
        should_stop = self.stop_when_idle and not self.prefer_unload_over_restart
        if should_stop:
            try:
                self._stop_process()
            except Exception:
                pass
            deadline = time.monotonic() + 60.0
            while time.monotonic() < deadline:
                if not self._is_up():
                    break
                time.sleep(0.5)
        self._idle_handled = True
        self._last_activity_at = None

    def release_for_idle(self) -> None:
        """Idle path: unload and optionally stop the Comfy process."""
        self.free_models()
        if self.stop_when_idle:
            try:
                self._stop_process()
            except Exception:
                pass
            deadline = time.monotonic() + 60.0
            while time.monotonic() < deadline:
                if not self._is_up():
                    break
                time.sleep(0.5)
        self._idle_handled = True
        self._last_activity_at = None

    def note_activity(self) -> None:
        self._last_activity_at = time.monotonic()
        self._idle_handled = False

    def tick_idle(self, *, has_active_jobs: bool) -> None:
        if has_active_jobs:
            return
        if self._last_activity_at is None:
            return
        if self._idle_handled:
            return
        elapsed = time.monotonic() - self._last_activity_at
        if elapsed < self.idle_seconds:
            return
        self.release_for_idle()
