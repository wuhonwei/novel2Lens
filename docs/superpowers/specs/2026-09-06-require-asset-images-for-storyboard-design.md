# Require asset images before storyboard

Date: 2026-09-06  
Status: approved (product intent); pending user review of this file

## Goal

生成分镜前，全书资产的参考图必须齐备。缺任一则禁止生成（前端禁用 + 后端拒绝）。

## Readiness rules

| Kind | Required |
|------|----------|
| character | `confirmed` **and** `half_path` **and** `full_path` |
| scene | at least one of `near_path` / `far_path` / `image_path` |
| prop | `image_path` |

- Empty kind lists (no scenes / no props) pass vacuously.
- Characters must still be confirmed (existing book-assets gate).

## Behavior

1. **Frontend** — Storyboard CTA disabled unless all assets above are ready. Flow step “上传参考图” is **mandatory** (not “建议”); tip states 缺图不可生成分镜.
2. **Backend** — `generate_storyboard` raises a clear `ValueError` if any asset fails the table above (API clients cannot bypass UI).
3. **Packing / prompts** — Unchanged: still prefer image slots when paths exist. No “missing image → text fallback” for scene/prop/character.

## Non-goals

- Per-asset “不需要图片” toggle
- Auto-generating images as a precondition (user may upload or use existing generate-image)
- Changing first-frame packing priority or Qwen slot wording

## Acceptance

- UI: with any character missing half/full, or any scene/prop missing image, 分镜 button disabled and guide points to 全书资产.
- API: `POST .../storyboard` returns 4xx with message listing what’s missing when images incomplete.
- Tests cover ready/unready helpers and storyboard rejection.
