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
            asset = db.get(Asset, job.asset_id)
            if not project or not asset:
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

        # prefer_backend only when explicitly set (no longer auto-forced for males)
        if prefer_backend == "sdxl_realvis" and (
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
        else:
            positive = build_positive(prompt, style)
            negative = STYLE_DEFAULT_NEGATIVE
            if subject_type == "scenery":
                negative = f"{negative}, people, person, human, face, crowd"

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
        ref_paths = list(payload.get("ref_paths") or [])
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

        if not ref_paths:
            raise RuntimeError("edit job has no reference images")

        names: list[str] = []
        for i, p in enumerate(ref_paths[:3]):
            path = Path(p)
            data = path.read_bytes()
            names.append(client.upload_image(data, path.name or f"ref_{i}.png"))

        aspect = payload.get("aspect") or "3:4"
        width, height = resolve_size(aspect, "sdxl")
        edit_prompt = job.prompt or ""
        # Character half-body edits must keep opaque white — never transparency grid.
        if (job.target_field or "") in ("half",) or "半身" in edit_prompt:
            if "纯白" not in edit_prompt:
                edit_prompt = (
                    f"{edit_prompt}。纯白色不透明实底背景，不要透明，不要棋盘格，不要灰白方格。"
                )
            edit_negative = (
                "checkerboard, checkered background, transparency grid, alpha checker, "
                "transparent background, png transparency pattern, grey and white squares"
            )
        else:
            edit_negative = ""
        wf = compile_qwen_edit(
            prompt=edit_prompt,
            negative=edit_negative,
            ref_names=names,
            seed=next_seed(None, 0, False),
            width=width,
            height=height,
        )
        pid = client.queue_prompt(wf)
        hist = client.wait_history(pid, timeout_seconds=self.job_timeout)
        images = client.collect_images(hist)
        if not images:
            raise RuntimeError("Comfy edit returned no images")
        return images[0]
