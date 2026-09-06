# One-click all-chapter storyboard

**Date:** 2026-09-06  
**Status:** Approved  
**Approach:** A — backend `POST .../storyboard-all` looping existing `generate_storyboard`.

## Behavior

- UI button: **一键生成全部章节分镜** next to 生成本章分镜.
- Enabled when book assets ready + reference images complete + not image-busy + not otherwise busy.
- **Overwrite checkbox** (共享「覆盖已有分镜」):
  - unchecked: skip chapters that already have shots
  - checked: regenerate every chapter with `overwrite=True`
- Abort: client AbortSignal + server disconnect between chapters.
- Partial success OK: keep chapters already written; return `generated`, `skipped`, `errors`.

## API

`POST /api/projects/{project_id}/storyboard-all?overwrite=false`

Response includes bundle fields plus:

```json
{
  "ok": true,
  "generated": ["chapter_id", ...],
  "skipped": ["chapter_id", ...],
  "errors": ["章标题: message", ...],
  "cancelled": false
}
```

## Non-goals

- Auto first-frame generation
- Per-chapter parallel LLM calls
