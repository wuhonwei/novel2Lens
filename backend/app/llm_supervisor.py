from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from urllib.request import urlopen


DEFAULT_LLM_PORT = 8080
DEFAULT_LLM_HEALTH = f"http://127.0.0.1:{DEFAULT_LLM_PORT}/v1/models"


def _kill_port_listeners(port: int) -> None:
    """Kill processes listening on *port* (prefer llama-server on 8080)."""
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


def _default_is_up(health_url: str = DEFAULT_LLM_HEALTH) -> bool:
    try:
        with urlopen(health_url, timeout=3) as resp:  # noqa: S310 — local health check
            return 200 <= int(getattr(resp, "status", 200)) < 400
    except Exception:
        return False


def _default_start_cmd() -> None:
    """Lazy-start Flash-Next via start-llm.ps1 when present."""
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "start-llm.ps1"
    if not script.is_file():
        raise FileNotFoundError(f"Missing LLM start script: {script}")
    subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        cwd=str(repo_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _default_stop_cmd(port: int = DEFAULT_LLM_PORT) -> None:
    _kill_port_listeners(port)


class LlmSupervisor:
    """Hard mutex gate + stop/start for Flash-Next (llama-server :8080)."""

    def __init__(
        self,
        *,
        stop_cmd: Callable[[], None] | None = None,
        start_cmd: Callable[[], None] | None = None,
        is_up: Callable[[], bool] | None = None,
        port: int = DEFAULT_LLM_PORT,
        ready_timeout_seconds: float = 900.0,
        poll_interval_seconds: float = 2.0,
        release_timeout_seconds: float = 60.0,
        settle_seconds: float = 15.0,
    ) -> None:
        self._port = port
        self._stop_cmd = stop_cmd or (lambda: _default_stop_cmd(self._port))
        self._start_cmd = start_cmd or _default_start_cmd
        self._is_up = is_up or (lambda: _default_is_up(f"http://127.0.0.1:{self._port}/v1/models"))
        self.ready_timeout_seconds = ready_timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.release_timeout_seconds = release_timeout_seconds
        self.settle_seconds = settle_seconds
        self._image_busy = False

    @property
    def image_busy(self) -> bool:
        return self._image_busy

    def set_image_busy(self, busy: bool) -> None:
        self._image_busy = bool(busy)
        if self._image_busy:
            self.stop_llm()

    def stop_llm(self) -> None:
        """Kill Flash-Next and wait until the port is down + a short RAM settle."""
        try:
            self._stop_cmd()
        except Exception:
            pass
        deadline = time.monotonic() + self.release_timeout_seconds
        while time.monotonic() < deadline:
            if not self._is_up():
                break
            try:
                self._stop_cmd()
            except Exception:
                pass
            time.sleep(min(1.0, self.poll_interval_seconds))
        # OS may still be reclaiming GGUF pages; give RAM a beat before Comfy loads.
        if self.settle_seconds > 0:
            time.sleep(self.settle_seconds)

    def wait_released(self) -> None:
        """Block until LLM health is down (no extra settle). Used by worker preflight."""
        deadline = time.monotonic() + self.release_timeout_seconds
        while time.monotonic() < deadline:
            if not self._is_up():
                return
            time.sleep(min(1.0, self.poll_interval_seconds))
        raise TimeoutError(f"LLM still responding on port {self._port} after stop")

    def ensure_llm(self) -> None:
        """Lazy-start LLM for text routes; no-op while image pipeline holds the mutex."""
        if self._image_busy:
            return
        if self._is_up():
            return
        self._start_cmd()
        deadline = time.monotonic() + self.ready_timeout_seconds
        while time.monotonic() < deadline:
            if self._is_up():
                return
            time.sleep(self.poll_interval_seconds)
        raise TimeoutError(f"LLM did not become ready on port {self._port} within {self.ready_timeout_seconds}s")
