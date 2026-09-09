# Embedded MiniMax H3 video generation

Date: 2026-09-09  
Status: approved (user); implementing

## Goal

Embed local MiniMax H3 image→video (from `aiImage2Video`) into novel2Lens so each shot can generate an MP4 from its first frame + `h3_prompt`, including chapter batch enqueue. No voice/ref2va in v1.

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| Integration | Port modules into novel2Lens (not HTTP sidecar) |
| H3 Comfy port | Separate **8190** (image Comfy stays **8189**) |
| Scope v1 | Single-shot generate + chapter batch |
| Voice / ref2va | Out of scope |
| Defaults | aspect `16:9`, clarity `0.75`, turbo on (8 steps), duration ← `shot.duration_s` |
| Batch skip | Skip shots that already have `video_path` unless `overwrite=true` |
| Prompt | Use `h3_prompt` as-is |
| Output | `projects/{pid}/shots/{sid}/video.mp4` via `/media` |

## Architecture

```
ShotCard / 本章视频
    → POST generate-video(s)
    → VideoJob (SQLite) queued
    → VideoWorker (daemon thread, serial)
         → ensure H3 Comfy :8190 (minmaxH3 + Shared models)
         → fit first_frame → upload → build_h3_i2v_workflow
         → wait → copy MP4 → shot.video_path
    → FE polls video-jobs / bundle.video_path
```

### Modules (ported / adapted from `D:\Develop\aiImage2Video`)

| novel2Lens path | Source |
|-----------------|--------|
| `app/h3_pipeline/params.py` | `params.py` |
| `app/h3_pipeline/image_prep.py` | `image_prep.py` |
| `app/h3_pipeline/workflow.py` | `workflow.py` (I2V only) |
| `app/h3_pipeline/comfy_client.py` | sync httpx port of H3 client |
| `app/h3_pipeline/comfy_manager.py` | launch on `N2L_H3_COMFY_PORT` |

### Config (`N2L_`)

- `h3_comfy_port=8190`
- `h3_comfy_root` → minmaxH3 ComfyUI
- `h3_comfy_python`, shared models/input/output
- Model filenames same as aiImage2Video defaults

### Data

- `Shot.video_path`
- Table `video_jobs` mirroring image job fields (`shot_id`, `status`, `phase`, `error`, `batch_id`, `payload_json`, …)

### API

- `POST /api/projects/{pid}/shots/{sid}/generate-video`
- `POST /api/projects/{pid}/chapters/{cid}/generate-videos?overwrite=`
- `GET /api/projects/{pid}/video-jobs?active_only=`
- `POST /api/video-jobs/cancel-all` (optional; reuse pattern)

### Frontend

- ShotCard: generate / progress / `<video>` when `video_path`
- Chapter: 「生成本章视频」
- Poll active video jobs like image jobs

## Non-goals

- ref2va, project-wide one-click video, concat export, automatic GPU kill of image Comfy

## Acceptance

- With first frame + h3_prompt, single-shot enqueue succeeds and writes MP4
- Chapter batch enqueues eligible shots; skips missing frame/prompt; skips existing video unless overwrite
- H3 Comfy listens on 8190; image stack on 8189 remains usable
- Unit tests: params frames, enqueue gates, serialize `video_path`
