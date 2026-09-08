# Sequential unlimited first frames + manual assets

Date: 2026-09-09  
Status: approved (user); implementing

## Goal

- First-frame generation stacks layers **sequentially** (not capped by “dual/3-ref one-shot”): **scene plate → each character → each prop**.
- **No hard cap** on named characters per shot for packing, enqueue, or sequential generation.
- Scene and prop **reference images** participate in the same sequential path (no longer forced to text-only when ≥2 people).
- When an asset is **deleted or unmatched**, first-frame prompts must **not** invent text-description stand-ins for that asset.
- Users can **manually create** character / scene / prop assets (name + description only); after images exist, storyboard generation **name-matches** them like registry assets.

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| Stack order | Scene → characters → props |
| Implementation | Extend existing `sequential_first_frame` pipeline (not a full LayerSpec rewrite) |
| Manual asset kinds | character, scene, prop |
| After create | Insert row only; no auto T2I |
| Attach to shots | Name-match on storyboard generate / recompile |
| Missing image vs deleted | Asset exists but no image → text fallback allowed; deleted/unmatched → omit text refs |

## Architecture

### When sequential runs

Use sequential stacking whenever the shot has **at least one usable reference image** among scene / characters / props.

- Pure text (zero reference images): keep any existing non-sequential / text-only path unchanged.
- One character + optional scene/prop images: still sequential (scene → that person → props), not the old one-shot ≤3-ref mix—so behavior is uniform.

### Layer skip rules

| Layer | Condition to run | If skipped |
|-------|------------------|------------|
| Scene | Scene asset resolved **and** scene image path exists | Continue with next stage; if no plate yet, first character place creates the initial plate |
| Character i | Character asset resolved **and** half/full path exists | Omit that person from image stack; if asset exists with desc only, allow text in prompt; if unmatched/deleted, no text stand-in |
| Prop j | Prop asset resolved **and** image path exists | Same as character |

### Per-step edit budget

Unchanged Qwen constraint: **≤3 images per edit call**.

- Scene stage: scene ref as base (or edit onto empty/canvas per existing Comfy entry); output becomes plate.
- Character 0: place first person onto plate (plate + person, or person alone if no scene plate).
- Character 1..N-1: plate + optional visual lock + new person (existing `seq_locks`).
- Prop j: plate + optional lock (prefer last-stable character lock when budget allows) + prop ref; new English wrap: add object only, preserve identities/composition.

### Character count & standing

- Remove / stop enforcing `MAX_NAMED_CHARACTERS` and `MAX_MULTI_CHAR_REF_IMAGES` (currently 8) in packing, storyboard slice, and enqueue.
- Align `SHOT_SYSTEM` with “no hard people cap; match existing assets by name”.
- Standing labels: persons 0–2 keep 左一 / 中 / 右一; person ≥3 use **按构图自然站位** with ordinal text `人物{i+1}` (no invented 左二/右二 geometry until we have real multi-slot layout). Extend `CN_NUM` so prompt 图N uses Chinese numerals beyond 三 where needed.
- Fix stale repair heuristic that treats `len(slots) > 3` as always needing portrait repair.

### Packing & refs

- `pack_qwen_slots`: do **not** force scene/props into `text_fallbacks` solely because `len(characters) >= 2` when those assets have images.
- Persist ordered layer metadata for the worker (slots and/or payload): scene path, character paths in order, prop paths in order.
- `image_jobs._shot_ref_paths` / `_first_frame_payload`: pass full ordered lists for sequential; stop dropping scene/prop images on multi-char shots.
- `text_fallbacks`: only for **existing** assets that lack an image for that layer.

### Deleted / unmatched scrub

- Storyboard match: only bind living assets; unmatched names → empty id, no ghost fallback text.
- `compile_first_frame` / `compile_shot_prompts`: never emit “无参考图槽，按文字绘制：…” for missing assets.
- On delete: existing detach + `refresh_shot_readiness(asset_id=…)` must rebuild prompts without that asset.
- Light scrub of `background` / `action` for exact deleted asset names when compiling after delete or when generating storyboard with a known deleted-name set (do not rewrite unrelated prose).

## Manual create asset

### API

`POST /api/projects/{project_id}/assets`

Body:

```json
{
  "kind": "character" | "scene" | "prop",
  "name": "string",
  "desc_zh": "string",
  "appearance": "string (optional, character)"
}
```

- Creates `Asset` only; returns serialized asset.
- 409 if same project + kind + name already exists.
- 400 on invalid kind / empty name or desc.

### UI

- Asset panel:「新增资产」→ kind + name + desc → POST.
- Merge into local bundle; reuse generate / upload / patch / delete.
- No new test runner on frontend (Playwright-only); cover API + compile/match in backend pytest.

## QA & failure

- Character adds: keep companion-delta style checks.
- Scene/prop stages: light “prior subjects still present / not destroyed” checks; do not require dual-skin peaks for N>2 as a hard pass gate.
- Retry within existing attempt budgets; escalate params per project quality rules; do not soft-accept failed QA.

## UI phase labels

Extend `jobPhaseLabel` for stages such as:

- `逐层叠加·场景`
- `逐层叠加·人物i/n·第a轮`
- `逐层叠加·道具j/m·第a轮`

## Out of scope

- Shot-card manual picker for scene/characters/props (name-match only this round).
- Auto T2I on asset create.
- Full rewrite to a generic LayerSpec engine.
- Inventing geometric standing slots beyond 左一/中/右一 for person ≥3.

## Primary touch points

| Area | Files (indicative) |
|------|-------------------|
| Sequential pipeline | `sequential_first_frame.py`, `edit_identity.py`, `seq_locks.py`, `image_worker.py` |
| Pack / refs / jobs | `domain/slots.py`, `image_jobs.py`, `domain/prompts.py` |
| Storyboard match / compile | `storyboard_ops.py`, `extract_prompts.py` |
| Create asset | `main.py`, `registry_ops.py` or `image_gen.py`, `frontend` `api.ts` + `App.tsx` |
| Tests | `test_slots.py`, `test_sequential_first_frame.py`, `test_edit_identity.py`, new create-asset / compile scrub tests |

## Success criteria

1. A shot with 1 scene + 5 characters + 2 props (all with images) generates a first frame via scene→5×person→2×prop sequential edits with no “max 8” / “scene text-only” shortcuts.
2. Deleting a matched asset and recompiling removes text-fallback and slot refs for that asset; first-frame prompt does not “按文字绘制” it.
3. Manual `POST` creates character/scene/prop; after images + storyboard regen, names bind and images enter the sequential stack.
4. Backend tests covering packing, sequential stage order, scrub-on-missing, and create-asset uniqueness.
