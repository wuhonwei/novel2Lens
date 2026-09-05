"""青渡川自主测试V2 — 国漫3D：资产→参考图→全章分镜→全部首帧。"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

NOVEL = Path(r"D:\Develop\aiVedioProducer\docs\novels\青渡川.txt")
API = "http://127.0.0.1:8790"
TITLE = "青渡川自主测试V2"
STYLE = "国漫3D"
REPORT = Path(__file__).resolve().parent / "qingduchuan_v2_report.json"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def write_report(payload: dict) -> None:
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report {REPORT}", flush=True)


def wait_jobs(client: httpx.Client, pid: str, timeout: float, poll: float) -> dict[str, int]:
    deadline = time.perf_counter() + timeout
    last = ""
    while time.perf_counter() < deadline:
        active = client.get(f"/api/projects/{pid}/image-jobs?active_only=true").json().get("jobs") or []
        if not active:
            break
        label = f"{len(active)}:{sorted({(j.get('phase') or j.get('status') or '?') for j in active})}"
        if label != last:
            print(f"phase {label}", flush=True)
            last = label
        time.sleep(poll)
    else:
        raise RuntimeError("timeout waiting image jobs")
    all_jobs = client.get(f"/api/projects/{pid}/image-jobs?active_only=false").json().get("jobs") or []
    counts: dict[str, int] = {}
    for j in all_jobs:
        counts[j.get("status") or "?"] = counts.get(j.get("status") or "?", 0) + 1
    return counts


def wait_llm() -> None:
    for i in range(40):
        try:
            r = httpx.post(
                "http://127.0.0.1:11434/v1/chat/completions",
                json={"model": "qwen2.5:32b", "messages": [{"role": "user", "content": "ok"}], "stream": False},
                timeout=180.0,
            )
            if r.status_code == 200:
                print("llm ready", flush=True)
                return
            print(f"llm {i}: {r.status_code}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"llm {i}: {exc}", flush=True)
        time.sleep(5)
    raise RuntimeError("llm not ready")


def main() -> int:
    report: dict = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ok": False,
        "title": TITLE,
        "style": STYLE,
        "errors": [],
        "timings_sec": {},
    }
    t0 = time.perf_counter()
    text = NOVEL.read_text(encoding="utf-8-sig")
    client = httpx.Client(base_url=API, timeout=1200.0)
    try:
        client.get("/api/health").raise_for_status()
        for row in client.get("/api/projects").json():
            if row.get("title") == TITLE:
                client.delete(f"/api/projects/{row['id']}").raise_for_status()
                print(f"deleted prior {row['id']}", flush=True)

        step = time.perf_counter()
        created = client.post("/api/projects", json={"title": TITLE, "text": text, "style": STYLE})
        created.raise_for_status()
        bundle = created.json()
        pid = bundle["project"]["id"]
        chapters = bundle["chapters"]
        report["project_id"] = pid
        report["chapters"] = len(chapters)
        report["timings_sec"]["create"] = time.perf_counter() - step
        print(f"project {pid} chapters {len(chapters)}", flush=True)

        out_dir = DATA_DIR / "projects" / pid / "generated"
        out_dir.mkdir(parents=True, exist_ok=True)
        client.patch(
            f"/api/projects/{pid}",
            json={
                "image_output_dir": str(out_dir),
                "llm_base_url": "http://127.0.0.1:11434/v1",
                "llm_model": "qwen2.5:32b",
                "allow_fallback": True,
                "fallback_base_url": "http://127.0.0.1:11434/v1",
                "fallback_model": "qwen2.5:32b",
                "thinking": "medium",
            },
        ).raise_for_status()

        step = time.perf_counter()
        print("1) generate-assets…", flush=True)
        gen = client.post(f"/api/projects/{pid}/generate-assets?replace=true")
        if gen.status_code != 200:
            raise RuntimeError(f"assets {gen.status_code}: {gen.text[:1500]}")
        assets = gen.json().get("assets") or []
        report["asset_counts"] = {
            "character": sum(1 for a in assets if a.get("kind") == "character"),
            "scene": sum(1 for a in assets if a.get("kind") == "scene"),
            "prop": sum(1 for a in assets if a.get("kind") == "prop"),
        }
        report["timings_sec"]["generate_assets"] = time.perf_counter() - step
        print(f"assets {report['asset_counts']}", flush=True)

        step = time.perf_counter()
        print("2) generate-images…", flush=True)
        enq = client.post(f"/api/projects/{pid}/generate-images")
        enq.raise_for_status()
        counts = wait_jobs(client, pid, timeout=21600, poll=3)
        report["ref_job_status"] = counts
        report["timings_sec"]["generate_images"] = time.perf_counter() - step
        print(f"ref jobs {counts}", flush=True)
        if counts.get("failed", 0) or counts.get("succeeded", 0) == 0:
            raise RuntimeError(f"reference images failed: {counts}")

        print("waiting LLM after Comfy…", flush=True)
        wait_llm()

        step = time.perf_counter()
        print("3) storyboard all chapters…", flush=True)
        chapter_ok = []
        for ch in sorted(chapters, key=lambda c: c.get("index", 0)):
            title = ch.get("title") or ch["id"]
            print(f"  {title}…", flush=True)
            r = None
            for attempt in range(1, 4):
                r = client.post(f"/api/projects/{pid}/chapters/{ch['id']}/storyboard")
                if r.status_code == 200:
                    break
                print(f"    attempt {attempt} {r.status_code}: {r.text[:200]}", flush=True)
                time.sleep(8 * attempt)
            if r is None or r.status_code != 200:
                raise RuntimeError(f"storyboard {title}: {r.text[:800] if r else 'none'}")
            shots = [s for s in (r.json().get("shots") or []) if s.get("chapter_id") == ch["id"]]
            unready = sum(1 for s in shots if s.get("first_frame_unready"))
            chapter_ok.append({"title": title, "shots": len(shots), "unready": unready})
            print(f"    shots={len(shots)} unready={unready}", flush=True)
        report["chapter_storyboards"] = chapter_ok
        report["timings_sec"]["storyboard_all"] = time.perf_counter() - step

        step = time.perf_counter()
        print("4) generate all first frames…", flush=True)
        ff = client.post(f"/api/projects/{pid}/generate-first-frames")
        if ff.status_code != 200:
            raise RuntimeError(f"first-frames {ff.status_code}: {ff.text[:1500]}")
        body = ff.json()
        report["first_frame_enqueue"] = {
            "queued": body.get("queued"),
            "skipped": body.get("skipped"),
            "errors": body.get("errors") or [],
        }
        print(f"enqueued {body.get('queued')} skipped {body.get('skipped')}", flush=True)
        counts2 = wait_jobs(client, pid, timeout=21600, poll=3)
        report["first_frame_job_status"] = counts2
        report["timings_sec"]["first_frames"] = time.perf_counter() - step
        print(f"first-frame jobs {counts2}", flush=True)

        final = client.get(f"/api/projects/{pid}").json()
        shots = final.get("shots") or []
        with_path = sum(1 for s in shots if (s.get("first_frame_path") or "").strip())
        report["shots"] = len(shots)
        report["first_frames_written"] = with_path
        exported = client.post(f"/api/projects/{pid}/export")
        if exported.status_code == 200:
            report["export_path"] = exported.json().get("path")

        ok = (
            counts.get("failed", 0) == 0
            and counts2.get("failed", 0) == 0
            and with_path == len(shots)
            and len(shots) > 0
            and all(c["unready"] == 0 for c in chapter_ok)
        )
        report["ok"] = ok
        report["timings_sec"]["total"] = time.perf_counter() - t0
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_report(report)
        print(f"{'OK' if ok else 'FAIL'} frames={with_path}/{len(shots)} total_s={report['timings_sec']['total']:.1f}", flush=True)
        return 0 if ok else 1
    except Exception as exc:
        report["errors"].append(str(exc))
        report["ok"] = False
        report["timings_sec"]["total"] = time.perf_counter() - t0
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_report(report)
        print(f"FAIL: {exc}", flush=True)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
