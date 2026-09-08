# Sequential Unlimited First Frames Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stack first frames as scene → each character → each prop with no people cap; omit text stand-ins for deleted/unmatched assets; add manual asset create (character/scene/prop).

**Architecture:** Extend `pack_qwen_slots` + `sequential_first_frame` + `_shot_ref_paths`; split slots vs text_fallbacks by image presence at compile time; add `POST /assets` + UI button.

**Tech Stack:** FastAPI, SQLAlchemy, React/Vite, pytest

## Global Constraints

- Stack order: scene → characters → props
- No hard named-character cap
- Deleted/unmatched: no “按文字绘制” stand-in
- Existing asset without image: text fallback allowed
- Manual create: row only, no auto T2I; storyboard name-match attaches
- Qwen ≤3 images per edit call

## File map

| File | Role |
|------|------|
| `backend/app/domain/slots.py` | Unlimited pack; order scene→chars→props |
| `backend/app/storyboard_ops.py` | Image-aware split; scrub; no `named[:cap]`; repair heuristic |
| `backend/app/domain/prompts.py` | CN_NUM; skip empty fallbacks; natural standing |
| `backend/app/image_jobs.py` | Ordered refs including scene/prop |
| `backend/app/sequential_first_frame.py` | Layered sequential runner |
| `backend/app/domain/edit_identity.py` | Scene/prop wraps |
| `backend/app/image_worker.py` | Route first_frame to layered sequential |
| `backend/app/extract_prompts.py` | SHOT_SYSTEM unlimited |
| `backend/app/main.py` + create helper | `POST /assets` |
| `frontend/src/api.ts`, `App.tsx` | createAsset +「新增资产」 |
| Tests | slots, prompts, sequential, create asset |

---

### Task 1: Pack slots unlimited + scene/prop included

**Files:** `backend/app/domain/slots.py`, `backend/tests/test_slots.py`

- [ ] Rewrite tests: dual-char keeps scene+prop as **slots** (order scene, chars, props); nine characters allowed; remove reject-nine / cap==8 assertions
- [ ] Implement: remove raise on >8; drop early_text_fallbacks for multi-char; order scene → characters → props; no slot count hard cap (all become slots; image-aware split happens in compile)
- [ ] `max_named_characters` return a large soft hint (e.g. 99) for LLM UI only, or unused
- [ ] Commit

### Task 2: Compile: image-aware fallbacks + scrub + storyboard

**Files:** `backend/app/storyboard_ops.py`, `backend/app/domain/prompts.py`, `backend/tests/test_prompts.py`, new `backend/tests/test_compile_scrub.py`

- [ ] After pack, move subjects without image paths to `text_fallbacks` (with desc); keep those with images as slots; reindex slots
- [ ] Scrub `background`/`action` for exact deleted names when assets missing from by_id (lines already skip missing)
- [ ] Remove `named[:cap]` in `generate_storyboard`; assign positions 左一/中/右一 for first 3, `自然站位` for rest
- [ ] Fix `shot_needs_portrait_repair`: do not treat `len(slots)>3` or leading scene as always broken
- [ ] Extend `CN_NUM`; `_fallback_*` skip when `text` empty; `_slot_zh` handles `自然站位`
- [ ] Commit

### Task 3: Ref paths + sequential layered generation

**Files:** `image_jobs.py`, `edit_identity.py`, `sequential_first_frame.py`, `image_worker.py`, tests

- [ ] `_shot_ref_paths`: order scene, characters, props; never skip scene/prop for multi-char; no 8-break
- [ ] Payload: `layer_scene`, `layer_people`, `layer_props` counts optional via labels
- [ ] Add `wrap_sequential_apply_scene`, `wrap_sequential_place_on_scene`, `wrap_sequential_add_prop`
- [ ] Rewrite runner: scene stage → people (existing) → props; allow people_n >= 1 when scene/props present; people_n>=2 alone still works
- [ ] Worker: first_frame + (scene or props or people>=2 or total_layers>=2) → layered sequential
- [ ] Phase labels in frontend `jobPhaseLabel`
- [ ] Commit

### Task 4: Manual create asset API + UI

**Files:** `main.py`, create helper, `api.ts`, `App.tsx`, `backend/tests/test_create_asset.py`

- [ ] `POST /api/projects/{id}/assets` with kind/name/desc_zh/appearance; 409 duplicate name+kind
- [ ] Frontend form「新增资产」
- [ ] Commit

### Task 5: SHOT_SYSTEM + full pytest

- [ ] Update `SHOT_SYSTEM` (no 3-person / 3-ref hard rules; match living assets only)
- [ ] `pytest` green; frontend build
- [ ] Push

---

**Spec coverage:** unlimited chars ✓; scene→person→prop ✓; deleted no text ✓; create asset ✓; name-match (existing) ✓
