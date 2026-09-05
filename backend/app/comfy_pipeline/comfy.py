from __future__ import annotations

import time
from typing import Any

import httpx


class ComfyError(RuntimeError):
    pass


class ComfyClient:
    def __init__(self, base_url: str, timeout: float = 60.0, poll_interval: float = 0.75) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.poll_interval = poll_interval

    def health(self) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=5.0) as http:
                # system_stats is widely available; fall back to object_info
                r = http.get(f"{self.base_url}/system_stats")
                if r.status_code == 404:
                    r = http.get(f"{self.base_url}/object_info")
                r.raise_for_status()
                detail = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                ckpts = self.list_checkpoints()
                return {
                    "ok": True,
                    "detail": detail,
                    "checkpoints": ckpts,
                    "checkpoint_count": len(ckpts),
                }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def list_checkpoints(self) -> list[str]:
        """Return checkpoint filenames ComfyUI currently exposes (may be empty if wrong instance)."""
        try:
            with httpx.Client(timeout=8.0) as http:
                r = http.get(f"{self.base_url}/object_info/CheckpointLoaderSimple")
                r.raise_for_status()
                info = r.json()
            opts = (
                info.get("CheckpointLoaderSimple", {})
                .get("input", {})
                .get("required", {})
                .get("ckpt_name", [[]])[0]
            )
            return [str(x) for x in (opts or [])]
        except Exception:
            return []

    def upload_image(self, data: bytes, filename: str) -> str:
        with httpx.Client(timeout=self.timeout) as http:
            r = http.post(
                f"{self.base_url}/upload/image",
                files={"image": (filename, data, "application/octet-stream")},
                data={"type": "input", "overwrite": "true"},
            )
            r.raise_for_status()
            body = r.json()
        name = body.get("name")
        if not name:
            raise ComfyError(f"upload failed: {body}")
        return str(name)

    def queue_prompt(self, prompt: dict[str, Any], client_id: str | None = None) -> str:
        body: dict[str, Any] = {"prompt": prompt}
        if client_id:
            body["client_id"] = client_id
        with httpx.Client(timeout=self.timeout) as http:
            r = http.post(f"{self.base_url}/prompt", json=body)
            if r.status_code >= 400:
                raise ComfyError(f"prompt error {r.status_code}: {r.text[:800]}")
            data = r.json()
        pid = data.get("prompt_id")
        if not pid:
            raise ComfyError(f"no prompt_id: {data}")
        return str(pid)

    def get_history(self, prompt_id: str) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as http:
            r = http.get(f"{self.base_url}/history/{prompt_id}")
            r.raise_for_status()
            return r.json()

    def wait_history(self, prompt_id: str, timeout_seconds: float = 600.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            hist = self.get_history(prompt_id)
            last = hist.get(prompt_id) or {}
            if last.get("outputs"):
                return last
            status = (last.get("status") or {})
            if status.get("status_str") == "error" or status.get("completed") is False and status.get("messages"):
                msgs = status.get("messages") or []
                raise ComfyError(f"comfy failed: {msgs[:3]}")
            time.sleep(self.poll_interval)
        raise ComfyError(f"timeout waiting for {prompt_id}")

    def download_view(self, filename: str, subfolder: str = "", folder_type: str = "output") -> bytes:
        with httpx.Client(timeout=self.timeout) as http:
            r = http.get(
                f"{self.base_url}/view",
                params={"filename": filename, "subfolder": subfolder, "type": folder_type},
            )
            r.raise_for_status()
            return r.content

    def collect_images(self, history_entry: dict[str, Any]) -> list[bytes]:
        out: list[bytes] = []
        outputs = history_entry.get("outputs") or {}
        for node_out in outputs.values():
            for img in node_out.get("images") or []:
                out.append(
                    self.download_view(
                        img["filename"],
                        img.get("subfolder") or "",
                        img.get("type") or "output",
                    )
                )
        return out

    def interrupt(self) -> None:
        try:
            with httpx.Client(timeout=5.0) as http:
                http.post(f"{self.base_url}/interrupt")
        except Exception:
            pass

    def free_memory(self, *, unload_models: bool = True) -> None:
        """Ask ComfyUI to unload models / free VRAM (best-effort)."""
        try:
            with httpx.Client(timeout=30.0) as http:
                http.post(
                    f"{self.base_url}/free",
                    json={"unload_models": unload_models, "free_memory": True},
                )
        except Exception:
            pass

    def vram_free_gb(self) -> float | None:
        try:
            with httpx.Client(timeout=5.0) as http:
                r = http.get(f"{self.base_url}/system_stats")
                r.raise_for_status()
                devices = (r.json().get("devices") or [])
                if not devices:
                    return None
                free = float(devices[0].get("vram_free") or 0)
                return free / (1024**3)
        except Exception:
            return None
