"""Autonomous 青渡川 E2E: create → assets → images → all-chapter storyboards → export.

Mirrors the human UI path under the hard image gate (refs before storyboard).
Shot *first-frame raster* generation is not in novel2Lens yet; this script verifies
per-chapter storyboard scripts + first_frame_unready==0 (refs attached).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

# Reuse helpers / constants from the existing GPU e2e module.
from e2e_qingduchuan_flow import (  # type: ignore
    API,
    COMFY_PYTHON,
    COMFY_ROOT,
    DATA_DIR,
    NOVEL,
    TITLE,
    abs_media,
    assert_t2i_before_edit,
    check_asset_paths,
    delete_prior,
    enqueue_images,
    phase_label,
    preflight_paths,
    require_novel,
    select_assets,
    upload_placeholder_refs,
)

STYLE = "国风3D、东方江湖"
REPORT = Path(__file__).resolve().parent / "qingduchuan_autonomous_report.json"


def write_report(payload: dict) -> None:
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report {REPORT}", flush=True)


def wait_image_jobs(
    client: httpx.Client,
    pid: str,
    *,
    poll_sec: float,
    timeout_sec: float,
    t0: float,
    report: dict,
) -> list[dict]:
    deadline = time.perf_counter() + timeout_sec
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
        except Exception as poll_exc:  # noqa: BLE001
            consecutive_poll_errors += 1
            print(f"poll retry {consecutive_poll_errors}: {poll_exc}", flush=True)
            poll_events.append(
                {"t": round(time.perf_counter() - t0, 1), "error": str(poll_exc), "retries": consecutive_poll_errors}
            )
            if consecutive_poll_errors >= 30:
                report["errors"].append(f"image-jobs poll failed {consecutive_poll_errors} times: {poll_exc}")
                break
            time.sleep(max(2.0, poll_sec))
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
                }
            )
            last_label = label
        time.sleep(max(0.5, poll_sec))
    else:
        report["errors"].append(f"timeout after {timeout_sec}s with jobs still active")
        print("TIMEOUT waiting for image jobs", flush=True)
    report["poll_events"] = poll_events[-40:]
    return client.get(f"/api/projects/{pid}/image-jobs?active_only=false").json().get("jobs") or []


def spot_check_white_bg(assets: list[dict], sample: int = 6) -> list[dict]:
    """Heuristic: flag tiny / missing files; checkerboard detection needs vision — size only here."""
    issues: list[dict] = []
    chars = [a for a in assets if (a.get("kind") or "").lower() in ("character", "人物", "角色")]
    for a in chars[:sample]:
        for field in ("half_path", "full_path"):
            stored = (a.get(field) or "").strip()
            if not stored:
                issues.append({"name": a.get("name"), "field": field, "error": "empty"})
                continue
            path = abs_media(stored)
            if not path.is_file():
                issues.append({"name": a.get("name"), "field": field, "error": "missing", "path": str(path)})
            elif path.stat().st_size < 4096:
                issues.append(
                    {
                        "name": a.get("name"),
                        "field": field,
                        "error": "suspiciously_small",
                        "bytes": path.stat().st_size,
                    }
                )
    return issues


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=API)
    ap.add_argument("--poll-sec", type=float, default=3.0)
    ap.add_argument("--timeout-sec", type=float, default=21600.0)
    ap.add_argument("--max-assets", type=int, default=0)
    args = ap.parse_args()

    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    report: dict = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ok": False,
        "title": TITLE,
        "style": STYLE,
        "base_url": args.base_url,
        "novel": str(NOVEL),
        "timings_sec": timings,
        "errors": [],
        "notes": [
            "Order: assets → reference images → storyboard every chapter (image gate).",
            "novel2Lens does not yet Comfy-render per-shot first-frame rasters; "
            "chapter storyboards + first_frame_unready==0 is the readiness contract.",
        ],
    }

    text = require_novel()
    preflight_paths()
    if not COMFY_ROOT.exists() or not COMFY_PYTHON.exists():
        raise SystemExit("Comfy paths missing")
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
        report["image_output_dir"] = str(out_dir)

        step = time.perf_counter()
        print("1) generate-assets…", flush=True)
        gen = client.post(f"/api/projects/{pid}/generate-assets?replace=true")
        if gen.status_code != 200:
            raise RuntimeError(f"generate-assets {gen.status_code}: {gen.text[:2000]}")
        bundle = gen.json()
        assets = bundle.get("assets") or []
        chapters = bundle.get("chapters") or chapters
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
            raise RuntimeError("zero assets")

        max_n = args.max_assets if args.max_assets and args.max_assets > 0 else None
        target_assets = select_assets(assets, max_n)
        if max_n and len(target_assets) < len(assets):
            rest = [a for a in assets if a["id"] not in {x["id"] for x in target_assets}]
            upload_placeholder_refs(client, pid, rest)
        report["image_asset_ids"] = [a["id"] for a in target_assets]

        step = time.perf_counter()
        print(f"2) generate-images ({len(target_assets)}/{len(assets)})…", flush=True)
        enq = enqueue_images(client, pid, target_assets, assets)
        queued_jobs = enq.get("jobs") or []
        batch_id = enq.get("batch_id") or (enq.get("image_gen") or {}).get("batch_id") or ""
        report["batch_id"] = batch_id
        report["queued"] = len(queued_jobs)
        report["t2i_before_edit"] = assert_t2i_before_edit(queued_jobs)
        print(f"queued {len(queued_jobs)} batch={batch_id}", flush=True)

        first = sorted(chapters, key=lambda c: c.get("index", 0))[0]
        busy = client.post(f"/api/projects/{pid}/chapters/{first['id']}/storyboard")
        report["storyboard_busy_status"] = busy.status_code
        print(f"storyboard-while-busy → {busy.status_code}", flush=True)

        all_jobs = wait_image_jobs(
            client, pid, poll_sec=args.poll_sec, timeout_sec=args.timeout_sec, t0=t0, report=report
        )
        timings["generate_images"] = time.perf_counter() - step
        if batch_id:
            batch_jobs = [j for j in all_jobs if j.get("batch_id") == batch_id]
            if batch_jobs:
                all_jobs = batch_jobs
        status_counts: dict[str, int] = {}
        for j in all_jobs:
            status_counts[j.get("status") or "?"] = status_counts.get(j.get("status") or "?", 0) + 1
        report["job_status_counts"] = status_counts
        print(f"job statuses {status_counts}", flush=True)

        final = client.get(f"/api/projects/{pid}").json()
        assets = final.get("assets") or assets
        check = assets if not max_n else [a for a in assets if a["id"] in set(report["image_asset_ids"])]
        path_issues = check_asset_paths(check)
        report["path_issues"] = path_issues
        report["spot_check"] = spot_check_white_bg(assets)
        if path_issues:
            print(f"path_issues {len(path_issues)}", flush=True)

        # Comfy may still hold VRAM; wait until Ollama can answer before storyboard.
        print("waiting for LLM VRAM after Comfy…", flush=True)
        llm_ready = False
        for _ in range(60):
            try:
                probe = httpx.post(
                    "http://127.0.0.1:11434/v1/chat/completions",
                    json={
                        "model": "qwen2.5:32b",
                        "messages": [{"role": "user", "content": "ok"}],
                        "stream": False,
                    },
                    timeout=120.0,
                )
                if probe.status_code == 200:
                    llm_ready = True
                    break
                print(f"  llm probe {probe.status_code}: {probe.text[:160]}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"  llm probe err: {exc}", flush=True)
            time.sleep(5.0)
        report["llm_ready_before_storyboard"] = llm_ready
        if not llm_ready:
            raise RuntimeError("LLM still OOM after Comfy; cannot storyboard")

        step = time.perf_counter()
        print("3) storyboard every chapter…", flush=True)
        chapter_results: list[dict] = []
        for ch in sorted(chapters, key=lambda c: c.get("index", 0)):
            title = ch.get("title") or ch["id"]
            print(f"  chapter{ch.get('index')} {title}…", flush=True)
            board = None
            for attempt in range(1, 4):
                board = client.post(f"/api/projects/{pid}/chapters/{ch['id']}/storyboard")
                if board.status_code == 200:
                    break
                print(f"    attempt {attempt} → {board.status_code}: {board.text[:240]}", flush=True)
                time.sleep(8.0 * attempt)
            if board is None or board.status_code != 200:
                msg = f"{board.status_code if board else '?'}: {(board.text if board else '')[:1200]}"
                report["errors"].append(f"storyboard {title}: {msg}")
                chapter_results.append({"title": title, "ok": False, "error": msg})
                continue
            bundle = board.json()
            chapters = bundle.get("chapters") or chapters
            ch_shots = [s for s in (bundle.get("shots") or []) if s.get("chapter_id") == ch["id"]]
            unready = sum(1 for s in ch_shots if s.get("first_frame_unready"))
            chapter_results.append(
                {"title": title, "ok": True, "shots": len(ch_shots), "first_frame_unready": unready}
            )
            print(f"    shots={len(ch_shots)} unready={unready}", flush=True)
        timings["storyboard_all"] = time.perf_counter() - step
        report["chapter_storyboards"] = chapter_results

        final = client.get(f"/api/projects/{pid}").json()
        all_shots = final.get("shots") or []
        report["shots"] = len(all_shots)
        report["first_frame_unready_total"] = sum(1 for s in all_shots if s.get("first_frame_unready"))

        print("4) export…", flush=True)
        exported = client.post(f"/api/projects/{pid}/export")
        if exported.status_code == 200:
            report["export_path"] = exported.json().get("path")
            print(f"export {report['export_path']}", flush=True)
        else:
            report["errors"].append(f"export {exported.status_code}")

        succeeded = status_counts.get("succeeded", 0)
        failed = status_counts.get("failed", 0)
        boards_ok = bool(chapter_results) and all(r.get("ok") for r in chapter_results)
        ok = (
            failed == 0
            and succeeded > 0
            and not path_issues
            and report.get("storyboard_busy_status") == 409
            and report.get("t2i_before_edit", False)
            and boards_ok
            and report.get("first_frame_unready_total", 1) == 0
        )
        report["ok"] = ok
        timings["total"] = time.perf_counter() - t0
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_report(report)
        if not ok:
            print(f"FAIL report={REPORT} errors={report['errors']}", flush=True)
            return 1
        print(
            f"OK shots={len(all_shots)} chapters={len(chapter_results)} "
            f"succeeded={succeeded} total_s={timings['total']:.1f}",
            flush=True,
        )
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
