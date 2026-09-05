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
    # create queued job; POST storyboard or extract 鈫?409
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

1. Each character 鈫?t2i `full` 9:16  
2. Each scene 鈫?t2i `far` 16:9  
3. Each prop 鈫?t2i `image` 1:1  
4. Each character 鈫?edit `half` 3:4 (ref=full)  
5. Each scene 鈫?edit `near` 3:4 (ref=far)

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

Wrap LLM-heavy routes: if `llm_supervisor.image_busy or has_active_jobs(db)` 鈫?`HTTPException(409, "鍙傝€冨浘鐢熸垚涓紝璇风◢鍚庡啀璇?)`.

Lifespan: start `ImageWorker` thread; on shutdown stop worker; on startup mark stale `running` 鈫?`failed`.

- [ ] **Step 4: PASS tests + commit**

```bash
git commit -m "Replace 閫犲儚 HTTP with serial embedded image job worker."
```

---

