# 全书资产一键生图（对接造像）Design

**Date:** 2026-09-05  
**Status:** Approved (user: 按这个做; 半身 3:4)

## Goal

On novel2Lens book-assets page: one-click generate reference images via **造像 HTTP API**, auto-save to a configurable directory, associate with assets. Per-image delete / manual upload / regenerate. Start scripts also launch 造像.

## Integration

- Call `http://127.0.0.1:8000` (configurable per project / env `N2L_ZAOXIANG_BASE_URL`).
- Generate: `POST /api/jobs/generate` → poll `GET /api/jobs/{id}` → download first `role=success` image via `GET /api/images/{id}`.
- Half-from-full: `POST /api/jobs/edit` (multipart, full PNG as ref, `aspect=3:4`).

## Aspect ratios

| Kind | Field(s) | Aspect |
|------|----------|--------|
| character | full | 9:16 |
| character | half (from full via edit) | 3:4 |
| scene | image | 16:9 |
| prop | image | 1:1 |

## Save & association

- Project setting `image_output_dir` (frontend editable). Default: `{data_dir}/projects/{id}/generated`.
- Files written under that dir (or project assets folder) and paths stored on Asset (`full_path` / `half_path` / `image_path`) for `/media` serving.
- Delete: clear path field (+ optional unlink file).
- Upload: existing upload endpoint.
- Regenerate: single asset field or full asset (char = full then half).

## UI

- Book assets hero: output-dir input + save; 「一键生成参考图」 button with progress.
- AssetCard: thumbs with 删除 / 上传 / 重新生成 per slot.

## Start scripts

- `start.ps1` / `start.bat` invoke `D:\Develop\aiImage\scripts\start.ps1` and wait for `http://127.0.0.1:8000/api/health` (and ideally Comfy ok).

## Out of scope

- Copying Comfy workflows into novel2Lens.
- Batch parallel GPU jobs (sequential per asset is enough for v1).
