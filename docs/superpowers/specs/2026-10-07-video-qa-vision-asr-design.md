# Video QA (Vision + ASR) — Design

**Date:** 2026-10-07  
**Status:** Approved for implementation (user OK: approach C + keyframes/ASR A + triggers C)  
**Scope:** Optional and post-generation video validation that compares rendered H3 clips (picture + sound) against the shot’s video prompt (`h3_prompt`), with scores/comments in the UI. Auto-regenerate is a config switch, default off.

## Goal

After a shot has `video_path`, let the system:

1. Sample key frames and score visual fidelity vs `h3_prompt` (identity, cast count, blocking, camera feel, no obvious identity collapse).
2. Extract audio and run local ASR; compare transcript to dialogue / narration implied by `h3_prompt`.
3. Persist an overall `video_score` (0–100) plus structured details and a short Chinese comment.
4. Trigger from: single shot, whole chapter, and automatically after a video job succeeds.
5. Optionally auto-requeue video generation when score is below threshold (default **disabled**).

## Non-goals

- Replacing MiniMax H3 generation QA inside Comfy (this is post-hoc product QA).
- Cloud-only multimodal “send whole mp4” APIs as the primary path.
- Perfect lip-sync / frame-accurate dialogue timing audit.
- Scoring videos that have no `video_path` or empty `h3_prompt`.
- Historical score history (latest score only, same as image VL scoring).

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| Result use | Score + comment first; auto-regen behind switch |
| Media coverage | Keyframes (vision) + local ASR (speech) |
| Triggers | Chapter button + per-shot button + auto after video success |
| Visual model | Existing `vision_llm_*` (`qwen2.5vl:7b` default) |
| ASR | Local Whisper-compatible stack (prefer `faster-whisper` if available; fallback documented) |
| Auto-regen default | Off (`N2L_VIDEO_QA_AUTO_REGEN=false`) |

## Pipeline

Per shot with `video_path` + `h3_prompt`:

```
video.mp4
  ├─ ffmpeg: extract N keyframes (default 4: t=10%, 35%, 60%, 85%)
  │    └─ vision LLM: score each frame vs h3_prompt → visual_score (mean), visual_notes
  └─ ffmpeg: extract mono wav 16kHz
       └─ ASR → transcript
            └─ compare to expected speech from h3_prompt → audio_score, audio_notes
  └─ combine → video_score + video_score_comment + video_qa_json
```

### Expected speech extraction

Parse from `h3_prompt` (and `lines_json` / `narration` when present):

- Quoted dialogue after `说道：「…」`
- `旁白（画外音）：…` when not `无`
- `画外口播：「…」`

If **no expected speech**:

- Audio weight flips to a silence check: speech detected → penalty; near-silence → pass.

If **expected speech**:

- Rough Chinese similarity (normalize punctuation/whitespace; containment / token overlap). Perfect ASR not required; clear foreign-language or empty transcript when dialogue was required → low audio_score.

### Scoring

- **Bands** (same as image scoring): `>80` 较好, `60–80` 一般, `<60` 较差, missing 未评估.
- **Default weights:** visual 0.6, audio 0.4 when speech expected; when silent shot expected, visual 0.75 + silence-check 0.25.
- **Combined comment:** 1–2 Chinese sentences summarizing worst gap (e.g. “画面人数对，但听写无对白”).

### Keyframe / ffmpeg requirements

- Use system `ffmpeg` / `ffprobe` (document PATH requirement).
- Work dir: `data/projects/{pid}/shots/{sid}/_video_qa/` (ephemeral; safe to delete after score write).
- Fail soft: if ASR unavailable, still write visual_score and mark `audio: skipped` with overall score = visual-only (comment notes ASR skipped). Do not fake a high audio score.

## Data model

### Shot columns

| Column | Type | Meaning |
|--------|------|---------|
| `video_score` | Integer nullable | Combined 0–100 |
| `video_score_comment` | Text default `""` | Short Chinese summary |
| `video_qa_json` | Text default `"{}"` | Structured details |

`video_qa_json` shape:

```json
{
  "visual_score": 72,
  "audio_score": 40,
  "weights": { "visual": 0.6, "audio": 0.4 },
  "expected_speech": ["请问，是陈守义老伯吗？"],
  "transcript": "…",
  "speech_expected": true,
  "frames": [{"t": 0.6, "score": 70, "comment": "…"}],
  "issues": ["dialogue_mismatch", "possible_foreign_speech"],
  "updated_at": "ISO8601",
  "model_vision": "qwen2.5vl:7b",
  "model_asr": "faster-whisper-base"
}
```

Serialize on `serialize_shot` alongside existing `first_frame_score*`.

### Reset rules

| Event | Action |
|-------|--------|
| Enqueue / write new `video_path` | Clear `video_score`, comment, `video_qa_json` |
| Delete video (if added later) | Same clear |
| Manual re-score | Overwrite latest |

## Config

| Setting | Default | Purpose |
|---------|---------|---------|
| `vision_llm_base_url` / `vision_llm_model` | existing | Frame scoring |
| `video_qa_frame_count` | `4` | Keyframes |
| `video_qa_asr_model` | `base` | Whisper size |
| `video_qa_asr_device` | `cpu` | Device hint |
| `video_qa_auto_after_video` | `true` | Auto score when video job succeeds |
| `video_qa_auto_regen` | `false` | Requeue video if score &lt; threshold |
| `video_qa_regen_threshold` | `60` | Only used when auto_regen on |
| `video_qa_max_regen` | `1` | Cap auto regen loops per shot write |

Env prefix remains `N2L_`.

## APIs

### `POST /api/projects/{id}/score-videos`

```json
{
  "scope": "shot" | "chapter" | "project",
  "shot_id": "…",
  "chapter_id": "…"
}
```

- Requires video present; skips missing with `skipped` reasons (mirror image scoring).
- Returns project bundle + `{ scored, errors, skipped, cancelled }`.
- Block or queue politely when image/video workers are saturating GPU if needed (prefer: run ASR/ffmpeg on CPU; vision LLM same gate as `score-images`).

### `POST /api/projects/{id}/shots/{shot_id}/score-video`

Convenience wrapper for single shot (`scope=shot`).

## Worker integration

In `VideoWorker` after successful copy to `video_path`:

1. Clear prior video score fields (already cleared on enqueue).
2. If `video_qa_auto_after_video`: schedule async score (thread/asyncio task via existing session factory pattern, or enqueue a lightweight `VideoQaJob` table if we need durability).

**Durability preference (v1):** fire-and-forget background task on the API process (same as image score request handling), with try/except logged. If process dies mid-score, UI shows 未评估 and user can click 评估.

**Auto-regen (only if enabled):** after score &lt; threshold and regen count &lt; max, call `enqueue_shot_video(..., overwrite=True)` and bump a counter in `video_qa_json.regen_count`.

## UI

- Shot card: badge for `video_score` (reuse band chips); tooltip = comment; expand/detail optional later from `video_qa_json` (transcript snippet).
- Chapter toolbar: **评估本章视频** next to **生成本章视频** / **评估图片**.
- Per-shot: **评估视频** when `video_path` set.
- Score summary strip for chapter videos (good/ok/bad/none), parallel to first-frame summary.
- Settings/advanced (optional v1.1): checkbox “低分自动重生成视频” bound to project or global config — v1 may expose only via env to keep UI small.

## Module layout

- `app/video_qa.py` — ffmpeg helpers, ASR wrapper, expected-speech parse, combine scores.
- `app/video_scores.py` or extend `image_scores.py` with video entrypoints — prefer **`app/video_scores.py`** to avoid bloating image module.
- Tests: unit tests for speech extraction, silent-shot weighting, combine formula; fake vision/ASR in API tests; no real GPU required.

## Test plan

1. Unit: extract expected speech from sample `h3_prompt` (dialogue + 画外口播 + silent).
2. Unit: combine scores for speech / silent cases.
3. API: score one shot with monkeypatched vision+ASR → persists `video_score` / json; regenerate video clears score.
4. Worker: success path schedules auto-score when flag true (mock).
5. Manual: one V12 shot with dialogue + one silent atmosphere shot.

## Risks / mitigations

| Risk | Mitigation |
|------|------------|
| ASR quality on noisy H3 audio | Fuzzy match; low confidence → comment, not hard fail unless empty vs required dialogue |
| Vision model slow for 126 shots | Chapter job is sequential; show progress via existing busy/notice patterns |
| ffmpeg missing | Clear error in `errors[]`; do not crash worker |
| Auto-regen loops | `video_qa_max_regen` + default off |

## Implementation order

1. DB columns + serialize + clear-on-video-write.
2. `video_qa` core (ffmpeg, parse speech, combine) + unit tests.
3. Vision+ASR scoring functions + `score-videos` API.
4. UI badges + chapter/shot buttons.
5. Auto-after-video hook + auto-regen flag (default false).
