"""Create the 青川渡 verification project against a running API."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

NOVEL = Path(r"D:\Develop\aiVedioProducer\docs\novels\青渡川.txt")
API = "http://127.0.0.1:8790"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def main() -> None:
    text = NOVEL.read_text(encoding="utf-8")
    client = httpx.Client(base_url=API, timeout=600.0)
    health = client.get("/api/health")
    health.raise_for_status()
    for row in client.get("/api/projects").json():
        if row.get("title") == "青川渡":
            client.delete(f"/api/projects/{row['id']}")
    created = client.post(
        "/api/projects",
        json={
            "title": "青川渡",
            "text": text,
            "style": "半写实、东方江湖、电影布光、十六比九横构图",
        },
    )
    created.raise_for_status()
    bundle = created.json()
    pid = bundle["project"]["id"]
    client.patch(
        f"/api/projects/{pid}",
        json={"allow_fallback": True, "thinking": "medium"},
    ).raise_for_status()
    print("project", pid, "chapters", len(bundle["chapters"]))
    first = bundle["chapters"][0]
    print("extract", first["title"])
    extracted = client.post(f"/api/projects/{pid}/chapters/{first['id']}/extract")
    extracted.raise_for_status()
    proposals = extracted.json()["proposals"]
    print("proposals", len(proposals), [p.get("name") for p in proposals])
    items = [{**p, "accept": True} for p in proposals]
    confirmed = client.post(
        f"/api/projects/{pid}/chapters/{first['id']}/confirm",
        json={"items": items},
    )
    confirmed.raise_for_status()
    assets = confirmed.json()["assets"]
    print("assets", [(a["kind"], a["name"]) for a in assets])
    print("storyboard…")
    board = client.post(f"/api/projects/{pid}/chapters/{first['id']}/storyboard")
    board.raise_for_status()
    shots = board.json()["shots"]
    print("shots", len(shots))
    if shots:
        print("h3", shots[0]["h3_prompt"][:180])
    for asset in assets:
        field = "image" if asset["kind"] != "character" else None
        if asset["kind"] == "character":
            for f in ("half", "full"):
                client.post(
                    f"/api/projects/{pid}/assets/{asset['id']}/upload",
                    data={"field": f},
                    files={"file": (f"{f}.png", PNG, "image/png")},
                ).raise_for_status()
        else:
            client.post(
                f"/api/projects/{pid}/assets/{asset['id']}/upload",
                data={"field": "image"},
                files={"file": ("ref.png", PNG, "image/png")},
            ).raise_for_status()
    exported = client.post(f"/api/projects/{pid}/export")
    exported.raise_for_status()
    out = exported.json()
    print("export", out["path"], flush=True)
    Path(__file__).resolve().parents[2].joinpath("data").mkdir(parents=True, exist_ok=True)



if __name__ == "__main__":
    main()
