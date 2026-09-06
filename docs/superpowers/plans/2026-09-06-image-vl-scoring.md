# Image VL Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Optional one-click VL scoring of generated asset images and first frames with UI badges, band counts, and clear-on-regen/delete.

**Architecture:** Persist per-slot scores on Asset (`image_scores_json`) and Shot (`first_frame_score`/`comment`). Score via Ollama `qwen2.5vl:7b` multimodal chat. Frontend shows badges + summary chips; scene near/far stacked in two rows.

**Tech Stack:** FastAPI, SQLAlchemy/SQLite, httpx, Ollama OpenAI-compatible vision API, React/Vite.

## Global Constraints

- Vision model default: `qwen2.5vl:7b` at `http://127.0.0.1:11434/v1`
- Bands: >80 较好 green; 60–80 一般 yellow; <60 较差 red; missing 未评估 white/`--ink`
- Scoring is user-triggered only
- Delete/regen clears corresponding score

---

### Task 1: Score helpers + DB fields

**Files:**
- Create: `backend/app/image_scores.py`
- Modify: `backend/app/db.py`, `backend/app/config.py`, `backend/app/services.py` (serialize)
- Test: `backend/tests/test_image_scores.py`

- [ ] Band helpers `score_band(score) -> good|ok|bad|none`
- [ ] `clamp_score`, `parse_score_payload`, `clear_field_score`, `set_field_score`
- [ ] Columns + ensure_schema
- [ ] Serialize scores on asset/shot
- [ ] Tests + commit

### Task 2: VL client + score batch API

**Files:**
- Modify: `backend/app/llm.py` (multimodal messages)
- Create/extend: `backend/app/image_scores.py` (score_image_bytes, score_project)
- Modify: `backend/app/main.py` endpoint `POST .../score-images`
- Modify: `backend/app/image_gen.py`, `backend/app/image_worker.py`, `backend/app/image_jobs.py` clear hooks
- Test: `backend/tests/test_image_scores_api.py` with mocked VL

- [ ] Vision chat accepting image+text
- [ ] Batch enumerator for assets/shots
- [ ] Reset on clear/write
- [ ] Tests + commit

### Task 3: Frontend UI

**Files:**
- Modify: `frontend/src/api.ts`, `frontend/src/App.tsx`, `frontend/src/styles.css`

- [ ] Types + `scoreImages` API
- [ ] Summary chips + 评估图片 button
- [ ] Score badge + tooltip
- [ ] Scene two-row thumbs
- [ ] First-frame badge
- [ ] Manual UI check notes + commit
