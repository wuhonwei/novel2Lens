# Guofeng T2I + Qwen edit + shot first frames

Date: 2026-09-06  
Status: approved (user)

## Goal

- All asset T2I (character full, scene far, prop) uses **Guofeng SDXL**.
- All edits (half, near, shot first-frame) use **Qwen-Image-Edit-2511**, aligned with aiImage prompt wrapping + retry.
- Chapter button: generate all first-frame rasters for current chapter.
- Book button: generate all first-frame rasters for all chapters.
- E2E: project **青渡川自主测试V2**, style **国漫3D**.

## Model routing

| Task | Backend |
|------|---------|
| full / far / image (prop) | Guofeng4.2XL |
| half / near / shot first_frame | Qwen-Image-Edit-2511 |

Style `国漫3D` maps to guofeng path. Do not route these slots to Ideogram.

## Half/full consistency

- Half edit always refs full; wrap like aiImage (`Using image N… Preserve identity…` + aspect WxH).
- Include look/outfit lock text from asset.
- Lightning → non-Lightning retry on failure; port real QA heuristics from aiImage where practical.

## Shot first frames

- `Shot.first_frame_path`; jobs may target `shot_id`.
- Aspect 16:9; ≤3 refs from shot slots; prompt from `prompt_zh` + identity wrapper.
- Store `projects/{pid}/shots/{shot_id}/first_frame.png`.
- APIs: per-shot, per-chapter batch, book batch.
- UI: chapter one-click + book one-click; same serial `image_jobs` queue; LLM mutex unchanged.

## Test

Create 青渡川自主测试V2 → assets → images → storyboards (all chapters) → book first-frames → verify paths + readiness.
