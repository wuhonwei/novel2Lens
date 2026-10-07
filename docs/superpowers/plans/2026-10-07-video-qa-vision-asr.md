# Video QA (Vision + ASR) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Score generated H3 videos against `h3_prompt` using keyframe vision + local ASR; show scores in UI; auto-score after video success; optional auto-regen (default off).

**Architecture:** Mirror image VL scoring. `app/video_qa.py` handles ffmpeg/ASR/speech parse/combine; `app/video_scores.py` orchestrates VL + persistence; APIs + VideoWorker hook; ShotCard/App badges and buttons.

**Tech Stack:** FastAPI, SQLAlchemy/SQLite, ffmpeg CLI, Ollama `qwen2.5vl:7b`, optional `faster-whisper`, React/Vite.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-10-07-video-qa-vision-asr-design.md`
- Bands: >80 good; 60–80 ok; <60 bad; missing none (reuse `image_scores.score_band`)
- Auto-regen default **false** (`N2L_VIDEO_QA_AUTO_REGEN`)
- ASR optional: if missing, visual-only score + `audio: skipped` in json
- Clear scores when new `video_path` is written / video job enqueued
- Commit + push after each task (repo rule)

## File map

| File | Responsibility |
|------|----------------|
| `backend/app/domain/video_speech.py` | Parse expected speech from h3/lines/narration; transcript similarity |
| `backend/app/video_qa.py` | ffmpeg keyframes/wav; ASR wrapper; combine scores |
| `backend/app/video_scores.py` | Persist scores; batch score shots; auto-regen gate |
| `backend/app/db.py` | Columns + migrate |
| `backend/app/config.py` | Settings |
| `backend/app/serialize.py` | Expose score fields |
| `backend/app/main.py` | `score-videos` / `score-video` APIs |
| `backend/app/video_jobs.py` / `video_worker.py` | Clear on enqueue; auto-score after success |
| `frontend/src/api.ts`, `ShotCard.tsx`, `App.tsx` | UI |
| `backend/tests/test_video_speech.py`, `test_video_qa.py`, `test_video_scores_api.py` | Tests |

---

### Task 1: Expected speech + score combine (pure logic)

**Files:**
- Create: `backend/app/domain/video_speech.py`
- Create: `backend/tests/test_video_speech.py`

**Produces:**
- `extract_expected_speech(h3_prompt, lines=None, narration="") -> list[str]`
- `speech_expected(expected: list[str]) -> bool`
- `score_transcript(expected: list[str], transcript: str) -> dict` with `score`, `issues`
- `combine_video_scores(visual: int | None, audio: int | None, *, speech_expected: bool) -> dict` with `score`, `weights`, `comment_hint`

- [ ] Write failing tests for dialogue / 画外口播 / silent / foreign-empty mismatch
- [ ] Implement helpers
- [ ] Tests pass + commit

### Task 2: ffmpeg + ASR wrappers

**Files:**
- Create: `backend/app/video_qa.py`
- Create: `backend/tests/test_video_qa.py`
- Modify: `backend/app/config.py` (video_qa_* settings)
- Modify: `backend/pyproject.toml` optional `[asr]` extra for faster-whisper (document; not required for CI)

**Produces:**
- `extract_keyframes(video: Path, work: Path, count: int) -> list[Path]`
- `extract_wav(video: Path, wav: Path) -> Path`
- `transcribe_wav(wav: Path) -> str` (empty + note if ASR unavailable)
- `asr_available() -> bool`

- [ ] Failing tests with monkeypatched subprocess
- [ ] Implement
- [ ] Tests pass + commit

### Task 3: DB + serialize + clear hooks

**Files:**
- Modify: `backend/app/db.py`
- Modify: `backend/app/serialize.py`
- Modify: `backend/app/video_jobs.py` (clear on enqueue)
- Modify: `backend/app/video_worker.py` (clear already covered by enqueue; ensure write path ok)
- Create: `backend/app/video_scores.py` (clear/set helpers)
- Test: extend `backend/tests/test_enqueue_video.py` or `test_video_scores_api.py`

**Produces:**
- Columns `video_score`, `video_score_comment`, `video_qa_json`
- `clear_shot_video_score(shot)`, `set_shot_video_score(...)`

- [ ] Migration + serialize
- [ ] Clear on `enqueue_shot_video`
- [ ] Tests + commit

### Task 4: Score orchestration + API

**Files:**
- Modify: `backend/app/video_scores.py` — `score_shot_video`, `score_project_videos`
- Modify: `backend/app/main.py` — POST endpoints
- Modify: `frontend` later
- Test: `backend/tests/test_video_scores_api.py` with mocked VL + ASR + ffmpeg

**Produces:**
- `async score_shot_video(db, project, shot, ...) -> dict`
- `async score_project_videos(..., scope, chapter_id, shot_id)`
- Auto-regen if settings.video_qa_auto_regen and score < threshold

- [ ] Failing API test
- [ ] Implement using `image_scores.score_image_file` for frames
- [ ] Tests + commit

### Task 5: Auto-score after video success

**Files:**
- Modify: `backend/app/video_worker.py`
- Test: `backend/tests/test_video_worker.py` (assert schedule/clear; mock score)

- [ ] After succeed, if `video_qa_auto_after_video`, spawn background asyncio/thread to score
- [ ] Respect auto_regen
- [ ] Tests + commit

### Task 6: Frontend

**Files:**
- Modify: `frontend/src/api.ts`, `ShotCard.tsx`, `App.tsx`

- [ ] Types + `scoreVideos` / `scoreShotVideo`
- [ ] Chapter button 评估本章视频 + summary chips
- [ ] Shot button 评估视频 + `ScoreBadge` for video
- [ ] Commit

### Task 7: Smoke on V12 (optional manual)

- [ ] Score 1 dialogue shot + 1 silent shot via API; confirm badges

---

## Done when

- Unit + API tests green
- UI can score chapter/shot
- Video success auto-scores when enabled
- Auto-regen stays off by default
