# Asset Image Gen via 造像 — Implementation Plan

> **For agentic workers:** Implement task-by-task. Steps use checkbox syntax.

**Goal:** One-click and per-asset image generation through 造像 API, with configurable save dir and start-script integration.

**Architecture:** novel2Lens backend owns a Zaoxiang HTTP client + asset image service; frontend triggers generate-all / regenerate / delete; start.ps1 launches aiImage.

**Tech Stack:** FastAPI, httpx, React, PowerShell start scripts, 造像 `:8000`.

## Global Constraints

- Half-body aspect **3:4**; full **9:16**; scene **16:9**; prop **1:1**.
- Do not commit `data/` or secrets.
- Commit+push after code changes when network allows.

---

### Task 1: Zaoxiang client + settings

- [ ] Add `zaoxiang_base_url`, `image_output_dir` on Project (+ ensure_schema / defaults).
- [ ] Implement `backend/app/zaoxiang_client.py` (generate, edit, poll, download bytes).
- [ ] Unit-test client with httpx mock.

### Task 2: Asset image generation service + API

- [ ] `generate_asset_images` / `clear_asset_image` / `generate_all_book_images`.
- [ ] Routes: POST generate-images (all), POST assets/{id}/generate, DELETE assets/{id}/image?field=, PATCH project image_output_dir.
- [ ] Tests with mocked Zaoxiang.

### Task 3: Frontend book-assets UI

- [ ] Output dir setting + 一键生成参考图 + per-slot 删除/上传/重生成.
- [ ] Progress/busy text.

### Task 4: Start scripts

- [ ] `start.ps1` starts `D:\Develop\aiImage\scripts\start.ps1` and waits for health.
- [ ] Keep `start.bat` wrapper.

### Task 5: Verify + commit

- [ ] pytest green; commit; push if possible.
