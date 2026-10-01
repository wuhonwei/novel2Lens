# -*- coding: utf-8 -*-
"""青渡川V12 — 国风3D 全链路自主测试（对齐页面按钮）。

流程：创建项目 → 一键全书资产 → 一键参考图 → 一键全部章节分镜 → 一键全部首帧

用法：
  python scripts/e2e_qingduchuan_v12.py              # 新建并跑全流程
  python scripts/e2e_qingduchuan_v12.py <project_id> # 续跑已有项目
  python scripts/e2e_qingduchuan_v12.py --from STEP  # 从某步强制重做（create|assets|images|storyboard|first_frames）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import httpx

NOVEL = Path(r"D:\Develop\aiVedioProducer\docs\novels\青渡川.txt")
API = "http://127.0.0.1:8790"
TITLE = "青渡川V12"
STYLE = "国风3D"
REPORT = Path(__file__).resolve().parent / "qingduchuan_v12_report.json"
STATE = Path(__file__).resolve().parent / "qingduchuan_v12_state.json"
LOG = Path(__file__).resolve().parent / "qingduchuan_v12_run.log"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"

STEPS = ("create", "assets", "images", "storyboard", "first_frames")


def log(msg: str) -> None:
    line = f"{datetime.now().strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def write_report(payload: dict) -> None:
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"report {REPORT}")


def save_state(pid: str, done: list[str], extra: dict | None = None) -> None:
    payload = {
        "project_id": pid,
        "title": TITLE,
        "done": done,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **(extra or {}),
    }
    STATE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state() -> dict:
    if not STATE.is_file():
        return {}
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def wait_jobs(client: httpx.Client, pid: str, timeout: float, poll: float) -> dict[str, int]:
    deadline = time.perf_counter() + timeout
    last = ""
    while time.perf_counter() < deadline:
        try:
            active = client.get(f"/api/projects/{pid}/image-jobs?active_only=true").json().get("jobs") or []
        except Exception as exc:  # noqa: BLE001
            log(f"poll jobs retry: {exc}")
            time.sleep(max(poll, 5))
            continue
        if not active:
            break
        label = f"{len(active)}:{sorted({(j.get('phase') or j.get('status') or '?') for j in active})}"
        if label != last:
            log(f"phase {label}")
            last = label
        time.sleep(poll)
    else:
        raise RuntimeError("timeout waiting image jobs")
    all_jobs: list[dict] = []
    for attempt in range(1, 6):
        try:
            all_jobs = client.get(f"/api/projects/{pid}/image-jobs?active_only=false").json().get("jobs") or []
            break
        except Exception as exc:  # noqa: BLE001
            log(f"list jobs retry {attempt}: {exc}")
            time.sleep(3 * attempt)
    counts: dict[str, int] = {}
    for j in all_jobs:
        counts[j.get("status") or "?"] = counts.get(j.get("status") or "?", 0) + 1
    failed = [j for j in all_jobs if j.get("status") == "failed"]
    if failed:
        sample = [
            f"{j.get('target_field')}:{(j.get('error') or '')[:120]}"
            for j in failed[:8]
        ]
        log(f"failed jobs sample: {sample}")
    return counts


def wait_llm(model: str = "qwen2.5:32b") -> None:
    for i in range(40):
        try:
            r = httpx.post(
                "http://127.0.0.1:11434/v1/chat/completions",
                json={"model": model, "messages": [{"role": "user", "content": "ok"}], "stream": False},
                timeout=180.0,
                trust_env=False,
            )
            if r.status_code == 200:
                log(f"llm ready ({model})")
                return
            log(f"llm {i}: {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            log(f"llm {i}: {exc}")
        time.sleep(5)
    raise RuntimeError("llm not ready")


def classify_error(exc: BaseException) -> str:
    msg = str(exc).lower()
    if any(k in msg for k in ("timeout", "timed out", "connection", "reset", "temporarily", "503", "502", "busy")):
        return "retry"
    if any(k in msg for k in ("syntaxerror", "traceback", "typeerror", "attributeerror", "keyerror", "import")):
        return "code"
    if "unboundlocal" in msg or "not defined" in msg:
        return "code"
    return "retry_or_code"


def assets_have_images(assets: list[dict]) -> bool:
    if not assets:
        return False
    for a in assets:
        kind = a.get("kind")
        if kind == "character" and not (a.get("full_path") and a.get("half_path")):
            return False
        if kind == "scene" and not (a.get("far_path") or a.get("near_path") or a.get("image_path")):
            return False
        if kind == "prop" and not a.get("image_path"):
            return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_id", nargs="?", default="")
    ap.add_argument("--from", dest="from_step", default="", choices=("", *STEPS))
    ap.add_argument("--base-url", default=API)
    args = ap.parse_args()

    if not LOG.exists():
        LOG.write_text("", encoding="utf-8")
    elif not args.project_id and not args.from_step:
        # fresh run — rotate log
        LOG.write_text("", encoding="utf-8")

    report: dict = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ok": False,
        "title": TITLE,
        "style": STYLE,
        "errors": [],
        "timings_sec": {},
        "steps": [],
        "retries": [],
    }
    t0 = time.perf_counter()
    if not NOVEL.is_file():
        raise SystemExit(f"novel missing: {NOVEL}")
    text = NOVEL.read_text(encoding="utf-8-sig")
    client = httpx.Client(
        base_url=args.base_url,
        timeout=httpx.Timeout(21600.0, connect=30.0),
        trust_env=False,
    )
    done: list[str] = []
    try:
        client.get("/api/health").raise_for_status()
        log(f"health ok | novel_chars={len(text)}")

        st = load_state()
        resume_id = (args.project_id or "").strip()
        force_from = args.from_step or ""
        done = []
        if resume_id:
            done = list(st.get("done") or []) if st.get("project_id") == resume_id else []
            if force_from and force_from in STEPS:
                idx = STEPS.index(force_from)
                done = [s for s in done if s in STEPS[:idx]]
                log(f"force from {force_from}; kept done={done}")
            else:
                log(f"resume {resume_id} done={done}")
        elif st.get("title") == TITLE and st.get("project_id") and st.get("ok") is not True:
            # Auto-resume incomplete prior V12 run when no id passed
            resume_id = str(st.get("project_id") or "")
            done = list(st.get("done") or [])
            log(f"auto-resume incomplete {resume_id} done={done}")

        pid = ""
        chapters: list = []
        assets: list = []

        # —— create ——
        if resume_id:
            log(f"续跑项目 {resume_id}")
            bundle = client.get(f"/api/projects/{resume_id}").json()
            pid = bundle["project"]["id"]
            chapters = bundle.get("chapters") or []
            assets = bundle.get("assets") or []
            report["project_id"] = pid
            report["chapters"] = len(chapters)
            if "create" not in done:
                done.append("create")
            save_state(pid, done)
        else:
            for row in client.get("/api/projects").json():
                if row.get("title") == TITLE:
                    client.delete(f"/api/projects/{row['id']}").raise_for_status()
                    log(f"deleted prior {row['id']}")

            step = time.perf_counter()
            log(f"UI: 创建项目 {TITLE} / {STYLE}")
            created = client.post("/api/projects", json={"title": TITLE, "text": text, "style": STYLE})
            created.raise_for_status()
            bundle = created.json()
            pid = bundle["project"]["id"]
            chapters = bundle["chapters"]
            report["project_id"] = pid
            report["chapters"] = len(chapters)
            report["timings_sec"]["create"] = time.perf_counter() - step
            report["steps"].append("create")
            done = ["create"]
            save_state(pid, done)
            log(f"project {pid} chapters {len(chapters)}")

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

        assert pid, "no project id"

        # —— assets ——
        if "assets" not in done or force_from == "assets":
            step = time.perf_counter()
            log("UI: 一键生成全书资产")
            wait_llm()
            last_err = ""
            for attempt in range(1, 4):
                gen = client.post(f"/api/projects/{pid}/generate-assets?replace=true")
                if gen.status_code == 200:
                    assets = gen.json().get("assets") or []
                    break
                last_err = f"assets {gen.status_code}: {gen.text[:1500]}"
                log(f"assets attempt {attempt}: {last_err}")
                time.sleep(8 * attempt)
                wait_llm()
            else:
                raise RuntimeError(last_err or "generate-assets failed")
            report["asset_counts"] = {
                "character": sum(1 for a in assets if a.get("kind") == "character"),
                "scene": sum(1 for a in assets if a.get("kind") == "scene"),
                "prop": sum(1 for a in assets if a.get("kind") == "prop"),
                "char_variants": sum(
                    1 for a in assets if a.get("kind") == "character" and (a.get("parent_id") or "")
                ),
            }
            report["timings_sec"]["generate_assets"] = time.perf_counter() - step
            report["steps"].append("generate_assets")
            if "assets" not in done:
                done.append("assets")
            save_state(pid, done, {"asset_counts": report["asset_counts"]})
            log(f"assets {report['asset_counts']}")
        else:
            assets = client.get(f"/api/projects/{pid}").json().get("assets") or assets
            log(f"skip assets (done); n={len(assets)}")

        if not assets:
            assets = client.get(f"/api/projects/{pid}").json().get("assets") or []
        report["asset_counts"] = report.get("asset_counts") or {
            "character": sum(1 for a in assets if a.get("kind") == "character"),
            "scene": sum(1 for a in assets if a.get("kind") == "scene"),
            "prop": sum(1 for a in assets if a.get("kind") == "prop"),
        }

        # —— images ——
        if "images" not in done or force_from == "images":
            cur = client.get(f"/api/projects/{pid}").json().get("assets") or []
            if assets_have_images(cur) and force_from != "images":
                log("参考图已齐，跳过生成")
                report["steps"].append("generate_images_skipped")
            else:
                step = time.perf_counter()
                log("UI: 一键生成参考图")
                active = client.get(f"/api/projects/{pid}/image-jobs?active_only=true").json().get("jobs") or []
                if not active:
                    enq = client.post(f"/api/projects/{pid}/generate-images")
                    enq.raise_for_status()
                    log(f"enqueued images: {enq.json()}")
                counts = wait_jobs(client, pid, timeout=21600, poll=5)
                report["ref_job_status"] = counts
                report["timings_sec"]["generate_images"] = time.perf_counter() - step
                report["steps"].append("generate_images")
                log(f"ref jobs {counts}")
                done_n = counts.get("done", 0) + counts.get("succeeded", 0)
                if counts.get("failed", 0) and done_n == 0:
                    raise RuntimeError(f"reference images failed: {counts}")
                cur = client.get(f"/api/projects/{pid}").json().get("assets") or []
                if not assets_have_images(cur):
                    # Retry only missing slots once via generate-images again
                    log("参考图未齐，重试入队缺失槽位…")
                    enq2 = client.post(f"/api/projects/{pid}/generate-images")
                    if enq2.status_code == 200:
                        counts = wait_jobs(client, pid, timeout=21600, poll=5)
                        report["ref_job_status_retry"] = counts
                    cur = client.get(f"/api/projects/{pid}").json().get("assets") or []
                    if not assets_have_images(cur):
                        missing = []
                        for a in cur:
                            kind = a.get("kind")
                            if kind == "character" and not (a.get("full_path") and a.get("half_path")):
                                missing.append(f"char:{a.get('name')}")
                            if kind == "scene" and not (a.get("far_path") or a.get("near_path")):
                                missing.append(f"scene:{a.get('name')}")
                            if kind == "prop" and not a.get("image_path"):
                                missing.append(f"prop:{a.get('name')}")
                        raise RuntimeError(f"reference images incomplete: {missing[:20]}")
            if "images" not in done:
                done.append("images")
            save_state(pid, done)
        else:
            log("skip images (done)")

        log("waiting LLM after Comfy…")
        wait_llm()

        # —— storyboard ——
        if "storyboard" not in done or force_from == "storyboard":
            existing_shots = client.get(f"/api/projects/{pid}").json().get("shots") or []
            chapters = client.get(f"/api/projects/{pid}").json().get("chapters") or chapters
            covered = all(any(s.get("chapter_id") == ch["id"] for s in existing_shots) for ch in chapters)
            if existing_shots and covered and force_from != "storyboard":
                log("全章分镜已存在，跳过")
                report["storyboard_all"] = {
                    "generated": [],
                    "skipped": [c["id"] for c in chapters],
                    "errors": [],
                }
                report["shots_after_storyboard"] = len(existing_shots)
                report["steps"].append("storyboard_all_skipped")
            else:
                step = time.perf_counter()
                log("UI: 按章生成分镜（缺口章）")
                generated: list[str] = []
                skipped: list[str] = []
                errors: list[str] = []
                # Only overwrite when explicitly forced and every chapter already has shots.
                # Gap-fill resumes must keep existing chapter boards.
                for ch in sorted(chapters, key=lambda x: int(x.get("index") or 0)):
                    cid = ch["id"]
                    has = any(s.get("chapter_id") == cid for s in existing_shots)
                    if has and force_from != "storyboard":
                        skipped.append(cid)
                        log(f"skip chapter#{ch.get('index')} {ch.get('title')} (has shots)")
                        continue
                    if has and force_from == "storyboard":
                        # Forced resume: still skip chapters that already have shots to save time
                        skipped.append(cid)
                        log(f"keep chapter#{ch.get('index')} {ch.get('title')} (already storyboarded)")
                        continue
                    wait_llm()
                    ok = False
                    last_body = ""
                    for attempt in range(1, 4):
                        log(f"storyboard chapter#{ch.get('index')} {ch.get('title')} attempt {attempt}")
                        board = client.post(
                            f"/api/projects/{pid}/chapters/{cid}/storyboard",
                            timeout=httpx.Timeout(10800.0, connect=30.0),
                        )
                        last_body = board.text[:800]
                        if board.status_code == 200:
                            body = board.json()
                            n = len(body.get("shots") or [])
                            log(f"  ok shots={n}")
                            generated.append(cid)
                            ok = True
                            break
                        log(f"  fail {board.status_code}: {last_body[:300]}")
                        report["retries"].append(
                            {"step": "storyboard", "chapter": cid, "attempt": attempt, "body": last_body[:400]}
                        )
                        time.sleep(10 * attempt)
                        wait_llm()
                    if not ok:
                        errors.append(f"{ch.get('title')}: {last_body}")
                    existing_shots = client.get(f"/api/projects/{pid}").json().get("shots") or []
                shots = existing_shots
                report["storyboard_all"] = {
                    "generated": generated,
                    "skipped": skipped,
                    "errors": errors,
                    "cancelled": False,
                }
                report["shots_after_storyboard"] = len(shots)
                report["timings_sec"]["storyboard_all"] = time.perf_counter() - step
                report["steps"].append("storyboard_all")
                log(
                    f"storyboard generated={len(generated)} skipped={len(skipped)} "
                    f"errors={errors[:3]} shots={len(shots)}"
                )
                uncovered = [
                    ch
                    for ch in chapters
                    if not any(s.get("chapter_id") == ch["id"] for s in shots)
                ]
                if errors and uncovered:
                    raise RuntimeError(
                        f"storyboard incomplete: errors={errors} "
                        f"uncovered={[c.get('title') for c in uncovered]}"
                    )
                if errors and not generated and not skipped:
                    raise RuntimeError(f"storyboard failed: {errors}")
            if "storyboard" not in done:
                done.append("storyboard")
            save_state(pid, done)
        else:
            log("skip storyboard (done)")

        # —— first frames ——
        if "first_frames" not in done or force_from == "first_frames":
            final0 = client.get(f"/api/projects/{pid}").json()
            shots = final0.get("shots") or []
            with_path0 = sum(1 for s in shots if (s.get("first_frame_path") or "").strip())
            if shots and with_path0 == len(shots) and force_from != "first_frames":
                log("全部首帧已齐，跳过")
                report["steps"].append("first_frames_skipped")
            else:
                step = time.perf_counter()
                log("UI: 一键生成全部首帧")
                active = client.get(f"/api/projects/{pid}/image-jobs?active_only=true").json().get("jobs") or []
                if not active:
                    ff = client.post(
                        f"/api/projects/{pid}/generate-first-frames?overwrite={str(force_from == 'first_frames').lower()}"
                    )
                    if ff.status_code != 200:
                        raise RuntimeError(f"first-frames {ff.status_code}: {ff.text[:1500]}")
                    ff_body = ff.json()
                    report["first_frame_enqueue"] = {
                        "queued": ff_body.get("queued"),
                        "skipped": ff_body.get("skipped"),
                        "errors": (ff_body.get("errors") or [])[:20],
                    }
                    log(
                        f"enqueued {ff_body.get('queued')} skipped {ff_body.get('skipped')} "
                        f"errors={len(ff_body.get('errors') or [])}"
                    )
                counts2 = wait_jobs(client, pid, timeout=43200, poll=5)
                report["first_frame_job_status"] = counts2
                report["timings_sec"]["first_frames"] = time.perf_counter() - step
                report["steps"].append("first_frames")
                log(f"first-frame jobs {counts2}")
                # Retry any still-missing shots once (dual-char QA / transient Comfy failures).
                final0 = client.get(f"/api/projects/{pid}").json()
                shots = final0.get("shots") or []
                missing = [s for s in shots if not (s.get("first_frame_path") or "").strip()]
                if missing:
                    log(f"首帧缺口 {len(missing)}，逐镜重试…")
                    for s in missing:
                        rr = client.post(f"/api/projects/{pid}/shots/{s['id']}/generate-first-frame")
                        log(f"  retry {s.get('order_index')} {rr.status_code}")
                    counts3 = wait_jobs(client, pid, timeout=21600, poll=5)
                    report["first_frame_job_status_retry"] = counts3
                    report["steps"].append("first_frames_retry")
                    log(f"first-frame retry jobs {counts3}")
            if "first_frames" not in done:
                done.append("first_frames")
            save_state(pid, done)
        else:
            log("skip first_frames (done)")

        final = client.get(f"/api/projects/{pid}").json()
        shots = final.get("shots") or []
        with_path = sum(1 for s in shots if (s.get("first_frame_path") or "").strip())
        assets = final.get("assets") or []
        report["shots"] = len(shots)
        report["first_frames_written"] = with_path
        report["assets_ready"] = assets_have_images(assets)
        report["ok"] = bool(with_path == len(shots) and len(shots) > 0 and report["assets_ready"])
        if with_path < len(shots):
            raise RuntimeError(f"first frames incomplete: {with_path}/{len(shots)}")
        report["timings_sec"]["total"] = time.perf_counter() - t0
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["done"] = done
        write_report(report)
        save_state(pid, done, {"ok": report["ok"]})
        log(
            f"{'OK' if report['ok'] else 'FAIL'} frames={with_path}/{len(shots)} "
            f"total_s={report['timings_sec']['total']:.1f}"
        )
        return 0 if report["ok"] else 1
    except Exception as exc:
        kind = classify_error(exc)
        report["errors"].append(str(exc))
        report["error_class"] = kind
        report["traceback"] = traceback.format_exc()[-3000:]
        report["ok"] = False
        report["timings_sec"]["total"] = time.perf_counter() - t0
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["done"] = done
        if pid:
            save_state(pid, done, {"last_error": str(exc), "error_class": kind})
        write_report(report)
        log(f"FAIL ({kind}): {exc}")
        if kind == "code":
            log("HINT: code fix needed — after patch, resume with: "
                f"python scripts/e2e_qingduchuan_v12.py {pid or ''} ")
        else:
            log("HINT: likely transient — retry/resume with same project id")
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
