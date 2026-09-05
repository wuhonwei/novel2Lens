# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import time

import httpx

API = "http://127.0.0.1:8790"
PROJ = "8e43e81f-d31c-4aba-9769-c54bcdc426d1"


def wait_idle(c: httpx.Client, label: str, timeout: float = 3600) -> None:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        jobs = c.get(f"/api/projects/{PROJ}/image-jobs?active_only=true").json().get("jobs") or []
        print(f"{label} active={len(jobs)}", flush=True)
        if not jobs:
            return
        time.sleep(5)
    raise TimeoutError(label)


def main() -> int:
    c = httpx.Client(base_url=API, timeout=120.0)
    c.get("/api/health").raise_for_status()
    wait_idle(c, "drain")

    bundle = c.get(f"/api/projects/{PROJ}").json()
    by = {a["name"]: a for a in bundle["assets"]}
    a = by["黑衣人"]
    if not a.get("half_path"):
        print("enqueue 黑衣人 half", flush=True)
        c.post(f"/api/projects/{PROJ}/assets/{a['id']}/generate-image", params={"field": "half"}).raise_for_status()
    for asset in bundle["assets"]:
        if asset["kind"] == "prop" and not asset.get("image_path"):
            print("enqueue prop", asset["name"], flush=True)
            c.post(f"/api/projects/{PROJ}/assets/{asset['id']}/generate-image").raise_for_status()
    wait_idle(c, "assets")

    bundle = c.get(f"/api/projects/{PROJ}").json()
    ch1 = next(ch for ch in bundle["chapters"] if ch["index"] == 0)
    shot = next(s for s in bundle["shots"] if s["chapter_id"] == ch1["id"] and s["order_index"] == 6)
    c.patch(f"/api/projects/{PROJ}/shots/{shot['id']}", json={"recompile": True}).raise_for_status()
    print("enqueue shot6", flush=True)
    c.post(f"/api/projects/{PROJ}/shots/{shot['id']}/generate-first-frame").raise_for_status()
    wait_idle(c, "ff", timeout=1800)
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
