"""Serial background ImageWorker — one Comfy job at a time."""
from __future__ import annotations

import json
import logging
import threading
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.comfy_pipeline.workflows import (
    GUOFENG_PERIOD_NEGATIVE,
    QUALITY_PARAMS,
    STYLE_DEFAULT_NEGATIVE,
    build_positive,
    ckpt_for_backend,
    compile_ideogram_t2i,
    compile_qwen_edit,
    compile_sdxl_t2i,
    next_seed,
    pick_t2i_backend,
    resolve_size,
)
from app.comfy_supervisor import ComfySupervisor
from app.config import settings
from app.db import Asset, ImageJob, Project
from app.image_gen import abs_media_path, write_asset_image
from app.comfy_pipeline.persona import identity_lock_en, identity_negative
from app.comfy_pipeline.character_prompt import enrich_character_prompt, enrich_character_negative
from app.image_jobs import has_active_jobs, next_queued_job
from app.llm_supervisor import LlmSupervisor
from app.services import refresh_shot_readiness

log = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]


class ImageWorker:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        comfy: ComfySupervisor,
        llm: LlmSupervisor,
        poll_interval: float = 0.4,
        job_timeout: float = 600.0,
        models_dir: Path | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.comfy = comfy
        self.llm = llm
        self.poll_interval = poll_interval
        self.job_timeout = job_timeout
        self.models_dir = models_dir or (Path(settings.comfy_root) / "models")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_kind: str | None = None
        self._running = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="image-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

    def drain_once(self) -> int:
        """Process all currently queued jobs serially (for unit tests)."""
        done = 0
        while True:
            db = self.session_factory()
            try:
                job = next_queued_job(db)
                if not job:
                    return done
                job_id = job.id
            finally:
                db.close()
            self._process_job_id(job_id)
            done += 1

    def _loop(self) -> None:
        while not self._stop.is_set():
            db = self.session_factory()
            try:
                job = next_queued_job(db)
                active = has_active_jobs(db)
                if not job:
                    try:
                        self.comfy.tick_idle(has_active_jobs=active)
                    except Exception:  # noqa: BLE001
                        pass
                    if not active:
                        self.llm.set_image_busy(False)
                    time.sleep(self.poll_interval)
                    continue
                job_id = job.id
            finally:
                db.close()
            self._process_job_id(job_id)

    def _process_job_id(self, job_id: str) -> None:
        db = self.session_factory()
        try:
            job = db.get(ImageJob, job_id)
            if not job or job.status != "queued":
                return
            if job.status == "cancelled":
                return
            self._run_job(db, job)
        except Exception as exc:  # noqa: BLE001
            log.exception("image job %s failed", job_id)
            job = db.get(ImageJob, job_id)
            if job and job.status == "running":
                job.status = "failed"
                job.phase = ""
                job.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-500:]}"
                db.commit()
        finally:
            db.close()

    def _save(self, db: Session, job: ImageJob) -> bool:
        """Persist job progress. Returns False if DB already cancelled (no overwrite)."""
        from datetime import datetime, timezone

        check = self.session_factory()
        try:
            fresh = check.get(ImageJob, job.id)
            if fresh is not None and fresh.status == "cancelled":
                db.rollback()
                db.refresh(job)
                return False
        finally:
            check.close()

        job.updated_at = datetime.now(timezone.utc)
        db.commit()
        return True

    def _client(self) -> Any:
        return self.comfy._client()

    def _run_job(self, db: Session, job: ImageJob) -> None:
        self._running = True
        try:
            self.llm.set_image_busy(True)
            # stop_llm already settles; re-check port before touching Comfy VRAM.
            try:
                self.llm.wait_released()
            except TimeoutError as exc:
                raise RuntimeError(f"cannot start Comfy while LLM still up: {exc}") from exc
            # Extra beat after Ollama unload so CUDA pages can reclaim before Comfy.
            time.sleep(min(5.0, max(0.0, float(getattr(self.llm, "settle_seconds", 5.0) or 0))))
            job.status = "running"
            job.error = ""
            job.phase = "ensuring_comfy"
            if not self._save(db, job):
                return

            self.comfy.ensure_running()
            client = self._client()
            payload = json.loads(job.payload_json or "{}")

            if job.kind == "t2i":
                if self._last_kind == "edit":
                    self.comfy.free_models()
                job.phase = "loading_t2i"
                if not self._save(db, job):
                    return
                job.phase = "generating"
                if not self._save(db, job):
                    return
                png = self._run_t2i(client, job.prompt, payload)
            else:
                if self._last_kind == "t2i":
                    self.comfy.free_models()
                job.phase = "loading_edit"
                if not self._save(db, job):
                    return
                job.phase = "generating"
                if not self._save(db, job):
                    return
                png = self._run_edit(db, client, job, payload)

            # Abort before write/succeed if cancelled while generating
            check = self.session_factory()
            try:
                fresh = check.get(ImageJob, job.id)
                if fresh is not None and fresh.status == "cancelled":
                    db.rollback()
                    db.refresh(job)
                    return
            finally:
                check.close()

            project = db.get(Project, job.project_id)
            if not project:
                raise RuntimeError("project missing")
            payload_shot_id = (payload.get("shot_id") or getattr(job, "shot_id", "") or "").strip()
            if job.target_field == "first_frame" or payload_shot_id:
                from app.db import Shot
                from app.image_gen import write_shot_first_frame

                shot = db.get(Shot, payload_shot_id or job.asset_id)
                if not shot or shot.project_id != project.id:
                    raise RuntimeError("shot missing for first_frame")
                write_shot_first_frame(project, shot, png)
                db.commit()
            else:
                asset = db.get(Asset, job.asset_id)
                if not asset:
                    raise RuntimeError("project or asset missing")
                write_asset_image(project, asset, job.target_field, png)
                refresh_shot_readiness(db, project)
            job.status = "succeeded"
            job.phase = ""
            job.error = ""
            if not self._save(db, job):
                return
            self._last_kind = job.kind
            self.comfy.note_activity()
        finally:
            self._running = False
            # Clear busy only when no more active work
            check = self.session_factory()
            try:
                if not has_active_jobs(check):
                    self.llm.set_image_busy(False)
            finally:
                check.close()

    def _run_t2i(self, client: Any, prompt: str, payload: dict[str, Any]) -> bytes:
        style = payload.get("style") or "realistic"
        quality = payload.get("quality") or "standard"
        aspect = payload.get("aspect") or "1:1"
        subject_type = payload.get("subject_type") or "scenery"
        gender = payload.get("gender") or "unknown"
        age_tier = payload.get("age_tier") or "unknown"
        prefer_backend = (payload.get("prefer_backend") or "").strip()
        qp = QUALITY_PARAMS.get(quality, QUALITY_PARAMS["standard"])
        live_ckpts = set(client.list_checkpoints() or [])

        t2i_prompt = prompt
        if subject_type == "character":
            en_lock = identity_lock_en(gender=gender, age_tier=age_tier)
            if en_lock:
                t2i_prompt = f"{en_lock}. {t2i_prompt}"
            # Costume color hard-prefix — Guofeng otherwise defaults to white/gold armor beauty.
            if "黑色" in prompt or "黑衣" in prompt:
                t2i_prompt = (
                    "all-black outfit only, solid black robes, black cloth, masked face, "
                    "no white clothes, no gold fantasy armor, no glamorous armor. "
                    + t2i_prompt
                )
            elif "官服" in prompt:
                t2i_prompt = (
                    "ancient Chinese magistrate official robes, formal guanfu, "
                    "middle-aged male official, not fantasy armor. "
                    + t2i_prompt
                )
            # Keep guofeng_cg for 国风3D males/elders; gender-specific CGI suffixes handle bias.
            style_for_suffix = style
            t2i_prompt = enrich_character_prompt(
                t2i_prompt,
                style_for_suffix,
                no_background=bool(payload.get("no_background")),
                gender=gender,
                age_tier=age_tier,
            )
        else:
            style_for_suffix = style
            if subject_type == "prop":
                # English object anchors first — Guofeng often ignores bare Chinese prop names.
                prop_en = {
                    "玉佩": "Chinese carved jade pendant bi disc, nephrite jade ornament",
                    "文献": "bound ancient Chinese rice-paper documents scroll stack",
                    "木盒": "carved rosewood wooden box",
                    "火折子": "ancient Chinese fire starter tube flint lighter",
                    "千年古松": "miniature ancient pine tree bonsai",
                    "密道": "narrow wooden secret tunnel doorway entrance",
                }
                for zh, en in prop_en.items():
                    if zh in prompt:
                        t2i_prompt = f"{en}. {prompt}"
                        break
                else:
                    t2i_prompt = prompt
            else:
                t2i_prompt = prompt

        try:
            backend = pick_t2i_backend(
                style,
                quality,
                self.models_dir,
                t2i_prompt,
                subject_type=subject_type if subject_type != "prop" else "scenery",
                available_ckpts=live_ckpts or None,
            )
        except ValueError:
            backend = "sdxl_realvis"

        # prefer_backend: Guofeng for all asset T2I; RealVis only when explicitly forced.
        if prefer_backend == "sdxl_guofeng" and (
            "Guofeng4.2XL.safetensors" in (live_ckpts or set())
            or (self.models_dir / "checkpoints" / "Guofeng4.2XL.safetensors").exists()
        ):
            backend = "sdxl_guofeng"
        elif prefer_backend == "sdxl_realvis" and (
            "RealVisXL_V5.0_fp16.safetensors" in (live_ckpts or set())
            or (self.models_dir / "checkpoints" / "RealVisXL_V5.0_fp16.safetensors").exists()
        ):
            backend = "sdxl_realvis"

        if subject_type == "character":
            positive = build_positive(
                t2i_prompt,
                style_for_suffix,
                gender=gender,
                age_tier=age_tier,
            )
            negative = enrich_character_negative(
                t2i_prompt,
                STYLE_DEFAULT_NEGATIVE,
                style=style_for_suffix,
                no_background=bool(payload.get("no_background")),
                gender=gender,
                age_tier=age_tier,
            )
            extra_neg = identity_negative(gender=gender, age_tier=age_tier)
            if extra_neg:
                negative = f"{negative}, {extra_neg}"
            if style_for_suffix in ("guofeng_cg", "guofeng"):
                negative = f"{negative}, {GUOFENG_PERIOD_NEGATIVE}"
            # Hard clothing color locks for assassin / official looks that Guofeng loves to overwrite.
            blob = f"{prompt} {t2i_prompt}".lower()
            if any(x in prompt for x in ("黑色", "黑衣", "官服", "短打")):
                negative = (
                    f"{negative}, white fantasy armor, gold filigree armor, "
                    "beautiful young woman, 1girl, exposed thighs, glamorous goddess armor"
                )
        else:
            positive = build_positive(prompt, style)
            negative = STYLE_DEFAULT_NEGATIVE
            if subject_type == "scenery":
                negative = f"{negative}, people, person, human, face, crowd"
            if subject_type == "prop":
                negative = (
                    f"{negative}, people, person, human, hands, face, fingers, "
                    "building exterior, courtyard, room interior, landscape, scenery, wide shot, "
                    "spotlight, tripod, studio softbox, lamp, photography equipment"
                )
                positive = (
                    f"single prop product shot, centered object, plain studio background, "
                    f"{t2i_prompt}"
                )

        if backend == "ideogram4":
            width, height = resolve_size(aspect, "ideogram4")
            wf = compile_ideogram_t2i(
                prompt=positive,
                negative=negative,
                width=width,
                height=height,
                seed=next_seed(None, 0, False),
                steps=int(qp["ideogram_steps"]),
                cfg=float(qp["cfg"]),
                style=style,
            )
        else:
            width, height = resolve_size(aspect, "sdxl")
            if subject_type == "character" and aspect == "9:16":
                width, height = resolve_size("9:16_fullbody", "sdxl")
            ckpt = ckpt_for_backend(backend) or "RealVisXL_V5.0_fp16.safetensors"
            wf = compile_sdxl_t2i(
                ckpt=ckpt,
                prompt=positive,
                negative=negative,
                width=width,
                height=height,
                seed=next_seed(None, 0, False),
                steps=int(qp["steps"]),
                cfg=float(qp["cfg"]),
            )

        pid = client.queue_prompt(wf)
        hist = client.wait_history(pid, timeout_seconds=self.job_timeout)
        images = client.collect_images(hist)
        if not images:
            raise RuntimeError("Comfy returned no images")
        return images[0]

    def _run_edit(self, db: Session, client: Any, job: ImageJob, payload: dict[str, Any]) -> bytes:
        from app.comfy_pipeline.qa import assess_image_bytes

        ref_paths = list(payload.get("ref_paths") or [])
        ref_labels = list(payload.get("ref_labels") or [])
        ref_field = (payload.get("ref_field") or "").strip()
        if not ref_paths and ref_field:
            asset = db.get(Asset, job.asset_id)
            if not asset:
                raise RuntimeError("asset missing for edit ref")
            stored = ""
            if ref_field == "full":
                stored = asset.full_path or ""
            elif ref_field == "half":
                stored = asset.half_path or ""
            elif ref_field == "far":
                stored = getattr(asset, "far_path", "") or asset.image_path or ""
            elif ref_field == "near":
                stored = getattr(asset, "near_path", "") or ""
            elif ref_field == "image":
                stored = asset.image_path or ""
            if not stored:
                raise RuntimeError(f"缺少参考图字段 {ref_field}")
            abs_path = abs_media_path(stored)
            if not abs_path.is_file():
                raise RuntimeError(f"参考图不存在: {stored}")
            ref_paths = [str(abs_path)]
            if not ref_labels:
                ref_labels = [
                    {
                        "full": "character full-body reference",
                        "far": "scene wide plate",
                        "half": "character half-body",
                        "near": "scene near plate",
                        "image": "prop reference",
                    }.get(ref_field, f"reference {ref_field}")
                ]

        if not ref_paths:
            raise RuntimeError("edit job has no reference images")

        names: list[str] = []
        for i, p in enumerate(ref_paths[:3]):
            path = Path(p)
            data = path.read_bytes()
            names.append(client.upload_image(data, path.name or f"ref_{i}.png"))

        aspect = payload.get("aspect") or "3:4"
        width, height = resolve_size(aspect, "sdxl")
        edit_prompt = (job.prompt or "").strip()
        edit_negative = ""
        if (job.target_field or "") in ("half",) or "半身" in edit_prompt:
            if "纯白" not in edit_prompt:
                edit_prompt = (
                    f"{edit_prompt}。纯白色不透明实底背景，不要透明，不要棋盘格，不要灰白方格。"
                )
            edit_negative = (
                "checkerboard, checkered background, transparency grid, alpha checker, "
                "transparent background, png transparency pattern, grey and white squares"
            )

        labeled = []
        for i in range(len(names)):
            label = (ref_labels[i] if i < len(ref_labels) else f"参考图{i + 1}").strip()
            labeled.append(f"image {i + 1} ({label})")
        if (job.target_field or "") == "half":
            wrapped = (
                f"Using {labeled[0]}, create one new image that is ONLY a tighter bust-crop reframe "
                f"of that same person: {edit_prompt}. "
                "Do not invent a new character; keep the exact face, hair, and outfit from the reference. "
                f"Output image aspect ratio {aspect}, resolution {width}x{height}."
            )
        elif (job.target_field or "") == "first_frame" and len(names) >= 2:
            wrapped = (
                f"Using {', '.join(labeled)}, create one new image: {edit_prompt}. "
                "CRITICAL: each labeled person reference is a DIFFERENT identity. "
                "Do not clone one face onto both people. Keep each person's age, hair color, "
                "beard/no-beard, and clothing distinct as in their own reference image. "
                f"Output image aspect ratio {aspect}, resolution {width}x{height}."
            )
        else:
            wrapped = (
                f"Using {', '.join(labeled)}, create one new image: {edit_prompt}. "
                "Preserve identity and key details from the references as instructed. "
                f"Output image aspect ratio {aspect}, resolution {width}x{height}."
            )

        last_err = ""
        last_png: bytes | None = None
        # Multi-character first frames: skip Lightning — 4-step often collapses faces.
        attempts = 2
        start_attempt = 0
        if (job.target_field or "") == "first_frame" and len(names) >= 2:
            start_attempt = 1
            attempts = 2
        for attempt in range(start_attempt, start_attempt + attempts):
            use_lightning = attempt < 1
            steps = 4 if use_lightning else 28
            cfg = 1.0 if use_lightning else 3.5
            wf = compile_qwen_edit(
                prompt=wrapped,
                negative=edit_negative or (payload.get("negative") or ""),
                ref_names=names,
                seed=next_seed(None, attempt, True),
                steps=steps,
                cfg=cfg,
                use_lightning=use_lightning,
                width=width,
                height=height,
            )
            pid = client.queue_prompt(wf)
            hist = client.wait_history(pid, timeout_seconds=self.job_timeout)
            images = client.collect_images(hist)
            if not images:
                last_err = "Comfy edit returned no images"
                continue
            last_png = images[0]
            qa = assess_image_bytes(
                last_png,
                require_fullbody=bool(payload.get("require_fullbody")),
            )
            if qa.get("ok") or qa.get("passed"):
                return last_png
            last_err = f"qa_failed:{','.join(qa.get('reasons') or [])}"
        if last_png is not None:
            return last_png
        raise RuntimeError(last_err or "Comfy edit failed")
