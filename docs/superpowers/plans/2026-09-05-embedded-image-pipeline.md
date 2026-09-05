# Embedded Image Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Embed ComfyUI text-to-image and image-edit inside novel2Lens with a serial durable job queue, hard LLM↔image mutex, on-demand Comfy with 3‑minute idle unload, and a 青渡川 end-to-end API test that simulates the frontend flow (create → import → assets → storyboard → one-click images) on **real GPU** (no FakeComfy for that flow).

**Architecture:** Copy/adapt aiImage’s Comfy client + workflow compilers into `backend/app/comfy_pipeline/`. Persist `image_jobs` in SQLite; a single background `ImageWorker` runs jobs FIFO. `ComfySupervisor` starts Comfy only when needed and `/free` (+ optional process stop) after 180s idle. `LlmSupervisor` stops Flash-Next while image jobs are active and LLM routes return 409. Frontend polls active jobs / phases. No aiImage `:8000`.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, httpx, Pillow, React/Vite, PowerShell, external ComfyUI at `D:\Develop\ComfyUI` (`:8189`), Flash-Next via `start-llm.ps1`.

## Global Constraints

- Aspects: character full **9:16**, half **3:4**; scene far **16:9**, near **3:4**; prop **1:1**.
- Global Comfy concurrency **1**; one-click enqueues **all t2i then all edit**.
- Idle unload after **180** seconds with no queued/running image jobs; default **stop Comfy process** when idle.
- Hard mutex: any queued/running image job → LLM APIs **409**; stop llama-server before image work.
- Results write asset slots immediately (no confirm UI). Manual edit ≤3 refs; file picker lists `image_output_dir`.
- Do not commit `data/` or secrets; commit+push after each task when network allows.
- Spec: `docs/superpowers/specs/2026-09-05-embedded-image-pipeline-design.md`.

## File map

| Path | Responsibility |
|------|----------------|
| `backend/workflows/*.json` | Copied Comfy API workflows (sdxl / ideogram / qwen edit) |
| `backend/app/comfy_pipeline/comfy.py` | `ComfyClient` |
| `backend/app/comfy_pipeline/workflows.py` | compile + style/backend pick |
| `backend/app/comfy_pipeline/character_prompt.py` | character enrich |
| `backend/app/comfy_pipeline/ideogram_prompt.py` | scenery captions |
| `backend/app/comfy_pipeline/qa.py` | light QA (optional pass-through first) |
| `backend/app/comfy_supervisor.py` | start/stop Comfy process, health, idle unload |
| `backend/app/llm_supervisor.py` | stop/start Flash-Next, `image_busy` gate |
| `backend/app/image_jobs.py` | ORM helpers: create/list/cancel/next |
| `backend/app/image_worker.py` | serial worker loop + phase tags |
| `backend/app/image_gen.py` | enqueue one-click / one-slot / manual edit; path writes |
| `backend/app/db.py` | `ImageJob`, `far_path`/`near_path`, settings |
| `backend/app/config.py` | comfy paths, idle seconds |
| `backend/app/main.py` | job APIs, LLM 409 gate, lifespan worker |
| `backend/app/domain/shot_refs.py` + readiness | scene near/far |
| `frontend/src/api.ts` + `App.tsx` + `styles.css` | queue UI, phases, edit panel, scene slots |
| `start.ps1` | no 造像 / no Comfy / no LLM by default |
| `backend/tests/test_image_worker.py` | serial, order, free, 409, idle |
| `backend/scripts/e2e_qingduchuan_flow.py` | 青渡川 full flow: real LLM + real Comfy GPU |
| `backend/tests/test_e2e_qingduchuan_flow_gpu.py` | Optional `@pytest.mark.gpu` wrapper (not in default CI) |

---

### Task 1: Copy Comfy pipeline modules + workflows

**Files:**
- Create: `backend/workflows/sdxl_t2i_api_v1.json` (copy from `D:\Develop\aiImage\workflows\`)
- Create: `backend/workflows/ideogram4_t2i_api_v1.json`
- Create: `backend/workflows/qwen_image_edit_2511_api_v1.json`
- Create: `backend/app/comfy_pipeline/__init__.py`
- Create: `backend/app/comfy_pipeline/comfy.py` (adapt from aiImage `zaoxiang/comfy.py`)
- Create: `backend/app/comfy_pipeline/workflows.py`, `character_prompt.py`, `ideogram_prompt.py`, `qa.py`
- Test: `backend/tests/test_comfy_workflows_compile.py`

**Interfaces:**
- Produces: `ComfyClient(base_url)`, `compile_sdxl_t2i(...)`, `compile_ideogram_t2i(...)`, `compile_qwen_edit(...)`, `pick_t2i_backend(...)`, `resolve_size(aspect)`, `free_memory()` on client

- [ ] **Step 1: Copy the three workflow JSON files into `backend/workflows/`**

```powershell
New-Item -ItemType Directory -Force D:\Develop\novel2Lens\backend\workflows | Out-Null
Copy-Item D:\Develop\aiImage\workflows\sdxl_t2i_api_v1.json D:\Develop\novel2Lens\backend\workflows\
Copy-Item D:\Develop\aiImage\workflows\ideogram4_t2i_api_v1.json D:\Develop\novel2Lens\backend\workflows\
Copy-Item D:\Develop\aiImage\workflows\qwen_image_edit_2511_api_v1.json D:\Develop\novel2Lens\backend\workflows\
```

- [ ] **Step 2: Write failing compile test**

```python
# backend/tests/test_comfy_workflows_compile.py
from app.comfy_pipeline.workflows import compile_sdxl_t2i, resolve_size

def test_resolve_size_half_and_far():
    assert resolve_size("3:4")[0] < resolve_size("3:4")[1] or resolve_size("3:4") == (768, 1024)
    w, h = resolve_size("16:9")
    assert w > h

def test_compile_sdxl_returns_prompt_dict():
    graph = compile_sdxl_t2i(
        prompt="test character full body",
        negative="",
        width=704,
        height=1472,
        steps=20,
        cfg=5.0,
        seed=1,
        ckpt="RealVisXL_V5.0_fp16.safetensors",
    )
    assert isinstance(graph, dict)
    assert len(graph) >= 3
```

- [ ] **Step 3: Run test — expect FAIL (module missing)**

Run: `cd D:\Develop\novel2Lens\backend && uv run pytest tests/test_comfy_workflows_compile.py -v`  
Expected: `ModuleNotFoundError` or import error

- [ ] **Step 4: Port comfy + workflows from aiImage**

Copy `comfy.py` almost verbatim. Port `workflows.py` / `character_prompt.py` / `ideogram_prompt.py`; set workflow JSON root to `Path(__file__).resolve().parents[2] / "workflows"`. Keep `qa.assess_image_bytes` as soft-pass (`return {"ok": True}`) if full QA deps are heavy — note in module docstring.

- [ ] **Step 5: Run test — expect PASS**

- [ ] **Step 6: Commit**

```bash
git add backend/workflows backend/app/comfy_pipeline backend/tests/test_comfy_workflows_compile.py
git commit -m "Add embedded Comfy workflow compilers copied from 造像."
```

---

### Task 2: DB — ImageJob, far/near paths, config

**Files:**
- Modify: `backend/app/db.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/services.py` (`serialize_asset`, readiness helpers)
- Test: `backend/tests/test_image_job_schema.py`

**Interfaces:**
- Produces: `ImageJob` model; `Asset.far_path`, `Asset.near_path`; settings `comfy_base_url`, `comfy_root`, `image_idle_unload_seconds=180`, `stop_comfy_when_idle=True`; `ensure_schema` migrations

- [ ] **Step 1: Failing test for columns / job row**

```python
def test_image_job_and_scene_paths(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    from app.db import Asset, ImageJob, Project, reset_engine, SessionLocal, ensure_schema
    reset_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    db = SessionLocal()
    p = Project(id="p1", title="t", style="", source_text="x")
    db.add(p)
    a = Asset(id="a1", project_id="p1", kind="scene", name="渡口", far_path="", near_path="")
    db.add(a)
    j = ImageJob(
        id="j1", project_id="p1", asset_id="a1", kind="t2i",
        target_field="far", status="queued", phase="", prompt="fog pier",
        payload_json="{}", batch_id="b1", error="",
    )
    db.add(j)
    db.commit()
    row = db.get(ImageJob, "j1")
    assert row.status == "queued"
    assert hasattr(db.get(Asset, "a1"), "far_path")
```

- [ ] **Step 2: Run — FAIL until model exists**

- [ ] **Step 3: Implement schema**

Add to `db.py`:

```python
class ImageJob(Base):
    __tablename__ = "image_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    asset_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # t2i | edit
    target_field: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    phase: Mapped[str] = mapped_column(String(40), default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    batch_id: Mapped[str] = mapped_column(String(36), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
```

Add `far_path`, `near_path` on `Asset`. In `ensure_schema`, `ALTER TABLE` if missing. Config:

```python
comfy_base_url: str = "http://127.0.0.1:8189"
comfy_root: str = r"D:\Develop\ComfyUI"
comfy_python: str = r"D:\Develop\ComfyUI\venv\Scripts\python.exe"
image_idle_unload_seconds: int = 180
stop_comfy_when_idle: bool = True
```

Serialize `far_path`/`near_path` in `serialize_asset`. Legacy: if `image_path` set and `far_path` empty, treat `far_path = image_path` when reading for display/refs.

- [ ] **Step 4: PASS + commit**

```bash
git commit -m "Add image_jobs table and scene far/near asset paths."
```

---

### Task 3: ComfySupervisor + LlmSupervisor

**Files:**
- Create: `backend/app/comfy_supervisor.py`
- Create: `backend/app/llm_supervisor.py`
- Test: `backend/tests/test_supervisors.py`

**Interfaces:**
- Produces:
  - `ComfySupervisor.ensure_running() -> None`
  - `ComfySupervisor.free_models() -> None`
  - `ComfySupervisor.note_activity() -> None`
  - `ComfySupervisor.tick_idle() -> None`  # call from worker loop
  - `LlmSupervisor.stop_llm() -> None`
  - `LlmSupervisor.ensure_llm() -> None`  # lazy start for text routes
  - `LlmSupervisor.set_image_busy(busy: bool) -> None`
  - `LlmSupervisor.image_busy -> bool`

- [ ] **Step 1: Failing tests**

```python
def test_llm_blocks_when_image_busy():
    from app.llm_supervisor import LlmSupervisor
    s = LlmSupervisor(stop_cmd=lambda: None, start_cmd=lambda: None)
    s.set_image_busy(True)
    assert s.image_busy is True

def test_idle_unload_calls_free(monkeypatch):
    calls = []
    from app.comfy_supervisor import ComfySupervisor
    sup = ComfySupervisor(
        base_url="http://127.0.0.1:8189",
        root=r"D:\Develop\ComfyUI",
        python=r"D:\Develop\ComfyUI\venv\Scripts\python.exe",
        idle_seconds=1,
        stop_when_idle=False,
        client_factory=lambda url: type("C", (), {"health": lambda self: {"ok": True}, "free_memory": lambda self: calls.append("free")})(),
        start_process=lambda: None,
        stop_process=lambda: None,
        is_up=lambda: True,
    )
    sup.note_activity()
    import time; time.sleep(1.2)
    sup.tick_idle(has_active_jobs=False)
    assert "free" in calls
```

- [ ] **Step 2: Implement supervisors**

`ComfySupervisor.ensure_running`: if health not ok, `Start-Process` equivalent via `subprocess.Popen` launching Comfy main.py on 8189 (mirror aiImage start.ps1 args: `--port 8189`). Wait up to 180s.

`LlmSupervisor.stop_llm`: kill listeners on port **8080** (same idea as stop port in aiImage script) or PID file if `start-llm.ps1` writes one — prefer port-based kill of `llama-server`.

- [ ] **Step 3: PASS + commit**

```bash
git commit -m "Add Comfy and LLM supervisors for on-demand load and hard mutex."
```

---

### Task 4: ImageWorker + enqueue API surface

**Files:**
- Create: `backend/app/image_jobs.py`
- Create: `backend/app/image_worker.py`
- Rewrite: `backend/app/image_gen.py` (enqueue, not sync zaoxiang)
- Modify: `backend/app/main.py` (routes + lifespan + LLM 409)
- Delete or gut: `backend/app/zaoxiang_client.py` (remove imports)
- Test: `backend/tests/test_image_worker.py`

**Interfaces:**
- Produces:
  - `enqueue_one_click(db, project) -> dict` with `batch_id`, `job_ids`
  - `enqueue_asset_field(db, project, asset, field) -> ImageJob`
  - `enqueue_manual_edit(db, project, asset, *, target_field, prompt, ref_paths: list[str], aspect) -> ImageJob`
  - `list_active_jobs(db, project_id) -> list[dict]`
  - `cancel_batch(db, batch_id) -> int`
  - Worker phases: `ensuring_comfy` | `loading_t2i` | `loading_edit` | `generating`

- [ ] **Step 1: Failing tests (FakeComfy)**

```python
def test_one_click_orders_t2i_before_edit(tmp_path, monkeypatch):
    # seed project with 1 character + 1 scene + 1 prop
    # monkeypatch worker ComfyClient to Fake that writes tiny PNG bytes
    # call enqueue_one_click; start worker briefly OR run drain_once()
    jobs = db.query(ImageJob).order_by(ImageJob.created_at).all()
    kinds = [j.kind for j in jobs]
    assert kinds == ["t2i", "t2i", "t2i", "edit", "edit"]  # full, far, prop, half, near
    assert all(j.target_field for j in jobs)

def test_llm_route_409_while_job_queued(tmp_path, monkeypatch):
    # create queued job; POST storyboard or extract → 409
    ...

def test_worker_serial_never_two_running():
    # FakeComfy.sleep; assert max concurrent running observed == 1
    ...
```

- [ ] **Step 2: Implement `image_jobs.py` helpers + worker**

Worker loop sketch:

```python
def _run_job(self, job: ImageJob) -> None:
    self.llm.set_image_busy(True)
    self.llm.stop_llm()
    job.phase = "ensuring_comfy"; self._save(job)
    self.comfy.ensure_running()
    if job.kind == "t2i":
        if self._last_kind == "edit":
            self.comfy.client.free_memory()
        job.phase = "loading_t2i"; self._save(job)
        # compile + queue_prompt + wait + save PNG to asset field
        job.phase = "generating"; self._save(job)
    else:
        if self._last_kind == "t2i":
            self.comfy.client.free_memory()
        job.phase = "loading_edit"; self._save(job)
        # upload refs, compile_qwen_edit, ...
        job.phase = "generating"; self._save(job)
    job.status = "succeeded"; job.phase = ""
    self._last_kind = job.kind
    self.comfy.note_activity()
```

One-click enqueue order:

1. Each character → t2i `full` 9:16  
2. Each scene → t2i `far` 16:9  
3. Each prop → t2i `image` 1:1  
4. Each character → edit `half` 3:4 (ref=full)  
5. Each scene → edit `near` 3:4 (ref=far)

Prompt text: use `look_text` / `desc_zh` + style from project (reuse `_style_for` from current `image_gen.py`).

- [ ] **Step 3: API routes**

```python
@app.post("/api/projects/{project_id}/generate-images")
def api_generate_all_images(...):
    # enqueue_one_click; return bundle + {batch_id, jobs}

@app.post("/api/projects/{project_id}/assets/{asset_id}/generate-image")
def api_generate_asset_image(..., field: str | None = None): ...

@app.post("/api/projects/{project_id}/assets/{asset_id}/edit-image")
async def api_edit_image(..., prompt: str = Form(...), target_field: str = Form(...),
                         aspect: str = Form("3:4"), files: list[UploadFile] = File(default=[])): ...

@app.get("/api/projects/{project_id}/image-jobs")
def api_list_image_jobs(..., active_only: bool = True): ...

@app.post("/api/projects/{project_id}/image-batches/{batch_id}/cancel")
def api_cancel_batch(...): ...

@app.get("/api/projects/{project_id}/image-output-files")
def api_list_output_dir_files(...):  # names under image_output_dir for edit UI
```

Wrap LLM-heavy routes: if `llm_supervisor.image_busy or has_active_jobs(db)` → `HTTPException(409, "参考图生成中，请稍后再试")`.

Lifespan: start `ImageWorker` thread; on shutdown stop worker; on startup mark stale `running` → `failed`.

- [ ] **Step 4: PASS tests + commit**

```bash
git commit -m "Replace 造像 HTTP with serial embedded image job worker."
```

---

### Task 5: Shot refs + readiness for scene near/far

**Files:**
- Modify: `backend/app/domain/shot_refs.py`
- Modify: `backend/app/domain/slots.py` (if scene image key)
- Modify: readiness in `services.py`
- Test: extend existing slots/refs tests

- [ ] **Step 1: Scene portrait path = `near_path or far_path or image_path`**

```python
def scene_image_path(asset: Asset) -> str:
    return (asset.near_path or asset.far_path or asset.image_path or "").strip()
```

Character unchanged (half OR full). Prop: `image_path`.

- [ ] **Step 2: Update tests that assumed scene `image_path` only**

- [ ] **Step 3: Commit**

```bash
git commit -m "Use scene near/far paths for storyboard reference packing."
```

---

### Task 6: Frontend — queue state, phases, scene slots, edit

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/App.tsx` (`BookAssets`, `AssetCard`)
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: `generateImages` → `{ batch_id, jobs }`; `listImageJobs`; `cancelImageBatch`; `editAssetImage`; `listImageOutputFiles`

- [ ] **Step 1: API helpers**

```ts
listImageJobs: (pid: string, activeOnly = true) =>
  req<{ jobs: ImageJob[] }>(`/api/projects/${pid}/image-jobs?active_only=${activeOnly}`),
cancelImageBatch: (pid: string, batchId: string) =>
  req(`/api/projects/${pid}/image-batches/${batchId}/cancel`, { method: "POST" }),
editAssetImage: (pid: string, aid: string, form: FormData) =>
  req(`/api/projects/${pid}/assets/${aid}/edit-image`, { method: "POST", body: form }),
listImageOutputFiles: (pid: string) =>
  req<{ files: { name: string; path: string }[] }>(`/api/projects/${pid}/image-output-files`),
```

Phase label map:

```ts
function jobPhaseLabel(j: ImageJob): string {
  if (j.phase === "loading_t2i" || j.phase === "ensuring_comfy") return "文生图模型加载中";
  if (j.phase === "loading_edit") return "图片编辑模型加载中";
  if (j.status === "queued") return "排队中";
  if (j.status === "running") return "生成中";
  if (j.status === "failed") return "失败";
  return "";
}
```

- [ ] **Step 2: Polling on BookAssets**

On mount + while any active job: `setInterval` 1500ms → `listImageJobs` → merge into asset card badges. Persist across refresh because server owns jobs.

- [ ] **Step 3: AssetCard slots**

- Character: full + half (unchanged layout)  
- Scene: **远景** (`far`) + **近景** (`near`)  
- Prop: single image  
- Per slot: 重生成 / 上传 / 删除  
- Button **编辑生成**: modal — list files from `listImageOutputFiles` (checkbox ≤3) + file input + prompt + target field → `editAssetImage`

- [ ] **Step 4: One-click** calls enqueue API (no long hang); show `生成中 (n/m)` + cancel batch; remove 造像 `:8000` hint → `Comfy 按需启动 :8189`

- [ ] **Step 5: Disable LLM actions when `activeJobs.length > 0`** with tooltip「参考图生成中」

- [ ] **Step 6: Manual UI smoke (optional) + commit**

```bash
git commit -m "Show durable image-job phases and scene near/far slots in book assets."
```

---

### Task 7: start.ps1 — no 造像, no Comfy, no LLM by default

**Files:**
- Modify: `start.ps1`
- Modify: `README.md` (short note if present)

- [ ] **Step 1: Remove block that starts `D:\Develop\aiImage\scripts\start.ps1`**

- [ ] **Step 2: Remove default `start-llm.ps1` invocation** (print hint: run `.\start-llm.ps1` when doing text; Comfy starts on first image job)

```powershell
Write-Host "LLM / ComfyUI are on-demand (not started here)."
Write-Host "  Text: .\start-llm.ps1"
Write-Host "  Images: first generate job starts ComfyUI at :8189"
Start-Backend $python
Start-Frontend
...
```

- [ ] **Step 3: Commit**

```bash
git commit -m "Stop auto-starting 造像, Comfy, and LLM from start.ps1."
```

---

### Task 8: 青渡川 E2E — simulate frontend full flow (**real GPU, no FakeComfy**)

**Files:**
- Create: `backend/scripts/e2e_qingduchuan_flow.py` (primary; agent runs this after implementation)
- Novel path: `D:\Develop\aiVedioProducer\docs\novels\青渡川.txt` (same as `verify_qingduchuan.py`)

**Hard rule:** This flow **must not** use FakeComfy. It drives the real `ImageWorker` → real ComfyUI `:8189` → real checkpoints / Qwen Edit on GPU. Unit tests in Tasks 3–4 may still use fakes; **青渡川 simulation does not**.

**What “simulate frontend” means:** hit the **same HTTP endpoints** the UI uses, against a **running** API (`http://127.0.0.1:8790`), in order:

1. Ensure LLM available for text steps (`start-llm.ps1` if needed); after assets+storyboard, one-click images will stop LLM (hard mutex) and start Comfy on demand.
2. `POST /api/projects` — title `青渡川`, **full** novel text from `青渡川.txt`, style 半写实江湖  
3. `PATCH` project — set `image_output_dir` (e.g. under `data/projects/.../generated` or a dedicated folder)  
4. `POST /api/projects/{id}/generate-assets?replace=true` (or prescan + confirm) — book character/scene/prop descriptions via **real LLM**  
5. First chapter `POST .../storyboard` — **real LLM**  
6. `POST .../generate-images` — enqueue one-click (real GPU)  
7. Poll `GET .../image-jobs?active_only=true` every ~2s; print phase labels (`文生图模型加载中` / `图片编辑模型加载中` / `生成中`); timeout generous (e.g. 3–6 hours depending on asset count)  
8. While jobs active, assert `POST .../storyboard?overwrite=true` → **409**  
9. Assert: each character has non-empty `full_path` + `half_path` and files exist on disk with non-trivial size; each scene `far_path` + `near_path`; props `image_path`; job list ordered t2i-before-edit for the batch  
10. Write `backend/scripts/qingduchuan_e2e_report.json` with timings, job statuses, asset paths

**Prerequisites (script must check and fail loudly):**

- Novel file exists  
- API `:8790` healthy  
- Comfy root / python paths configured (script may trigger ensure_running via first job; or preflight `GET` Comfy if already up)  
- GPU / Comfy can load RealVis / Guofeng / Qwen Edit as needed  

**Not in default `pytest -q`:** mark optional `pytest` wrapper `@pytest.mark.gpu` / `@pytest.mark.slow` so CI without GPU does not run it; **agent verification after Task 8 = run the script for real**.

- [ ] **Step 1: Implement `e2e_qingduchuan_flow.py`**

```python
# backend/scripts/e2e_qingduchuan_flow.py
"""青渡川 full UI-equivalent flow — REAL LLM + REAL Comfy GPU (no FakeComfy)."""
from __future__ import annotations
import argparse, json, time
from pathlib import Path
import httpx

NOVEL = Path(r"D:\Develop\aiVedioProducer\docs\novels\青渡川.txt")
API = "http://127.0.0.1:8790"

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=API)
    ap.add_argument("--poll-sec", type=float, default=2.0)
    ap.add_argument("--timeout-sec", type=float, default=21600)  # 6h
    args = ap.parse_args()
    text = NOVEL.read_text(encoding="utf-8")
    client = httpx.Client(base_url=args.base_url, timeout=600.0)
    client.get("/api/health").raise_for_status()
    # delete prior 青渡川 test project if any ...
    # create → patch image_output_dir → generate-assets → storyboard
    # generate-images → poll image-jobs until idle
    # assert paths + 409 during run → write report JSON
    ...

if __name__ == "__main__":
    main()
```

Fill in the full step body (no FakeComfy imports, no monkeypatch of ComfyClient).

- [ ] **Step 2: Optional GPU pytest (skipped by default)**

```python
# backend/tests/test_e2e_qingduchuan_flow_gpu.py
import pytest
pytestmark = [pytest.mark.gpu, pytest.mark.slow]

@pytest.mark.skipif(not Path(r"D:\Develop\aiVedioProducer\docs\novels\青渡川.txt").exists(), reason="novel missing")
def test_qingduchuan_real_gpu_flow():
    # subprocess: uv run python scripts/e2e_qingduchuan_flow.py
    # or import main(); assert report ok
    ...
```

Default `pytest -q` must **not** require GPU. Agent post-implementation gate: **always** run the script on this machine.

- [ ] **Step 3: Run real GPU E2E (agent mandatory)**

```powershell
# API already up; LLM available for text steps
cd D:\Develop\novel2Lens\backend
uv run python scripts/e2e_qingduchuan_flow.py --base-url http://127.0.0.1:8790
```

Expected: report JSON with all jobs `succeeded`, asset image files on disk, no FakeComfy in stack traces.

- [ ] **Step 4: Commit**

```bash
git commit -m "Add 青渡川 real-GPU E2E simulating frontend create-to-images flow."
```

---

### Task 9: Full regression + docs + cleanup

**Files:**
- Update: `docs/superpowers/specs/2026-09-05-asset-image-gen-design.md` already superseded  
- Remove dead `zaoxiang_client` tests or rewrite  
- Run full `pytest`

- [ ] **Step 1:** `uv run pytest -q` — all green  
- [ ] **Step 2:** Delete obsolete `test_zaoxiang_client.py` if unused; fix `test_image_gen_api.py` for async enqueue semantics  
- [ ] **Step 3:** Commit + push

```bash
git commit -m "Finish embedded image pipeline; drop 造像 client dependency."
git push origin HEAD
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| Embed T2I + edit, no aiImage HTTP | 1, 4 |
| Serial queue + durable jobs + refresh | 2, 4, 6 |
| One-click all t2i then edit; half 3:4; scene far→near | 4, 5 |
| Manual edit ≤3 refs from output dir | 4, 6 |
| Delete + upload kept | 6 (existing endpoints) |
| LLM hard mutex 409 + stop Flash-Next | 3, 4 |
| Comfy on-demand; 180s idle free (+ stop) | 3, 4 |
| Frontend phases 文生图/编辑模型加载中 | 4 phase field, 6 labels |
| start.ps1 no 造像/Comfy/LLM | 7 |
| 青渡川 auto test full UI-equivalent flow (**real GPU**) | 8 |

## Execution handoff

Plan saved to `docs/superpowers/plans/2026-09-05-embedded-image-pipeline.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — this session with executing-plans checkpoints  

Which approach?
