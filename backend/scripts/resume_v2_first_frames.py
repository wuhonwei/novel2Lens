"""Resume V2 first frames for shots still missing after crash."""
from __future__ import annotations

import sys
import time

import httpx

API = "http://127.0.0.1:8790"
PROJ = "8e43e81f-d31c-4aba-9769-c54bcdc426d1"


def main() -> int:
    client = httpx.Client(base_url=API, timeout=600.0)
    client.get("/api/health").raise_for_status()

    # Cancel leftover active batches first (crash/restart often leaves stuck "running")
    jobs = client.get(f"/api/projects/{PROJ}/image-jobs?active_only=true").json().get("jobs") or []
    batches = {j.get("batch_id") for j in jobs if j.get("batch_id")}
    for bid in batches:
        client.post(f"/api/projects/{PROJ}/image-batches/{bid}/cancel")
        print(f"cancelled batch {bid}", flush=True)
    for _ in range(30):
        active = client.get(f"/api/projects/{PROJ}/image-jobs?active_only=true").json().get("jobs") or []
        if not active:
            break
        print(f"draining {len(active)} active…", flush=True)
        time.sleep(2)

    bundle = client.get(f"/api/projects/{PROJ}").json()
    missing = [s for s in (bundle.get("shots") or []) if not (s.get("first_frame_path") or "").strip()]
    print(f"missing first frames: {len(missing)}/{len(bundle.get('shots') or [])}", flush=True)
    if not missing:
        print("OK all first frames present", flush=True)
        return 0

    queued = 0
    errors = []
    for s in missing:
        r = client.post(f"/api/projects/{PROJ}/shots/{s['id']}/generate-first-frame")
        if r.status_code != 200:
            errors.append(f"镜{s.get('order_index')}: {r.status_code} {r.text[:200]}")
            print(f"  fail 镜{s.get('order_index')}: {r.status_code}", flush=True)
        else:
            queued += 1
            print(f"  queued 镜{s.get('order_index')} chapter={s.get('chapter_title','')}", flush=True)

    print(f"requeued {queued} errors={len(errors)}", flush=True)
    deadline = time.perf_counter() + 7200
    while time.perf_counter() < deadline:
        active = client.get(f"/api/projects/{PROJ}/image-jobs?active_only=true").json().get("jobs") or []
        if not active:
            break
        print(f"phase {len(active)}", flush=True)
        time.sleep(4)

    final = client.get(f"/api/projects/{PROJ}").json()
    shots = final.get("shots") or []
    with_path = sum(1 for s in shots if (s.get("first_frame_path") or "").strip())
    print(f"done frames={with_path}/{len(shots)}", flush=True)
    return 0 if with_path == len(shots) else 1


if __name__ == "__main__":
    sys.exit(main())
