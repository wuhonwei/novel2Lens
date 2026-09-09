# Embedded H3 Video Implementation Plan

> **For agentic workers:** Execute task-by-task. Prefer TDD where noted.

**Goal:** Embed MiniMax H3 I2V into novel2Lens for per-shot and chapter-batch MP4 generation.

**Architecture:** Port aiImage2Video H3 pipeline under `app/h3_pipeline/`; durable `video_jobs` + serial `VideoWorker`; H3 Comfy on port 8190.

**Tech Stack:** FastAPI, SQLite, httpx, Pillow, ComfyUI minmaxH3, React/Vite

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-09-embedded-h3-video-design.md`
- No ref2va in v1
- Default turbo=true, aspect 16:9, clarity 0.75
- Commit+push after working slices

---

### Task 1: H3 pipeline port + params tests

**Files:**
- Create: `backend/app/h3_pipeline/__init__.py`
- Create: `backend/app/h3_pipeline/params.py`
- Create: `backend/app/h3_pipeline/image_prep.py`
- Create: `backend/app/h3_pipeline/workflow.py`
- Create: `backend/tests/test_h3_params.py`

- [ ] Port params/image_prep/workflow (I2V only) from aiImage2Video
- [ ] Test `seconds_to_frames(6) % 17 == 5` and resolution 16:9@0.75
- [ ] Commit

### Task 2: H3 Comfy client/manager + config

**Files:**
- Create: `backend/app/h3_pipeline/comfy_client.py` (sync)
- Create: `backend/app/h3_pipeline/comfy_manager.py`
- Modify: `backend/app/config.py`

- [ ] Add `N2L_H3_*` settings (port 8190, minmaxH3 paths, Shared models)
- [ ] Sync client: ready/h3 nodes, upload, prompt, wait, extract video
- [ ] Manager: launch with --port 8190, refuse non-H3 occupant
- [ ] Commit

### Task 3: DB video_path + VideoJob

**Files:**
- Modify: `backend/app/db.py`
- Modify: `backend/app/serialize.py`
- Create: `backend/tests/test_video_job_schema.py`

- [ ] `Shot.video_path`; `VideoJob` table; `ensure_schema`
- [ ] Serialize shot includes `video_path`
- [ ] Commit

### Task 4: Enqueue + VideoWorker

**Files:**
- Create: `backend/app/video_jobs.py`
- Create: `backend/app/video_worker.py`
- Create: `backend/tests/test_enqueue_video.py`
- Modify: `backend/app/main.py` lifespan

- [ ] Tests: reject without first_frame / h3_prompt; chapter skip existing
- [ ] Implement enqueue shot/chapter; worker runs workflow; write video.mp4
- [ ] Start VideoWorker in lifespan
- [ ] Commit

### Task 5: API + frontend

**Files:**
- Modify: `backend/app/main.py`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/ShotCard.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/useImageJobPoll.ts` or add `useVideoJobPoll.ts`

- [ ] Routes generate-video / generate-videos / video-jobs
- [ ] ShotCard button + video player; chapter batch button
- [ ] Poll + patch `video_path`
- [ ] Commit + push
