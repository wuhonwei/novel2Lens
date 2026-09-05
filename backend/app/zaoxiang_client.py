"""HTTP client for 造像 (aiImage) generate / edit jobs."""
from __future__ import annotations

import time
from typing import Any

import httpx


class ZaoxiangError(RuntimeError):
    pass


class ZaoxiangClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def health(self) -> dict[str, Any]:
        with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
            r = client.get("/api/health")
            r.raise_for_status()
            return r.json()

    def create_generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
            r = client.post("/api/jobs/generate", json=payload)
            if r.status_code >= 400:
                raise ZaoxiangError(f"generate failed: {r.status_code} {r.text[:500]}")
            return r.json()

    def create_edit(
        self,
        *,
        prompt: str,
        image_bytes: bytes,
        filename: str = "full.png",
        aspect: str = "3:4",
        labels: str = "全身参考",
        project: str | None = None,
    ) -> dict[str, Any]:
        data = {
            "prompt": prompt,
            "aspect": aspect,
            "labels": labels,
            "project": project or "",
        }
        files = {"files": (filename, image_bytes, "image/png")}
        with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
            r = client.post("/api/jobs/edit", data=data, files=files)
            if r.status_code >= 400:
                raise ZaoxiangError(f"edit failed: {r.status_code} {r.text[:500]}")
            return r.json()

    def get_job(self, job_id: str) -> dict[str, Any]:
        with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
            r = client.get(f"/api/jobs/{job_id}")
            if r.status_code >= 400:
                raise ZaoxiangError(f"job read failed: {r.status_code} {r.text[:500]}")
            return r.json()

    def wait_job(self, job_id: str, *, poll_s: float = 2.0, timeout_s: float = 900.0) -> dict[str, Any]:
        deadline = time.time() + timeout_s
        last: dict[str, Any] = {}
        while time.time() < deadline:
            last = self.get_job(job_id)
            status = (last.get("status") or "").lower()
            if status in {"succeeded", "failed", "cancelled", "canceled"}:
                return last
            time.sleep(poll_s)
        raise ZaoxiangError(f"job {job_id} timed out after {timeout_s}s (last={last.get('status')})")

    def download_image(self, image_id: str) -> bytes:
        with httpx.Client(base_url=self.base_url, timeout=120.0) as client:
            r = client.get(f"/api/images/{image_id}")
            if r.status_code >= 400:
                raise ZaoxiangError(f"download failed: {r.status_code} {r.text[:300]}")
            return r.content

    def first_success_image_id(self, job: dict[str, Any]) -> str:
        images = job.get("images") or []
        for img in images:
            if (img.get("role") or "") == "success" and img.get("id"):
                return str(img["id"])
        for img in images:
            if img.get("id"):
                return str(img["id"])
        raise ZaoxiangError(f"job {job.get('id')} has no images (status={job.get('status')} error={job.get('error')})")
