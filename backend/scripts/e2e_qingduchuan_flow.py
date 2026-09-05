"""青渡川 full UI-equivalent flow — REAL LLM + REAL Comfy GPU (no FakeComfy)."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

NOVEL = Path(r"D:\Develop\aiVedioProducer\docs\novels\青渡川.txt")
API = "http://127.0.0.1:8790"
TITLE = "青渡川"
STYLE = "半写实、东方江湖、电影布光、十六比九横构图"
REPORT = Path(__file__).resolve().parent / "qingduchuan_e2e_report.json"
MIN_BYTES = 2048
COMFY_ROOT = Path(r"D:\Develop\ComfyUI")
COMFY_PYTHON = Path(r"D:\Develop\ComfyUI\venv\Scripts\python.exe")
DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def phase_label(job: dict) -> str:
    phase = job.get("phase") or ""
    status = job.get("status") or ""
    if phase in ("loading_t2i", "ensuring_comfy"):
        return "文生图模型加载中"
    if phase == "loading_edit":
        return "图片编辑模型加载中"
    if status == "queued":
        return "排队中"
    if status == "running":
        return "生成中"
    if status == "failed":
        return "失败"
    if status == "succeeded":
        return "成功"
    return status or phase or "?"


def abs_media(stored: str) -> Path:
    p = Path(stored)
    if p.is_absolute():
        return p
    return DATA_DIR / stored


def require_novel() -> str:
    if not NOVEL.is_file():
        raise SystemExit(f"FAIL: novel missing: {NOVEL}")
    return NOVEL.read_text(encoding="utf-8-sig")


def preflight_paths() -> None:
    missing = [str(p) for p in (COMFY_ROOT, COMFY_PYTHON) if not p.exists()]
    if missing:
        raise SystemExit(f"FAIL: Comfy paths missing: {missing}")


def delete_prior(client: httpx.Client) -> None:
    rows = client.get("/api/projects").json()
    for row in rows:
        if row.get("title") == TITLE:
            client.delete(f"/api/projects/{row['id']}").raise_for_status()
            print(f"deleted prior project {row['id']}", flush=True)


def assert_t2i_before_edit(jobs: list[dict]) -> bool:
    """Batch must list all t2i ahead of edit (enqueue_one_click contract)."""
    kinds = [j.get("kind") for j in jobs]
    if "edit" not in kinds or "t2i" not in kinds:
        return True
    first_edit = kinds.index("edit")
    return all(k != "t2i" for k in kinds[first_edit:])


def check_asset_paths(assets: list[dict]) -> list[dict]:
    issues: list[dict] = []
    for a in assets:
        kind = (a.get("kind") or "").lower()
        name = a.get("name") or a.get("id")
        needed: list[tuple[str, str]] = []
        if kind in ("character", "人物", "角色"):
            needed = [("full_path", "full"), ("half_path", "half")]
        elif kind in ("scene", "场景", "地点"):
            needed = [("far_path", "far"), ("near_path", "near")]
        else:
            needed = [("image_path", "image")]
        for field, _slot in needed:
            stored = (a.get(field) or "").strip()
            if not stored:
                issues.append({"name": name, "kind": kind, "field": field, "error": "empty"})
                continue
            path = abs_media(stored)
            if not path.is_file():
                issues.append(
                    {"name": name, "kind": kind, "field": field, "error": "missing_file", "path": str(path)}
                )
                continue
            size = path.stat().st_size
            if size < MIN_BYTES:
                issues.append(
                    {
                        "name": name,
                        "kind": kind,
                        "field": field,
                        "error": "too_small",
                        "path": str(path),
                        "bytes": size,
                    }
                )
    return issues


def select_assets(assets: list[dict], max_assets: int | None) -> list[dict]:
    if max_assets is None or max_assets <= 0 or len(assets) <= max_assets:
        return list(assets)
    order = {"character": 0, "人物": 0, "角色": 0, "scene": 1, "场景": 1, "地点": 1}
    ranked = sorted(
        assets,
        key=lambda a: (order.get((a.get("kind") or "").lower(), 2), a.get("name") or ""),
    )
    return ranked[:max_assets]


def enqueue_images(client: httpx.Client, pid: str, assets: list[dict], all_assets: list[dict]) -> dict:
    if len(assets) == len(all_assets):
        r = client.post(f"/api/projects/{pid}/generate-images")
        r.raise_for_status()
        return r.json()
    # Scoped: per-asset slots (still real GPU; no FakeComfy)
    jobs: list[dict] = []
    batch_id = ""
    for a in assets:
        r = client.post(f"/api/projects/{pid}/assets/{a['id']}/generate-image")
        r.raise_for_status()
        body = r.json()
        for j in body.get("jobs") or []:
            jobs.append(j)
            if not batch_id:
                batch_id = j.get("batch_id") or ""
    return {"batch_id": batch_id, "jobs": jobs, "image_gen": {"queued": len(jobs), "scoped": True}}


def write_report(payload: dict) -> None:
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report {REPORT}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="青渡川 real-GPU E2E (no FakeComfy)")
    ap.add_argument("--base-url", default=API)
    ap.add_argument("--poll-sec", type=float, default=2.0)
    ap.add_argument("--timeout-sec", type=float, default=21600.0)  # 6h
    ap.add_argument(
        "--max-assets",
        type=int,
        default=0,
        help="Limit image generation to N assets (0 = all book assets)",
    )
    args = ap.parse_args()

    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    report: dict = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ok": False,
        "fake_comfy": False,
        "base_url": args.base_url,
        "novel": str(NOVEL),
        "timings_sec": timings,
        "errors": [],
    }

    text = require_novel()
    preflight_paths()
    report["novel_chars"] = len(text)

    client = httpx.Client(base_url=args.base_url, timeout=1200.0)
    try:
        health = client.get("/api/health")
        health.raise_for_status()
        print("health ok", flush=True)

        delete_prior(client)

        step = time.perf_counter()
        created = client.post(
            "/api/projects",
            json={"title": TITLE, "text": text, "style": STYLE},
        )
        created.raise_for_status()
        bundle = created.json()
        pid = bundle["project"]["id"]
        chapters = bundle["chapters"]
        timings["create"] = time.perf_counter() - step
        report["project_id"] = pid
        report["chapters"] = len(chapters)
        print(f"project {pid} chapters {len(chapters)}", flush=True)
        if not chapters:
            raise RuntimeError("no chapters after import")

        out_dir = DATA_DIR / "projects" / pid / "generated"
        out_dir.mkdir(parents=True, exist_ok=True)
        step = time.perf_counter()
        patched = client.patch(
            f"/api/projects/{pid}",
            json={
                "image_output_dir": str(out_dir),
                "llm_base_url": "http://127.0.0.1:8080/v1",
                "llm_model": "qwen3.8-flash-next",
                "allow_fallback": True,
                "fallback_base_url": "http://127.0.0.1:11434/v1",
                "fallback_model": "qwen2.5:32b",
                "thinking": "medium",
            },
        )
        patched.raise_for_status()
        timings["patch"] = time.perf_counter() - step
        report["image_output_dir"] = str(out_dir)

        step = time.perf_counter()
        print("generate-assets (real LLM)…", flush=True)
        gen = client.post(f"/api/projects/{pid}/generate-assets?replace=true")
        if gen.status_code != 200:
            raise RuntimeError(f"generate-assets {gen.status_code}: {gen.text[:2000]}")
        bundle = gen.json()
        assets = bundle.get("assets") or []
        timings["generate_assets"] = time.perf_counter() - step
        counts = {
            "character": sum(1 for a in assets if (a.get("kind") or "").lower() in ("character", "人物", "角色")),
            "scene": sum(1 for a in assets if (a.get("kind") or "").lower() in ("scene", "场景", "地点")),
            "prop": sum(
                1
                for a in assets
                if (a.get("kind") or "").lower()
                not in ("character", "人物", "角色", "scene", "场景", "地点")
            ),
        }
        report["asset_counts"] = counts
        print(f"assets {counts}", flush=True)
        if not assets:
            raise RuntimeError("generate-assets returned zero assets")

        first = sorted(chapters, key=lambda c: c.get("index", 0))[0]
        # refresh chapter ids from latest bundle
        chapters = bundle.get("chapters") or chapters
        first = sorted(chapters, key=lambda c: c.get("index", 0))[0]
        cid = first["id"]
        step = time.perf_counter()
        print(f"storyboard chapter0 {first.get('title')}…", flush=True)
        board = client.post(f"/api/projects/{pid}/chapters/{cid}/storyboard")
        if board.status_code != 200:
            raise RuntimeError(f"storyboard {board.status_code}: {board.text[:2000]}")
        bundle = board.json()
        shots = bundle.get("shots") or []
        timings["storyboard"] = time.perf_counter() - step
        report["shots"] = len(shots)
        print(f"shots {len(shots)}", flush=True)

        assets = bundle.get("assets") or assets
        max_n = args.max_assets if args.max_assets and args.max_assets > 0 else None
        target_assets = select_assets(assets, max_n)
        report["max_assets"] = max_n
        report["image_asset_ids"] = [a["id"] for a in target_assets]
        report["image_asset_names"] = [a.get("name") for a in target_assets]

        step = time.perf_counter()
        print(f"generate-images ({len(target_assets)}/{len(assets)} assets, real GPU)…", flush=True)
        enq = enqueue_images(client, pid, target_assets, assets)
        queued_jobs = enq.get("jobs") or []
        batch_id = enq.get("batch_id") or (enq.get("image_gen") or {}).get("batch_id") or ""
        report["batch_id"] = batch_id
        report["queued"] = len(queued_jobs)
        report["t2i_before_edit"] = assert_t2i_before_edit(queued_jobs)
        if not report["t2i_before_edit"]:
            report["errors"].append("job order not t2i-before-edit")
        print(f"queued {len(queued_jobs)} batch={batch_id} t2i_before_edit={report['t2i_before_edit']}", flush=True)

        # Assert 409 while jobs active
        busy = client.post(f"/api/projects/{pid}/chapters/{cid}/storyboard?overwrite=true")
        report["storyboard_busy_status"] = busy.status_code
        if busy.status_code != 409:
            report["errors"].append(f"expected storyboard 409 while busy, got {busy.status_code}")
            print(f"WARN: expected 409, got {busy.status_code} {busy.text[:200]}", flush=True)
        else:
            print("storyboard overwrite while busy → 409 OK", flush=True)

        deadline = time.perf_counter() + args.timeout_sec
        last_label = ""
        poll_events: list[dict] = []
        consecutive_poll_errors = 0
        while time.perf_counter() < deadline:
            try:
                resp = client.get(f"/api/projects/{pid}/image-jobs?active_only=true")
                if resp.status_code >= 500 or not (resp.text or "").strip():
                    raise RuntimeError(f"empty/bad poll status={resp.status_code} body={resp.text[:120]!r}")
                active = resp.json().get("jobs") or []
                consecutive_poll_errors = 0
            except Exception as poll_exc:  # noqa: BLE001 — API may restart while Comfy loads
                consecutive_poll_errors += 1
                print(f"poll retry {consecutive_poll_errors}: {poll_exc}", flush=True)
                poll_events.append(
                    {
                        "t": round(time.perf_counter() - t0, 1),
                        "error": str(poll_exc),
                        "retries": consecutive_poll_errors,
                    }
                )
                if consecutive_poll_errors >= 30:
                    report["errors"].append(f"image-jobs poll failed {consecutive_poll_errors} times: {poll_exc}")
                    break
                time.sleep(max(2.0, args.poll_sec))
                continue
            if not active:
                break
            labels = sorted({phase_label(j) for j in active})
            label = ",".join(labels)
            if label != last_label:
                print(f"phase [{len(active)} active]: {label}", flush=True)
                poll_events.append(
                    {
                        "t": round(time.perf_counter() - t0, 1),
                        "active": len(active),
                        "labels": labels,
                        "sample": [
                            {
                                "id": j.get("id"),
                                "kind": j.get("kind"),
                                "phase": j.get("phase"),
                                "status": j.get("status"),
                                "label": phase_label(j),
                            }
                            for j in active[:3]
                        ],
                    }
                )
                last_label = label
            time.sleep(max(0.5, args.poll_sec))
        else:
            report["errors"].append(f"timeout after {args.timeout_sec}s with jobs still active")
            print("TIMEOUT waiting for image jobs", flush=True)

        timings["generate_images"] = time.perf_counter() - step
        report["poll_events"] = poll_events[-40:]

        all_jobs = client.get(f"/api/projects/{pid}/image-jobs?active_only=false").json().get("jobs") or []
        # Prefer batch jobs when known
        if batch_id:
            batch_jobs = [j for j in all_jobs if j.get("batch_id") == batch_id]
            if batch_jobs:
                all_jobs = batch_jobs
        # If scoped without batch_id, filter by asset ids
        if max_n:
            ids = set(report["image_asset_ids"])
            all_jobs = [j for j in all_jobs if j.get("asset_id") in ids]

        status_counts: dict[str, int] = {}
        for j in all_jobs:
            status_counts[j.get("status") or "?"] = status_counts.get(j.get("status") or "?", 0) + 1
        report["job_status_counts"] = status_counts
        report["jobs"] = [
            {
                "id": j.get("id"),
                "asset_id": j.get("asset_id"),
                "kind": j.get("kind"),
                "target_field": j.get("target_field"),
                "status": j.get("status"),
                "phase": j.get("phase"),
                "error": j.get("error"),
            }
            for j in all_jobs
        ]
        print(f"job statuses {status_counts}", flush=True)

        final = client.get(f"/api/projects/{pid}").json()
        final_assets = final.get("assets") or []
        if max_n:
            ids = set(report["image_asset_ids"])
            check = [a for a in final_assets if a["id"] in ids]
        else:
            check = final_assets
        path_issues = check_asset_paths(check)
        report["path_issues"] = path_issues
        report["asset_paths"] = [
            {
                "id": a["id"],
                "name": a.get("name"),
                "kind": a.get("kind"),
                "full_path": a.get("full_path"),
                "half_path": a.get("half_path"),
                "far_path": a.get("far_path"),
                "near_path": a.get("near_path"),
                "image_path": a.get("image_path"),
            }
            for a in check
        ]

        succeeded = status_counts.get("succeeded", 0)
        failed = status_counts.get("failed", 0)
        active_left = status_counts.get("queued", 0) + status_counts.get("running", 0)
        ok = (
            failed == 0
            and active_left == 0
            and succeeded > 0
            and not path_issues
            and report.get("storyboard_busy_status") == 409
            and report.get("t2i_before_edit", False)
        )
        report["ok"] = ok
        timings["total"] = time.perf_counter() - t0
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_report(report)

        if not ok:
            print(
                f"FAIL ok={ok} succeeded={succeeded} failed={failed} "
                f"path_issues={len(path_issues)} errors={report['errors']}",
                flush=True,
            )
            return 1
        print(f"OK succeeded={succeeded} assets_checked={len(check)} total_s={timings['total']:.1f}", flush=True)
        return 0
    except Exception as exc:
        report["errors"].append(str(exc))
        report["ok"] = False
        timings["total"] = time.perf_counter() - t0
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_report(report)
        print(f"FAIL: {exc}", flush=True)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
