# Task 6 Report: Frontend — queue state, phases, scene slots, edit

**Status:** DONE  
**Branch:** `feature/embedded-image-pipeline`

## Summary

Book assets UI now tracks durable image jobs (poll 1.5s), shows phase badges and batch progress with cancel, uses scene **远景/近景** slots, and supports **编辑生成** (output-dir refs ≤3 + upload + prompt → `edit-image`). One-click enqueue returns immediately; LLM actions disable with tooltip `参考图生成中` while jobs are active. Hint updated to Comfy `:8189`.

## Changes

| File | Changes |
|------|---------|
| `frontend/src/api.ts` | `far_path`/`near_path`; `ImageJob`; `jobPhaseLabel`; `listImageJobs` / `cancelImageBatch` / `editAssetImage` / `listImageOutputFiles`; async generate-image response |
| `frontend/src/App.tsx` | App-level job polling + batch progress; LLM disable; BookAssets progress/cancel; AssetCard slots + EditImageModal |
| `frontend/src/flow.ts` | Scene missing-ref uses near/far/image fallback |
| `frontend/src/styles.css` | Wider scene side column, slot badges, edit modal |

## Verification

```powershell
Set-Location D:\Develop\novel2Lens\frontend
npm run build
# tsc --noEmit && vite build — OK
```

## Concerns

1. Batch `n/m` uses enqueue total minus active count; mid-session jobs from other clients may skew the denominator until refresh.
2. Manual browser smoke (enqueue → phase labels → cancel → edit modal) not run in this session.
3. Polling refreshes the full bundle when active count drops; fine for book-scale asset counts.

---

## Review fix (idle polling + edit modal clamp)

**Status:** DONE  
**Commit:** `9f258d9`

### Changes

| File | Fix |
|------|-----|
| `frontend/src/App.tsx` | Image-job polling: one fetch on mount / after enqueue; 1.5s interval only while `jobs.length > 0` or `imageBatchRef` is set; clears timer when idle. Edit modal disables file input when 3 dir refs already picked. |

### Verification

```powershell
Set-Location D:\Develop\novel2Lens\frontend
npm run build
# tsc --noEmit && vite build — OK
```
