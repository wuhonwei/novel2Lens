# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import time

import httpx

API = "http://127.0.0.1:8790"
PROJ = "8e43e81f-d31c-4aba-9769-c54bcdc426d1"


def wait(c: httpx.Client) -> None:
    while c.get(f"/api/projects/{PROJ}/image-jobs?active_only=true").json().get("jobs"):
        print("waiting", flush=True)
        time.sleep(5)


def main() -> int:
    c = httpx.Client(base_url=API, timeout=120.0)
    c.get("/api/health").raise_for_status()
    bundle = c.get(f"/api/projects/{PROJ}").json()
    by = {a["name"]: a for a in bundle["assets"]}
    a = by["林砚之"]
    c.delete(f"/api/projects/{PROJ}/assets/{a['id']}/image", params={"field": "half"})
    print("half", c.post(f"/api/projects/{PROJ}/assets/{a['id']}/generate-image", params={"field": "half"}).status_code)
    wait(c)
    ch1 = next(ch for ch in bundle["chapters"] if ch["index"] == 0)
    shot = next(s for s in bundle["shots"] if s["chapter_id"] == ch1["id"] and s["order_index"] == 6)
    c.patch(f"/api/projects/{PROJ}/shots/{shot['id']}", json={"recompile": True})
    print("ff", c.post(f"/api/projects/{PROJ}/shots/{shot['id']}/generate-first-frame").status_code)
    wait(c)
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
