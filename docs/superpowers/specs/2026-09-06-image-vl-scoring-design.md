# Image VL Scoring UI — Design

**Date:** 2026-09-06  
**Status:** Approved for implementation (user OK)  
**Scope:** Optional one-click vision scoring of generated asset images and shot first frames.

## Goal

Let users optionally evaluate already-generated images against their generation prompts. Scores (0–100) and short comments appear next to each thumb / first frame, with page-level band counts. Delete or regenerate clears that slot back to「未评估」.

## Non-goals

- Automatic scoring on every generation (user must click).
- Changing Comfy generation / QA soft-accept behavior.
- Historical score history (latest score only).
- Scoring uploaded images without a stored generation prompt (use best-effort prompt from `build_field_prompt` / `prompt_zh`).

## Scoring engine

- **Model:** Ollama `qwen2.5vl:7b` via OpenAI-compatible `/v1/chat/completions` (default `http://127.0.0.1:11434/v1`).
- **Input:** image bytes (base64 data URL) + Chinese system/user prompt describing the intended generation brief for that slot.
- **Output:** strict JSON `{ "score": <int 0-100>, "comment": "<short Chinese evaluation>" }`.
- **Bands:**
  - `score > 80` → 较好 (green)
  - `60 <= score <= 80` → 一般 (yellow)
  - `score < 60` → 较差 (red)
  - missing / cleared → 未评估 (white / `--ink`)

Configurable via settings (e.g. `vision_llm_base_url`, `vision_llm_model`) with the above defaults.

## Data model

### Asset

Add `image_scores_json` (Text, default `{}`):

```json
{
  "full": { "score": 86, "comment": "…", "updated_at": "ISO8601" },
  "half": { "score": 55, "comment": "…", "updated_at": "…" },
  "far": { … },
  "near": { … },
  "image": { … }
}
```

Only keys with a current image path may hold a score. Serialize in `serialize_asset`.

### Shot

Add:

- `first_frame_score` (Integer, nullable)
- `first_frame_score_comment` (Text, default `""`)

Serialize in `serialize_shot` / project bundle.

### Reset rules

| Event | Action |
|-------|--------|
| `clear_asset_image(field)` | Remove that field key from `image_scores_json` |
| Enqueue regenerate for field / write new asset image | Clear that field’s score before/when writing |
| Write new `first_frame_path` | Clear `first_frame_score` + comment (set null/`""`); new score only after user re-runs评估 |
| Delete first frame (if added later) | Same clear |

Stats must recompute from live paths ∩ scores so counts stay consistent.

## APIs

### `POST /api/projects/{id}/score-images`

Body (optional filters):

```json
{
  "scope": "assets" | "shots" | "all",
  "kind": "character" | "scene" | "prop" | null
}
```

- Default for 全书资产 UI: `scope=assets` + current `kind`.
- Default for 分镜 UI: `scope=shots`.
- Enumerate existing image files only; skip empty paths.
- Run sequentially (or small concurrency) to avoid VRAM thrash with Comfy; release/avoid fighting Comfy if needed via existing supervisor patterns when practical.
- Persist each score as it completes; return summary counts + updated assets/shots slice or full bundle.

### `GET` via project bundle

No separate poll required if scoring is awaited in one request with a long timeout; if runtime is long, return `{ job_id }` + poll — prefer **sync with progress via image-jobs-like status** only if sync exceeds ~2 minutes in practice. Initial ship: **synchronous batch** with generous HTTP timeout; frontend shows busy state on the button.

## Frontend

### 全书资产 (`BookAssets`)

- Top bar: button「评估图片」+ summary chips  
  `较好：N；一般：N；较差：N；未评估：N`  
  Colors: green / yellow / red / white (`--ok` / `--warn` / `--danger` / `--ink`).
- Counts scoped to **current kind** and **existing image slots only**.
- Each `thumb-slot`: score badge to the **right** of the thumb (or trailing in the slot column). Hover → native `title` or tooltip with `comment`. Unscored →「未评估」in white/ink.
- **Scene layout:** near/far displayed as **two rows** (stacked), matching character full/half information hierarchy (each row: label + image + score). Character full/half may stay side-by-side or also stack if needed for visual consistency with「两行」— **scene must be two rows**; characters keep current dual-slot pattern unless stacking is required for alignment (prefer scene stacked rows first).

### 分镜

- Chapter/list header: same summary for first frames that exist.
- `ShotCard` first-frame block: score /「未评估」on the right; hover shows comment.

### Interactions

- Click「评估图片」→ call API for current scope → refresh project state → update badges and counts.
- Disable button while scoring; show short status text（评估中…）.

## Prompt brief sources

| Slot | Brief |
|------|--------|
| Asset field | `build_field_prompt(project, asset, field)` |
| First frame | `shot.prompt_zh` |

Evaluator instruction (summary): judge identity, costume/scene fidelity, composition vs brief, style consistency; ignore pure aesthetic preference; return JSON only.

## Testing

- Unit: score band helpers; JSON parse/clamp; clear-on-delete/regen.
- API test with mocked VL client returning fixed scores.
- Frontend: band counts from fixtures; badge class names; scene two-row layout smoke.

## Open follow-ups (out of this ship)

- Two-pass multi-character first-frame compose (separate from scoring).
- Background score job with SSE progress.
