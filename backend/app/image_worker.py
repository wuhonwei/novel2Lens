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
from app.comfy_pipeline.character_prompt import (
    enrich_character_negative,
    enrich_character_prompt,
    prompt_requests_black_outfit,
)
from app.image_jobs import has_active_jobs, next_queued_job
from app.llm_supervisor import LlmSupervisor
from app.storyboard_ops import refresh_shot_readiness

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
        idle_poll_interval: float = 2.0,
        job_timeout: float = 600.0,
        models_dir: Path | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.comfy = comfy
        self.llm = llm
        self.poll_interval = poll_interval
        self.idle_poll_interval = idle_poll_interval
        self.job_timeout = job_timeout
        self.models_dir = models_dir or (Path(settings.comfy_root) / "models")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_kind: str | None = None
        self._running = False
        self._idle_streak = 0
        self._ckpt_cache: set[str] | None = None
        self._cancel_cache: dict[str, float] = {}

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
                    self._idle_streak += 1
                    # Back off when idle so we don't spin the DB/CPU at 0.4s forever.
                    sleep_s = self.poll_interval
                    if self._idle_streak > 3:
                        sleep_s = min(
                            self.idle_poll_interval,
                            self.poll_interval * (1.0 + 0.5 * (self._idle_streak - 3)),
                        )
                    time.sleep(sleep_s)
                    continue
                self._idle_streak = 0
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

    def _job_was_cancelled(self, job_id: str) -> bool:
        # Throttle cancel checks — sequential phase updates hit this often.
        now = time.monotonic()
        last = self._cancel_cache.get(job_id)
        if last is not None and (now - last) < 0.8:
            return False
        self._cancel_cache[job_id] = now
        check = self.session_factory()
        try:
            fresh = check.get(ImageJob, job_id)
            cancelled = fresh is not None and fresh.status == "cancelled"
            if cancelled:
                self._cancel_cache.pop(job_id, None)
            return cancelled
        finally:
            check.close()

    def _client(self) -> Any:
        return self.comfy._client()

    def _live_checkpoints(self, client: Any) -> set[str]:
        if self._ckpt_cache is None:
            self._ckpt_cache = set(client.list_checkpoints() or [])
        return self._ckpt_cache

    def _invalidate_ckpt_cache(self) -> None:
        self._ckpt_cache = None

    def _run_job(self, db: Session, job: ImageJob) -> None:
        self._running = True
        try:
            self.llm.set_image_busy(True)
            # stop_llm already settles; re-check port before touching Comfy VRAM.
            try:
                self.llm.wait_released()
            except TimeoutError as exc:
                raise RuntimeError(f"cannot start Comfy while LLM still up: {exc}") from exc
            # Extra beat only if Ollama unload may still be reclaiming — keep short;
            # stop_llm already waited settle_seconds once.
            time.sleep(min(1.5, max(0.0, float(getattr(self.llm, "settle_seconds", 5.0) or 0) * 0.15)))
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
                    self._invalidate_ckpt_cache()
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
                    self._invalidate_ckpt_cache()
                job.phase = "loading_edit"
                if not self._save(db, job):
                    return
                job.phase = "generating"
                if not self._save(db, job):
                    return
                png = self._run_edit(db, client, job, payload)

            # Abort before write/succeed if cancelled while generating
            if self._job_was_cancelled(job.id):
                db.rollback()
                db.refresh(job)
                return

            project = db.get(Project, job.project_id)
            if not project:
                raise RuntimeError("project missing")
            payload_shot_id = (payload.get("shot_id") or getattr(job, "shot_id", "") or "").strip()
            result_path = ""
            if job.target_field == "first_frame" or payload_shot_id:
                from app.db import Shot
                from app.image_gen import write_shot_first_frame

                shot = db.get(Shot, payload_shot_id or job.asset_id)
                if not shot or shot.project_id != project.id:
                    raise RuntimeError("shot missing for first_frame")
                result_path = write_shot_first_frame(project, shot, png)
            else:
                asset = db.get(Asset, job.asset_id)
                if not asset:
                    raise RuntimeError("project or asset missing")
                result_path = write_asset_image(project, asset, job.target_field, png)
                refresh_shot_readiness(
                    db, project, commit=False, asset_id=asset.id
                )

            payload["result_path"] = result_path
            payload["result_field"] = job.target_field or ""
            payload["result_asset_id"] = job.asset_id or ""
            payload["result_shot_id"] = payload_shot_id
            job.payload_json = json.dumps(payload, ensure_ascii=False)

            # Re-check after disk/ORM write: never commit paths if user cancelled.
            if self._job_was_cancelled(job.id):
                db.rollback()
                db.refresh(job)
                return

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
        live_ckpts = self._live_checkpoints(client)

        t2i_prompt = prompt
        if subject_type == "character":
            en_lock = identity_lock_en(gender=gender, age_tier=age_tier)
            if en_lock:
                t2i_prompt = f"{en_lock}. {t2i_prompt}"
            # Costume color hard-prefix — Guofeng otherwise defaults to white/gold armor beauty.
            # Match black *clothing* only (黑衣/黑袍/黑色长衫…); never hair like「黑色长发」.
            if prompt_requests_black_outfit(prompt):
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
                from app.domain.prop_hints import prop_en_anchor

                en = prop_en_anchor(prompt)
                t2i_prompt = f"{en}. {prompt}" if en else prompt
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
            if prompt_requests_black_outfit(prompt) or any(x in prompt for x in ("官服", "短打")):
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
        else:
            width, height = resolve_size(aspect, "sdxl")
            if subject_type == "character" and aspect == "9:16":
                width, height = resolve_size("9:16_fullbody", "sdxl")
            ckpt = ckpt_for_backend(backend) or "RealVisXL_V5.0_fp16.safetensors"

        from app.comfy_pipeline.qa import assess_image_bytes

        require_fb = bool(payload.get("require_fullbody"))
        last_err = ""
        last_png: bytes | None = None
        attempts = 3 if require_fb or subject_type == "character" else 2
        for attempt in range(attempts):
            steps = int(qp["steps"]) + attempt * 4
            cfg = float(qp["cfg"]) + attempt * 0.25
            if backend == "ideogram4":
                wf = compile_ideogram_t2i(
                    prompt=positive,
                    negative=negative,
                    width=width,
                    height=height,
                    seed=next_seed(None, attempt, True),
                    steps=int(qp["ideogram_steps"]) + attempt,
                    cfg=float(qp["cfg"]),
                    style=style,
                )
            else:
                wf = compile_sdxl_t2i(
                    ckpt=ckpt,
                    prompt=positive,
                    negative=negative,
                    width=width,
                    height=height,
                    seed=next_seed(None, attempt, True),
                    steps=steps,
                    cfg=cfg,
                )
            pid = client.queue_prompt(wf)
            hist = client.wait_history(pid, timeout_seconds=self.job_timeout)
            images = client.collect_images(hist)
            if not images:
                last_err = "Comfy returned no images"
                continue
            last_png = images[0]
            qa = assess_image_bytes(
                last_png,
                require_fullbody=require_fb,
                min_character_sides=int(payload.get("min_character_sides") or 0),
            )
            if qa.get("ok") or qa.get("passed"):
                return last_png
            last_err = f"qa_failed:{','.join(qa.get('reasons') or [])}"
        if last_png is not None and not require_fb:
            return last_png
        raise RuntimeError(last_err or "Comfy t2i failed")

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

        # Layered first frames: scene → people → props (sequential edit).
        from app.domain.edit_identity import is_prop_ref_label, is_scene_ref_label, person_ref_indices

        person_n = len(person_ref_indices(ref_labels)) if ref_labels else 0
        scene_n = sum(1 for lab in ref_labels if is_scene_ref_label(lab)) if ref_labels else 0
        prop_n = sum(1 for lab in ref_labels if is_prop_ref_label(lab)) if ref_labels else 0
        if person_n < 1 and not scene_n and not prop_n:
            person_n = len(ref_paths)
        layer_n = scene_n + person_n + prop_n
        use_sequential = (job.target_field or "") == "first_frame" and (
            person_n >= 2 or layer_n >= 2
        )
        if use_sequential:
            aspect = payload.get("aspect") or "3:4"
            width, height = resolve_size(aspect, "sdxl")
            edit_prompt = (job.prompt or "").strip()
            return self._run_sequential_multi_char_first_frame(
                client=client,
                job=job,
                payload=payload,
                ref_paths=ref_paths,
                ref_labels=ref_labels,
                edit_prompt=edit_prompt,
                aspect=aspect,
                width=width,
                height=height,
            )

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
        else:
            wrapped = (
                f"Using {', '.join(labeled)}, create one new image: {edit_prompt}. "
                "Preserve identity and key details from the references as instructed. "
                f"Output image aspect ratio {aspect}, resolution {width}x{height}."
            )

        last_err = ""
        last_png: bytes | None = None
        attempts = 2
        start_attempt = 0
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
                min_character_sides=int(payload.get("min_character_sides") or 0),
            )
            if qa.get("ok") or qa.get("passed"):
                return last_png
            last_err = f"qa_failed:{','.join(qa.get('reasons') or [])}"
        raise RuntimeError(last_err or "Comfy edit failed")

    def _run_sequential_multi_char_first_frame(
        self,
        *,
        client: Any,
        job: ImageJob,
        payload: dict[str, Any],
        ref_paths: list[str],
        ref_labels: list[str],
        edit_prompt: str,
        aspect: str,
        width: int,
        height: int,
    ) -> bytes:
        """Place each named person into the first frame one at a time."""
        from app.sequential_first_frame import run_sequential_multi_char_first_frame

        return run_sequential_multi_char_first_frame(
            client=client,
            job=job,
            payload=payload,
            ref_paths=ref_paths,
            ref_labels=ref_labels,
            edit_prompt=edit_prompt,
            aspect=aspect,
            width=width,
            height=height,
            job_timeout=self.job_timeout,
            set_phase=self._bind_seq_phase(job),
            session_factory=self.session_factory,
        )

    def _bind_seq_phase(self, job: ImageJob) -> Callable[[str], None]:
        def set_phase(phase: str) -> None:
            db = self.session_factory()
            try:
                fresh = db.get(ImageJob, job.id)
                if fresh is None or fresh.status == "cancelled":
                    return
                from datetime import datetime, timezone

                fresh.phase = phase
                fresh.updated_at = datetime.now(timezone.utc)
                db.commit()
                job.phase = phase
            finally:
                db.close()

        return set_phase
