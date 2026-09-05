"""Retry storyboard for every chapter on an existing project (after VRAM release fix)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

API = "http://127.0.0.1:8790"
PROJ = "6a023d3f-24eb-4e7d-8d18-a839bdf09086"
REPORT = Path(__file__).resolve().parent / "qingduchuan_storyboard_retry_report.json"


def main() -> int:
    client = httpx.Client(base_url=API, timeout=1200.0)
    report: dict = {"project_id": PROJ, "chapters": [], "ok": False, "errors": []}
    try:
        health = client.get("/api/health")
        health.raise_for_status()
        print("health ok", flush=True)

        # Ensure LLM can load
        for i in range(30):
            probe = httpx.post(
                "http://127.0.0.1:11434/v1/chat/completions",
                json={
                    "model": "qwen2.5:32b",
                    "messages": [{"role": "user", "content": "ok"}],
                    "stream": False,
                },
                timeout=180.0,
            )
            if probe.status_code == 200:
                print("llm ready", flush=True)
                break
            print(f"llm probe {i}: {probe.status_code} {probe.text[:120]}", flush=True)
            time.sleep(5)
        else:
            report["errors"].append("llm not ready")
            REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return 1

        bundle = client.get(f"/api/projects/{PROJ}").json()
        chapters = sorted(bundle.get("chapters") or [], key=lambda c: c.get("index", 0))
        print(f"chapters {len(chapters)} assets {len(bundle.get('assets') or [])}", flush=True)

        for ch in chapters:
            title = ch.get("title") or ch["id"]
            print(f"storyboard {ch.get('index')} {title}…", flush=True)
            r = None
            for attempt in range(1, 4):
                r = client.post(
                    f"/api/projects/{PROJ}/chapters/{ch['id']}/storyboard",
                    params={"overwrite": "true"},
                )
                if r.status_code == 200:
                    break
                print(f"  attempt {attempt} → {r.status_code}: {r.text[:300]}", flush=True)
                time.sleep(10 * attempt)
            if r is None or r.status_code != 200:
                msg = f"{r.status_code if r else '?'}: {(r.text if r else '')[:800]}"
                report["errors"].append(f"{title}: {msg}")
                report["chapters"].append({"title": title, "ok": False})
                continue
            body = r.json()
            shots = [s for s in (body.get("shots") or []) if s.get("chapter_id") == ch["id"]]
            unready = sum(1 for s in shots if s.get("first_frame_unready"))
            report["chapters"].append(
                {"title": title, "ok": True, "shots": len(shots), "unready": unready}
            )
            print(f"  shots={len(shots)} unready={unready}", flush=True)

        final = client.get(f"/api/projects/{PROJ}").json()
        all_shots = final.get("shots") or []
        report["shots"] = len(all_shots)
        report["first_frame_unready_total"] = sum(1 for s in all_shots if s.get("first_frame_unready"))
        exported = client.post(f"/api/projects/{PROJ}/export")
        if exported.status_code == 200:
            report["export_path"] = exported.json().get("path")
        report["ok"] = (
            bool(report["chapters"])
            and all(c.get("ok") for c in report["chapters"])
            and report.get("first_frame_unready_total") == 0
            and not report["errors"]
        )
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"ok={report['ok']} shots={report['shots']} report={REPORT}", flush=True)
        return 0 if report["ok"] else 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
