# Abort model ops + required project style

**Date:** 2026-09-06  
**Status:** Draft for review  
**Approach:** B (hybrid) — client abort + server stop for sync LLM/VL; cancel all active image jobs for Comfy/Qwen queues.

## Goals

1. Every **model-calling** control can be **terminated while running**.
2. Creating a new project requires a non-empty **项目画风**.

## Non-goals

- Rollback of partial LLM writes (prescan assets already committed, scores already saved).
- Cancelling unrelated HTTP calls (save settings, upload file without model, export, merge).
- Killing an in-flight ComfyUI / Ollama OS process mid-GPU kernel (best-effort: mark job cancelled; worker stops before/after step boundaries).

## Model-calling surfaces (in scope)

| Surface | Kind | Terminate behavior |
|--------|------|--------------------|
| 一键生成全书资产 | Sync LLM | Abort fetch + server disconnect → stop further LLM rounds |
| 生成本章分镜 | Sync LLM | Same |
| 评估图片（资产 / 首帧） | Sync VL | Same; keep already-scored slots |
| 一键生成参考图 | Image jobs | Cancel **all** active jobs for project |
| 单资产重生成 / 自动生成全部 / 编辑生成排队 | Image jobs | Same cancel-all (or cancel that job’s batch + orphans) |
| 一键生成本章首帧 / 全部首帧 | Image jobs | Same |

Out of scope for terminate: 粘贴创建、上传 txt、打开/删除项目、保存设置、保存提示词、上传参考图、清除图片、导出、合并资产。

## UI

- While a scoped model op is running, show a **「终止」** control next to the busy indicator (and/or next to the triggering action area).
- 「终止」 is enabled only during that run (or while image jobs are active for image ops).
- On terminate: UI clears busy / local scoreBusy immediately; show a soft message like「已终止」 (not treated as a hard error banner if user-initiated).
- Existing 「取消批次」 keeps working; it shares the same backend cancel path as 「终止」 for image work. Prefer one cancel-all API so single-slot jobs without a batch id still stop.

## Frontend mechanics

- Introduce a shared abortable runner (extend `run`):
  - Hold `AbortController` for the active sync request.
  - Pass `signal` into `api.*` / `req`.
  - `abort()` on 「终止」; treat `AbortError` as user cancel (no scary error).
- Image ops: after enqueue, 「终止」 calls `cancelProjectImageJobs(projectId)` (new), then refresh jobs + bundle.
- Score flow currently uses local `scoreBusy`; wire it into the same abortable pattern (or lift into `run("评估…")` with signal).

## Backend: sync LLM / VL

- Long endpoints (`prescan` / `generate-assets`, `storyboard`, `score-images`) accept `Request` and periodically check `await request.is_disconnected()` (or equivalent) between LLM/VL iterations.
- Propagate optional cancel into loops in `prescan_project`, storyboard generation, and `score_project_images`.
- `chat_completion` / httpx: pass a cancel hook or use client that closes when the request task is cancelled; on disconnect, raise a dedicated `CancelledError` / return early without failing the whole process as 500 if possible (499 / 400 with `{detail:"cancelled"}` is fine; client already aborted).
- Partial persistence is OK: do not delete already-written assets or scores.

## Backend: image jobs

- Add `POST /api/projects/{project_id}/image-jobs/cancel` that marks all `queued`/`running` jobs for that project as `cancelled` (reuse `cancel_batch` logic generalized to `cancel_project_jobs`).
- Keep `POST .../image-batches/{batch_id}/cancel` as a thin wrapper or leave as-is calling the same helper filtered by batch.
- Worker already respects `cancelled` at save/run boundaries — no change required beyond using cancel-all from UI.

## Required style on create

- **Frontend:** Create panel — 「粘贴创建并进入」 and 「上传 txt 进入」 disabled (or blocked with clear hint) when `style.trim()` is empty. Label/hint marks 画风 as必填; clear default placeholder so users must fill intentionally **or** keep a placeholder but still require non-empty trim (default seed text counts as filled — **decision:** empty string invalid; current default seed `"半写实、东方江湖…"` remains allowed as a filled value; user may clear it and then must refill).
- **Backend:** `POST /api/projects` and `POST /api/projects/upload` reject empty/whitespace `style` with `400` and message like「项目画风不能为空」.
- Settings edit inside an existing project: style remains editable; empty style on patch is discouraged but **not** in scope for this change unless already validated (optional: same 400 on patch if style key present and blank — **include** for consistency).

## Acceptance

1. During 一键生成全书资产 / 分镜 / 评估, 「终止」 stops UI wait; further LLM rounds do not continue after disconnect.
2. During any image generation with active jobs, 「终止」 clears queued/running jobs for the project; progress returns to idle.
3. New project create/upload without style fails client-side and server-side.
4. Non-model buttons unchanged.

## Spec self-review

- No unresolved placeholders.
- Sync vs image cancel paths both defined.
- Partial write policy explicit (keep).
- Style rule: trim-empty rejected; seeded default still valid until cleared.
- Scope excludes export/merge/save-only actions.
