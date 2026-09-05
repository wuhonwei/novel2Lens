# -*- coding: utf-8 -*-
"""Second-pass regen: 黑衣人 + props after clothing/shape prompt harden."""
from __future__ import annotations

import sys
import time

import httpx

API = "http://127.0.0.1:8790"
PROJ = "8e43e81f-d31c-4aba-9769-c54bcdc426d1"


def main() -> int:
    c = httpx.Client(base_url=API, timeout=120.0)
    c.get("/api/health").raise_for_status()
    bundle = c.get(f"/api/projects/{PROJ}").json()
    assets = bundle.get("assets") or []
    by_name = {a["name"]: a for a in assets}

    active = c.get(f"/api/projects/{PROJ}/image-jobs?active_only=true").json().get("jobs") or []
    for bid in {j.get("batch_id") for j in active if j.get("batch_id")}:
        c.post(f"/api/projects/{PROJ}/image-batches/{bid}/cancel")

    # 黑衣人
    a = by_name["黑衣人"]
    for field in ("half", "full"):
        c.delete(f"/api/projects/{PROJ}/assets/{a['id']}/image", params={"field": field})
    r = c.post(f"/api/projects/{PROJ}/assets/{a['id']}/generate-image")
    print("黑衣人", r.status_code, flush=True)

    for a in assets:
        if a.get("kind") != "prop":
            continue
        c.delete(f"/api/projects/{PROJ}/assets/{a['id']}/image", params={"field": "image"})
        r = c.post(f"/api/projects/{PROJ}/assets/{a['id']}/generate-image")
        print("prop", a["name"], r.status_code, flush=True)

    deadline = time.perf_counter() + 7200
    while time.perf_counter() < deadline:
        active = c.get(f"/api/projects/{PROJ}/image-jobs?active_only=true").json().get("jobs") or []
        if not active:
            break
        print("active", len(active), flush=True)
        time.sleep(5)

    # refresh ch1 shot6 with better refs
    ch1 = next(ch for ch in (bundle.get("chapters") or []) if ch.get("index") == 0)
    shot = next(
        s
        for s in (bundle.get("shots") or [])
        if s.get("chapter_id") == ch1["id"] and s.get("order_index") == 6
    )
    c.patch(f"/api/projects/{PROJ}/shots/{shot['id']}", json={"recompile": True})
    r = c.post(f"/api/projects/{PROJ}/shots/{shot['id']}/generate-first-frame")
    print("shot6", r.status_code, flush=True)
    deadline = time.perf_counter() + 1800
    while time.perf_counter() < deadline:
        active = c.get(f"/api/projects/{PROJ}/image-jobs?active_only=true").json().get("jobs") or []
        if not active:
            break
        print("ff", len(active), flush=True)
        time.sleep(4)
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
