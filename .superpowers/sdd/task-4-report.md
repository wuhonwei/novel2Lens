# Task 4 Report: ImageWorker + enqueue API surface

**Status:** DONE  
**Branch:** `feature/embedded-image-pipeline`  
**Commit:** `fe8070e` — Replace 造像 HTTP with serial embedded image job worker.

## Summary

Replaced sync 造像 HTTP generation with a durable serial `ImageWorker` + SQLite `ImageJob` queue. One-click enqueue orders all t2i (full/far/prop) before all edit (half/near). Generate APIs return immediately with `batch_id`/`jobs`. LLM-heavy routes return **409** while any image job is queued/running. Lifespan starts the worker and marks stale `running` jobs as `failed`. Unit tests use injectable `FakeComfy` (tiny PNG, no GPU).

## TDD Steps Executed

| Step | Action | Result |
|------|--------|--------|
| 1 | Added `backend/tests/test_image_worker.py` (order, 409, serial) | RED — missing modules |
| 2 | Implemented `image_jobs.py`, `image_worker.py`, rewrote `image_gen.py`, wired `main.py` | OK |
| 3 | Updated `test_image_gen_api.py` for async enqueue + FakeComfy drain | OK |
| 4 | Gutted `zaoxiang_client.py` to stub | OK |
| 5 | Full suite | **46 passed** |

## Files Modified / Created

| File | Changes |
|------|---------|
| `backend/app/image_jobs.py` | **New** — enqueue_one_click, enqueue_asset_field, enqueue_manual_edit, list/cancel/has_active |
| `backend/app/image_worker.py` | **New** — serial worker, phases, drain_once for tests |
| `backend/app/image_gen.py` | Rewritten — prompts/paths/clear only; no zaoxiang sync gen |
| `backend/app/main.py` | Lifespan worker; enqueue routes; LLM 409 gate; image-jobs/cancel/output-files |
| `backend/app/zaoxiang_client.py` | Gutted to `ZaoxiangError` stub |
| `backend/tests/test_image_worker.py` | **New** — FakeComfy tests |
| `backend/tests/test_image_gen_api.py` | Async enqueue + worker drain |
| `backend/tests/test_zaoxiang_client.py` | Stub type check only |

## Interfaces (as specified)

- `enqueue_one_click(db, project) -> {batch_id, job_ids, jobs}`
- `enqueue_asset_field` / `enqueue_manual_edit` / `list_active_jobs` / `cancel_batch`
- Worker phases: `ensuring_comfy` \| `loading_t2i` \| `loading_edit` \| `generating`
- APIs: `POST generate-images`, `generate-image`, `edit-image`, `GET image-jobs`, `POST cancel`, `GET image-output-files`

## Concerns

1. `generate-image` with `field=None` now enqueues a single default slot (full/far/image), not both character slots — client should enqueue half after full succeeds (or use one-click).
2. Real Comfy path still needs GPU E2E (Task 8); FakeComfy does not exercise workflow correctness beyond compile+queue call.
3. `zaoxiang_base_url` project setting remains in DB/config but is unused by the image pipeline.
4. Edit half/near jobs resolve refs from asset paths at run time — if a prior t2i in the same batch fails, edit fails with a clear error rather than blocking enqueue.

## Verification Commands

```powershell
Set-Location D:\Develop\novel2Lens\backend
python -m pytest tests/test_image_worker.py tests/test_image_gen_api.py -v
python -m pytest -v
# 46 passed
```
