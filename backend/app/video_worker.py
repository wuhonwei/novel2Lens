"""Serial MiniMax H3 video worker (daemon thread)."""
from __future__ import annotations

import json
import logging
import shutil
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db import Shot, VideoJob, project_dir
from app.h3_pipeline.comfy_client import H3ComfyClient
from app.h3_pipeline.comfy_manager import ensure_h3_comfy_running
from app.h3_pipeline.image_prep import save_fitted
from app.h3_pipeline.params import resolution_from_aspect_clarity, seconds_to_frames, steps_for_turbo
from app.h3_pipeline.workflow import build_h3_i2v_workflow
from app.video_jobs import has_active_video_jobs, next_queued_video_job

log = logging.getLogger(__name__)


class VideoWorker:
    def __init__(
        self,
        session_factory: sessionmaker,
        *,
        poll_interval: float = 0.8,
        idle_poll_interval: float = 3.0,
        ensure_comfy: Callable[[], Any] | None = None,
        client_factory: Callable[[], H3ComfyClient] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.poll_interval = poll_interval
        self.idle_poll_interval = idle_poll_interval
        self._ensure_comfy = ensure_comfy or ensure_h3_comfy_running
        self._client_factory = client_factory or H3ComfyClient
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._idle_streak = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="video-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

    def drain_once(self) -> int:
        done = 0
        while True:
            db = self.session_factory()
            try:
                job = next_queued_video_job(db)
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
                job = next_queued_video_job(db)
                active = has_active_video_jobs(db)
                if not job:
                    self._idle_streak += 1
                    sleep_s = self.poll_interval
                    if self._idle_streak > 3:
                        sleep_s = min(
                            self.idle_poll_interval,
                            self.poll_interval * (1.0 + 0.5 * (self._idle_streak - 3)),
                        )
                    if not active:
                        time.sleep(sleep_s)
                    else:
                        time.sleep(self.poll_interval)
                    continue
                self._idle_streak = 0
                job_id = job.id
            finally:
                db.close()
            self._process_job_id(job_id)

    def _process_job_id(self, job_id: str) -> None:
        db = self.session_factory()
        try:
            job = db.get(VideoJob, job_id)
            if not job or job.status != "queued":
                return
            self._run_job(db, job)
        except Exception as exc:  # noqa: BLE001
            log.exception("video job %s failed", job_id)
            job = db.get(VideoJob, job_id)
            if job and job.status == "running":
                job.status = "failed"
                job.phase = ""
                job.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-500:]}"
                db.commit()
        finally:
            db.close()

    def _save(self, db: Session, job: VideoJob) -> bool:
        check = self.session_factory()
        try:
            fresh = check.get(VideoJob, job.id)
            if fresh is not None and fresh.status == "cancelled":
                db.rollback()
                db.refresh(job)
                return False
        finally:
            check.close()
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
        return True

    def _cancelled(self, job_id: str) -> bool:
        db = self.session_factory()
        try:
            fresh = db.get(VideoJob, job_id)
            return bool(fresh and fresh.status == "cancelled")
        finally:
            db.close()

    def _run_job(self, db: Session, job: VideoJob) -> None:
        job.status = "running"
        job.phase = "starting_comfy"
        job.error = ""
        if not self._save(db, job):
            return

        try:
            payload = json.loads(job.payload_json or "{}")
            if not isinstance(payload, dict):
                payload = {}
        except json.JSONDecodeError:
            payload = {}

        shot = db.get(Shot, job.shot_id)
        if not shot or shot.project_id != job.project_id:
            job.status = "failed"
            job.phase = ""
            job.error = "shot_not_found"
            self._save(db, job)
            return

        prompt = (job.prompt or shot.h3_prompt or "").strip()
        from app.domain.prompts import ensure_h3_language_lock

        prompt = ensure_h3_language_lock(prompt)
        first_rel = (payload.get("first_frame_path") or shot.first_frame_path or "").strip()
        if not first_rel or not prompt:
            job.status = "failed"
            job.phase = ""
            job.error = "missing_first_frame_or_prompt"
            self._save(db, job)
            return

        first_abs = Path(settings.data_dir) / first_rel
        if not first_abs.is_file():
            job.status = "failed"
            job.phase = ""
            job.error = f"first_frame_missing:{first_abs}"
            self._save(db, job)
            return

        aspect = str(payload.get("aspect") or "16:9")
        clarity = str(payload.get("clarity") or "0.75")
        turbo = bool(payload.get("turbo", True))
        duration_s = float(payload.get("duration_s") or shot.duration_s or 6.0)
        width, height = resolution_from_aspect_clarity(aspect, clarity)
        length = seconds_to_frames(duration_s)
        steps = steps_for_turbo(turbo)

        job.phase = "ensuring_comfy"
        if not self._save(db, job):
            return
        if self._cancelled(job.id):
            return

        # Free image Comfy (Qwen Edit / SDXL) before loading H3 on the same GPU.
        try:
            from app.comfy_pipeline.comfy import ComfyClient

            ComfyClient(settings.comfy_base_url).free_memory()
        except Exception:  # noqa: BLE001
            log.exception("image Comfy free_memory before H3 failed")

        self._ensure_comfy()
        client = self._client_factory()

        job.phase = "fitting_frame"
        if not self._save(db, job):
            return

        work = project_dir(job.project_id) / "shots" / shot.id / "_h3_work"
        work.mkdir(parents=True, exist_ok=True)
        fitted = work / "first_frame_fit.png"
        save_fitted(first_abs, fitted, width, height, mode="cover")

        job.phase = "uploading"
        if not self._save(db, job):
            return
        if self._cancelled(job.id):
            return

        uploaded = client.upload_image(fitted)
        seed = int(uuid.uuid4().int % (2**31 - 1))
        workflow = build_h3_i2v_workflow(
            image_filename=uploaded,
            prompt=prompt,
            width=width,
            height=height,
            length=length,
            seed=seed,
            turbo=turbo,
            steps=steps,
            unet_name=settings.h3_unet_name,
            clip_name=settings.h3_clip_name,
            video_vae_name=settings.h3_video_vae_name,
            audio_vae_name=settings.h3_audio_vae_name,
            turbo_lora_name=settings.h3_turbo_lora_name,
            filename_prefix=f"video/n2l_{shot.id[:8]}",
        )

        job.phase = "queued_comfy"
        if not self._save(db, job):
            return
        if self._cancelled(job.id):
            return

        prompt_id = client.queue_prompt(workflow, client_id=f"n2l-video-{job.id}")
        payload["comfy_prompt_id"] = prompt_id
        job.payload_json = json.dumps(payload, ensure_ascii=False)
        job.phase = "generating"
        if not self._save(db, job):
            return

        history = client.wait_for_prompt(prompt_id)
        if self._cancelled(job.id):
            return

        job.phase = "copying_output"
        if not self._save(db, job):
            return

        src_video = client.extract_video_path(history, Path(settings.h3_shared_output))
        dest_rel = f"projects/{job.project_id}/shots/{shot.id}/video.mp4"
        dest_abs = Path(settings.data_dir) / dest_rel
        dest_abs.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_video, dest_abs)

        # H3 still invents babble on silent shots despite prompt locks — strip audio.
        try:
            import json as _json

            from app.domain.video_speech import extract_expected_speech, speech_expected
            from app.video_qa import force_silent_audio

            lines = _json.loads(shot.lines_json or "[]")
            expected = extract_expected_speech(
                prompt,
                lines=lines if isinstance(lines, list) else [],
                narration=shot.narration or "",
            )
            if not speech_expected(expected):
                force_silent_audio(dest_abs)
        except Exception:  # noqa: BLE001
            log.exception("silent-audio postprocess failed for %s", shot.id)

        shot.video_path = dest_rel
        payload["result_path"] = dest_rel
        job.payload_json = json.dumps(payload, ensure_ascii=False)
        job.status = "succeeded"
        job.phase = ""
        job.error = ""
        self._save(db, job)
        try:
            from app.video_scores import schedule_score_after_video

            schedule_score_after_video(job.project_id, shot.id)
        except Exception:  # noqa: BLE001
            log.exception("schedule video QA failed for %s", shot.id)
        # Unload H3 weights so a later first-frame/image job does not OOM.
        try:
            client.free_memory()
        except Exception:  # noqa: BLE001
            log.exception("H3 free_memory after video job failed")
