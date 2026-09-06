# Abort Model Ops + Required Style Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Abortable model ops (sync LLM/VL + cancel-all image jobs) and required non-empty project style on create/upload/patch.

**Architecture:** Frontend AbortController + shared 「终止」; backend disconnect checks in long LLM/VL loops; `cancel_project_jobs` for all active image jobs; style validation 400.

**Tech Stack:** FastAPI Request.is_disconnected, httpx cancel, React AbortController, existing ImageJob cancel flags.

## Global Constraints

- Partial writes kept on cancel (no rollback)
- Terminate only model-calling surfaces listed in spec
- Style: trim-empty rejected; default seed text counts as filled

---

### Task 1: Required style + cancel-all image jobs (backend)

**Files:** `backend/app/main.py`, `backend/app/image_jobs.py`, tests

- [ ] Tests: create/upload/patch empty style → 400; cancel project jobs marks queued/running cancelled
- [ ] Implement validation + `cancel_project_jobs` + `POST .../image-jobs/cancel`
- [ ] Commit

### Task 2: Disconnect-aware sync LLM/VL

**Files:** `backend/app/llm.py`, `services.py` (prescan), storyboard path, `image_scores.py`, `main.py`

- [ ] Tests: mocked multi-step score/prescan stops when disconnect predicate true
- [ ] Pass `is_cancelled` / Request into loops; chat_completion supports cancel
- [ ] Commit

### Task 3: Frontend abort runner + 终止 + style required

**Files:** `frontend/src/api.ts`, `App.tsx`, `styles.css`

- [ ] `req` accepts signal; API methods pass through
- [ ] `run` holds AbortController; show 终止; AbortError → 「已终止」
- [ ] Image busy: 终止 calls cancel-all
- [ ] Create/upload require style.trim()
- [ ] Build + commit
