# Require Asset Images for Storyboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Block storyboard generation until every book asset has its required reference image(s).

**Architecture:** Shared readiness rules on backend (`require_asset_images`) and frontend (`bookAssetsReady` / `assetRefReady`). UI disables the CTA; API raises `ValueError` → HTTP 409. No change to slot packing or prompt wording.

**Tech Stack:** FastAPI, SQLAlchemy Asset model, React + TypeScript (`flow.ts`), pytest, existing TestClient patterns.

## Global Constraints

- Character: confirmed **and** `half_path` **and** `full_path`
- Scene: any of `near_path` / `far_path` / `image_path`
- Prop: `image_path`
- Empty scene/prop lists pass vacuously; still require ≥1 confirmed character
- Error message in Chinese, clear enough for UI toast

---

### Task 1: Backend readiness helper + storyboard gate

**Files:**
- Create: `backend/tests/test_asset_image_gate.py`
- Modify: `backend/app/services.py` (add helpers near `scene_image_path` usage; call from `generate_storyboard`)
- Modify: `backend/tests/test_api.py` (upload images before storyboard)

**Interfaces:**
- Produces: `def asset_ref_ready(asset: Asset) -> bool`
- Produces: `def missing_asset_image_messages(assets: list[Asset]) -> list[str]`
- Produces: `def require_asset_images(assets: list[Asset]) -> None` — raises `ValueError` if any message
- Consumes: `scene_image_path`, `normalize_kind`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_asset_image_gate.py
from app.db import Asset
from app.services import asset_ref_ready, missing_asset_image_messages, require_asset_images


def _a(**kw):
    defaults = dict(
        id="x", project_id="p", kind="character", name="林砚之",
        half_path="", full_path="", image_path="", far_path="", near_path="",
        confirmed=True, desc_zh="", desc_en="",
    )
    defaults.update(kw)
    return Asset(**{k: v for k, v in defaults.items() if k in Asset.__table__.columns.keys() or True})
    # Prefer constructing via ORM columns only — match existing test helpers in test_shot_refs / test_image_worker.


def test_asset_ref_ready_rules():
    assert asset_ref_ready(Asset(id="1", project_id="p", kind="character", name="a", half_path="h", full_path="f"))
    assert not asset_ref_ready(Asset(id="2", project_id="p", kind="character", name="a", half_path="h", full_path=""))
    assert asset_ref_ready(Asset(id="3", project_id="p", kind="scene", name="s", near_path="n"))
    assert asset_ref_ready(Asset(id="4", project_id="p", kind="scene", name="s", far_path="f"))
    assert not asset_ref_ready(Asset(id="5", project_id="p", kind="scene", name="s"))
    assert asset_ref_ready(Asset(id="6", project_id="p", kind="prop", name="p", image_path="i"))
    assert not asset_ref_ready(Asset(id="7", project_id="p", kind="prop", name="p"))


def test_require_asset_images_raises_chinese():
    assets = [
        Asset(id="1", project_id="p", kind="character", name="林砚之", half_path="", full_path="", confirmed=True),
        Asset(id="2", project_id="p", kind="scene", name="渡口", near_path="", far_path="", image_path=""),
        Asset(id="3", project_id="p", kind="prop", name="玉佩", image_path=""),
    ]
    msgs = missing_asset_image_messages(assets)
    assert any("林砚之" in m for m in msgs)
    assert any("渡口" in m for m in msgs)
    assert any("玉佩" in m for m in msgs)
    try:
        require_asset_images(assets)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "参考图未齐备" in str(e)
```

Use a minimal Asset construction pattern that matches the repo (copy from `test_shot_refs._A` if needed). Fill required NOT NULL columns with defaults (`""`, `False`, `0`).

- [ ] **Step 2: Run tests — expect FAIL** (import / missing symbols)

```bash
cd backend && uv run pytest tests/test_asset_image_gate.py -q
```

- [ ] **Step 3: Implement helpers in `services.py`**

```python
def asset_ref_ready(asset: Asset) -> bool:
    kind = normalize_kind(asset.kind)
    if kind == "character":
        return bool((asset.half_path or "").strip() and (asset.full_path or "").strip())
    if kind == "scene":
        return bool(scene_image_path(asset))
    if kind == "prop":
        return bool((asset.image_path or "").strip())
    return True


def missing_asset_image_messages(assets: list[Asset]) -> list[str]:
    out: list[str] = []
    for a in assets:
        kind = normalize_kind(a.kind)
        if kind == "character" and not asset_ref_ready(a):
            out.append(f"人物「{a.name}」缺半身或全身图")
        elif kind == "scene" and not asset_ref_ready(a):
            out.append(f"场景「{a.name}」缺参考图")
        elif kind == "prop" and not asset_ref_ready(a):
            out.append(f"物品「{a.name}」缺参考图")
    return out


def require_asset_images(assets: list[Asset]) -> None:
    msgs = missing_asset_image_messages(assets)
    if msgs:
        raise ValueError("参考图未齐备，无法生成分镜：" + "；".join(msgs[:12]))
```

In `generate_storyboard`, after loading `assets` and existing book_ready check, call:

```python
require_asset_images(assets)
```

- [ ] **Step 4: Fix `test_api.py` pipeline** — upload character half/full, scene image, and prop image **before** `POST .../storyboard`.

- [ ] **Step 5: Add API rejection test** in `test_asset_image_gate.py` or `test_api.py`: generate assets → storyboard without upload → status 409 and detail contains `参考图未齐备`.

- [ ] **Step 6: Run tests**

```bash
cd backend && uv run pytest tests/test_asset_image_gate.py tests/test_api.py -q
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/services.py backend/tests/test_asset_image_gate.py backend/tests/test_api.py
git commit -m "Reject storyboard when any book asset is missing reference images."
```

---

### Task 2: Frontend gate + flow copy

**Files:**
- Modify: `frontend/src/flow.ts`
- Create: `frontend/src/flow.test.ts` (if vitest exists) **or** skip unit file and rely on TypeScript + e2e — check `package.json` for vitest; if no unit runner, export helpers and keep logic thin without new test harness.
- Modify: `frontend/src/App.tsx` only if button uses a second check beyond `bookAssetsReady` (prefer extending `bookAssetsReady` only).

**Interfaces:**
- Produces: `export function assetRefReady(a: Asset): boolean`
- Updates: `bookAssetsReady` to require confirmed characters **and** every asset `assetRefReady`

- [ ] **Step 1: Update `flow.ts`**

```typescript
export function assetRefReady(a: Asset): boolean {
  const kind = normalizeKind(a.kind);
  if (kind === "character") return Boolean(a.half_path && a.full_path);
  if (kind === "scene") return Boolean(a.near_path || a.far_path || a.image_path);
  if (kind === "prop") return Boolean(a.image_path);
  return true;
}

export function bookAssetsReady(bundle: Bundle): boolean {
  const chars = bundle.assets.filter((a) => normalizeKind(a.kind) === "character");
  if (!(chars.length > 0 && chars.every((a) => a.confirmed))) return false;
  return bundle.assets.every(assetRefReady);
}
```

Update upload guide tip (~line 88–96):

- title: `第 3 步 · 补齐参考图（必须）`
- tip: `还有 ${missing} 个全书资产缺图。人物需半身+全身，场景/物品各至少一张。缺图禁止生成分镜。`
- Keep `missingRefCount` as-is (already matches rules).

- [ ] **Step 2: Verify storyboard button already uses `bookAssetsReady(bundle)`** — no App.tsx change unless a second entry point bypasses it (`onRun` storyboard around line 196). Ensure that path also respects readiness (disable or early return).

- [ ] **Step 3: Frontend typecheck**

```bash
cd frontend && npm run build
```

- [ ] **Step 4: Commit + push**

```bash
git add frontend/src/flow.ts frontend/src/App.tsx
git commit -m "Require all asset reference images before enabling storyboard."
git push
```

---

## Spec coverage

| Spec item | Task |
|-----------|------|
| Character half+full | 1 + 2 |
| Scene any path | 1 + 2 |
| Prop image | 1 + 2 |
| Frontend disable | 2 (`bookAssetsReady`) |
| Backend reject | 1 (`require_asset_images`) |
| Mandatory upload copy | 2 |
| Vacuous empty scene/prop | 1 + 2 (`every` on empty kinds still true if no such assets) |
| Tests | 1 |

## Self-review

- No optional-image / text-fallback tasks (explicit non-goal).
- `test_api` reorder required so pipeline still green.
- Image-worker 409 test posts storyboard while job queued — still 409 for busy; may also hit image gate if assets lack paths — `_seed_project` must leave paths empty; busy check runs first in `api_storyboard` via `_reject_if_image_busy` — OK.
