from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger(__name__)


class H3ComfyClient:
    """Sync Comfy client aimed at the MiniMax H3 install (separate port)."""

    def __init__(self, base_url: str | None = None, timeout: float = 120.0) -> None:
        self.base_url = (base_url or settings.h3_comfy_base_url).rstrip("/")
        self.timeout = timeout

    def system_stats(self) -> dict[str, Any]:
        with httpx.Client(base_url=self.base_url, timeout=10.0) as client:
            r = client.get("/system_stats")
            r.raise_for_status()
            return r.json()

    def has_h3_nodes(self) -> bool:
        try:
            with httpx.Client(base_url=self.base_url, timeout=15.0) as client:
                r = client.get("/object_info/MiniMaxH3ImageToVideo")
                if r.status_code != 200:
                    return False
                data = r.json()
                return "MiniMaxH3ImageToVideo" in data
        except Exception:
            return False

    def is_ready(self) -> bool:
        try:
            self.system_stats()
            return self.has_h3_nodes()
        except Exception:
            return False

    def describe_server(self) -> dict[str, Any]:
        try:
            stats = self.system_stats()
            version = (stats.get("system") or {}).get("comfyui_version")
            h3 = self.has_h3_nodes()
            return {"up": True, "version": version, "h3": h3}
        except Exception as exc:
            return {"up": False, "version": None, "h3": False, "error": str(exc)}

    def wait_until_ready(self, timeout_s: float | None = None) -> None:
        timeout = timeout_s if timeout_s is not None else settings.h3_comfy_ready_timeout_s
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_ready():
                return
            time.sleep(settings.h3_comfy_poll_interval_s)
        info = self.describe_server()
        raise TimeoutError(
            f"ComfyUI H3 not ready at {self.base_url} within {timeout}s "
            f"(up={info.get('up')} version={info.get('version')} h3={info.get('h3')})"
        )

    def upload_image(self, path: Path, *, overwrite: bool = True) -> str:
        data = {"overwrite": "true" if overwrite else "false", "type": "input"}
        files = {"image": (path.name, path.read_bytes(), "image/png")}
        with httpx.Client(base_url=self.base_url, timeout=60.0) as client:
            r = client.post("/upload/image", data=data, files=files)
            r.raise_for_status()
            payload = r.json()
        name = payload.get("name") or path.name
        sub = payload.get("subfolder") or ""
        return f"{sub}/{name}" if sub else name

    def queue_prompt(self, workflow: dict[str, Any], client_id: str) -> str:
        body = {"prompt": workflow, "client_id": client_id}
        with httpx.Client(base_url=self.base_url, timeout=60.0) as client:
            r = client.post("/prompt", json=body)
            if r.status_code >= 400:
                detail = r.text
                log.error("H3 Comfy /prompt failed: %s", detail)
                raise RuntimeError(f"Comfy prompt rejected: {detail}")
            payload = r.json()
        prompt_id = payload.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"Comfy response missing prompt_id: {payload}")
        return str(prompt_id)

    def get_history(self, prompt_id: str) -> dict[str, Any] | None:
        with httpx.Client(base_url=self.base_url, timeout=30.0) as client:
            r = client.get(f"/history/{prompt_id}")
            r.raise_for_status()
            data = r.json()
        return data.get(prompt_id)

    def wait_for_prompt(self, prompt_id: str, timeout_s: float | None = None) -> dict[str, Any]:
        timeout = timeout_s if timeout_s is not None else settings.h3_job_timeout_s
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            hist = self.get_history(prompt_id)
            if not hist:
                time.sleep(settings.h3_job_poll_interval_s)
                continue
            status = hist.get("status") or {}
            status_str = str(status.get("status_str") or "").lower()
            messages = status.get("messages") or []
            if status_str == "error" or any(
                isinstance(m, (list, tuple)) and m and m[0] == "execution_error" for m in messages
            ):
                raise RuntimeError(f"Comfy job failed: {messages}")
            if status.get("completed") is True or status_str == "success":
                return hist
            if hist.get("outputs") and status.get("completed") is not False and status_str != "error":
                if "completed" not in status:
                    return hist
            time.sleep(settings.h3_job_poll_interval_s)
        raise TimeoutError(f"Comfy prompt {prompt_id} timed out")

    @staticmethod
    def extract_video_path(history: dict[str, Any], output_root: Path) -> Path:
        outputs = history.get("outputs") or {}
        for node_out in outputs.values():
            for key in ("videos", "gifs", "images"):
                items = node_out.get(key) or []
                for item in items:
                    filename = item.get("filename")
                    if not filename:
                        continue
                    subfolder = item.get("subfolder") or ""
                    if key != "videos" and not str(filename).lower().endswith((".mp4", ".webm", ".mov")):
                        continue
                    path = output_root / subfolder / filename if subfolder else output_root / filename
                    if path.exists():
                        return path
                    alt = output_root / "video" / filename
                    if alt.exists():
                        return alt
        for node_out in outputs.values():
            for items in node_out.values():
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    filename = item.get("filename")
                    if not filename or not str(filename).lower().endswith((".mp4", ".webm", ".mov")):
                        continue
                    subfolder = item.get("subfolder") or ""
                    path = output_root / subfolder / filename if subfolder else output_root / filename
                    if path.exists():
                        return path
        raise FileNotFoundError(f"No video file found in Comfy history outputs: {outputs}")

    def free_memory(self, *, unload_models: bool = True) -> None:
        """Ask H3 Comfy to unload models / free VRAM (best-effort)."""
        try:
            with httpx.Client(base_url=self.base_url, timeout=30.0) as client:
                client.post("/free", json={"unload_models": unload_models, "free_memory": True})
        except Exception:
            pass

    def interrupt(self) -> None:
        try:
            with httpx.Client(base_url=self.base_url, timeout=5.0) as client:
                client.post("/interrupt")
        except Exception:
            pass
