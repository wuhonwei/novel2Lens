# -*- coding: utf-8 -*-
"""Regenerate identity-broken V2 assets + chapter1 shot6 after persona/prompt fixes."""
from __future__ import annotations

import sys
import time

import httpx

API = "http://127.0.0.1:8790"
PROJ = "8e43e81f-d31c-4aba-9769-c54bcdc426d1"
CHARS = ("周大人", "黑衣人", "陈守义")


def main() -> int:
    c = httpx.Client(base_url=API, timeout=120.0)
    c.get("/api/health").raise_for_status()
    bundle = c.get(f"/api/projects/{PROJ}").json()
    assets = bundle.get("assets") or []
    by_name = {a["name"]: a for a in assets}

    # cancel active
    active = c.get(f"/api/projects/{PROJ}/image-jobs?active_only=true").json().get("jobs") or []
    for bid in {j.get("batch_id") for j in active if j.get("batch_id")}:
        c.post(f"/api/projects/{PROJ}/image-batches/{bid}/cancel")
        print("cancelled", bid, flush=True)
    time.sleep(1)

    # clear + regenerate characters (full then half via field endpoints)
    for name in CHARS:
        a = by_name.get(name)
        if not a:
            print("MISSING", name, flush=True)
            continue
        aid = a["id"]
        for field in ("half", "full"):
            c.delete(f"/api/projects/{PROJ}/assets/{aid}/image", params={"field": field})
        print(f"regen {name} full+half", flush=True)
        r = c.post(f"/api/projects/{PROJ}/assets/{aid}/generate-image")
        print(" ", r.status_code, r.text[:160], flush=True)

    # props
    for a in assets:
        if a.get("kind") != "prop":
            continue
        aid = a["id"]
        c.delete(f"/api/projects/{PROJ}/assets/{aid}/image", params={"field": "image"})
        print(f"regen prop {a['name']}", flush=True)
        r = c.post(f"/api/projects/{PROJ}/assets/{aid}/generate-image")
        print(" ", r.status_code, r.text[:160], flush=True)

    # wait jobs
    deadline = time.perf_counter() + 7200
    while time.perf_counter() < deadline:
        active = c.get(f"/api/projects/{PROJ}/image-jobs?active_only=true").json().get("jobs") or []
        if not active:
            break
        print(f"active {len(active)}", flush=True)
        time.sleep(5)

    # recompile storyboards chapter 1 then regen shot 6 first frame
    chapters = bundle.get("chapters") or []
    ch1 = next((ch for ch in chapters if ch.get("index") == 0 or "第一章" in (ch.get("title") or "")), None)
    if not ch1:
        # refresh
        bundle = c.get(f"/api/projects/{PROJ}").json()
        chapters = bundle.get("chapters") or []
        ch1 = next((ch for ch in chapters if ch.get("index") == 0), None)
    if ch1:
        # force recompile via storyboard regenerate? use internal if API exists
        r = c.post(f"/api/projects/{PROJ}/chapters/{ch1['id']}/recompile-prompts")
        if r.status_code == 404:
            # fallback: regenerate storyboard keeps assets; try compile endpoint
            print("no recompile endpoint", r.status_code, flush=True)
        else:
            print("recompile", r.status_code, r.text[:200], flush=True)

    bundle = c.get(f"/api/projects/{PROJ}").json()
    shots = [s for s in (bundle.get("shots") or []) if s.get("chapter_id") == (ch1 or {}).get("id") and s.get("order_index") == 6]
    if not shots:
        shots = [s for s in (bundle.get("shots") or []) if s.get("order_index") == 6]
        # pick first chapter shot 6 by sorting chapters
    shot = None
    if ch1:
        shot = next(
            (
                s
                for s in (bundle.get("shots") or [])
                if s.get("chapter_id") == ch1["id"] and s.get("order_index") == 6
            ),
            None,
        )
    if shot:
        # Recompile prompts so names + distinct-face clause land in prompt_zh
        pr = c.patch(f"/api/projects/{PROJ}/shots/{shot['id']}", json={"recompile": True})
        print("recompile patch", pr.status_code, flush=True)
        print("regen first frame shot6", shot["id"], flush=True)
        r = c.post(f"/api/projects/{PROJ}/shots/{shot['id']}/generate-first-frame")
        print(" ", r.status_code, r.text[:200], flush=True)
        deadline = time.perf_counter() + 1800
        while time.perf_counter() < deadline:
            active = c.get(f"/api/projects/{PROJ}/image-jobs?active_only=true").json().get("jobs") or []
            if not active:
                break
            print(f"ff active {len(active)}", flush=True)
            time.sleep(4)

    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
