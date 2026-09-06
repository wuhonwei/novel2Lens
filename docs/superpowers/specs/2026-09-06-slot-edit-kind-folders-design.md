# Slot edit + kind folders for reference images

**Date:** 2026-09-06  
**Status:** Approved  
**Approach:** A — new writes under 人物/场景/物品; edit modal defaults to that kind; per-slot 编辑 between 重生成 and 删除.

## Goals

1. Per thumb slot: 上传 | 重生成 | **编辑** | 删除.
2. Edit opens modal: up to 3 refs + prompt → existing Qwen Image Edit enqueue.
3. New generated files land in `{image_output_dir}/{人物|场景|物品}/{safe_name}_{field}.png`.
4. Edit modal lists that kind folder first; optional filter 全部/人物/场景/物品.
5. Legacy `{asset_id}/` under the output dir is ignored (new projects only use 人物/场景/物品).

## Non-goals

- Native OS file dialog default path (browser cannot set it).
- Moving first frames into the three folders.
- Deleting old per-asset_id folders.

## Kind folder map

| kind | folder |
|------|--------|
| character | 人物 |
| scene | 场景 |
| prop | 物品 |

## Implementation notes

- `write_asset_image`: write under kind folder; keep media mirror under `data/projects/.../assets/...` for API serving.
- `list_image_output_files`: return `kind` / `folder` metadata; API may accept `?kind=character`.
- Slot edit opens `EditImageModal` with `targetField` preselected to that slot.
- Card-level「编辑生成」kept, opens same modal without forced field (or first field).
