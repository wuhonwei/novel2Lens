from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.comfy_supervisor import ComfySupervisor
from app.config import settings
from app.db import Asset, Chapter, Project, Proposal, Shot, init_db
from app import db as database
from app.domain.registry import sanitize_aliases, sanitize_character_fields
from app.image_gen import clear_asset_image, list_image_output_files, resolve_image_output_dir
from app.image_jobs import (
    cancel_batch,
    enqueue_asset_all_slots,
    enqueue_asset_field,
    enqueue_manual_edit,
    enqueue_one_click,
    has_active_jobs,
    list_active_jobs,
    mark_stale_running_failed,
    serialize_job,
)
from app.image_worker import ImageWorker
from app.llm_supervisor import LlmSupervisor
from app.services import (
    confirm_proposals,
    export_project,
    extract_assets,
    full_registry_scan,
    generate_storyboard,
    merge_assets,
    prescan_project,
    rebuild_chapters,
    refresh_shot_readiness,
    repair_shot_prompts_if_needed,
    save_upload,
    serialize_asset,
    serialize_chapter,
    serialize_project,
    serialize_shot,
    update_shot,
    _load,
    _uid,
)

llm_supervisor = LlmSupervisor()
comfy_supervisor = ComfySupervisor(
    base_url=settings.comfy_base_url,
    root=settings.comfy_root,
    python=settings.comfy_python,
    idle_seconds=settings.image_idle_unload_seconds,
    stop_when_idle=settings.stop_comfy_when_idle,
)
image_worker: ImageWorker | None = None


def _start_image_worker() -> None:
    global image_worker
    if image_worker is None:
        image_worker = ImageWorker(
            session_factory=database.SessionLocal,
            comfy=comfy_supervisor,
            llm=llm_supervisor,
        )
    image_worker.start()


def _stop_image_worker() -> None:
    global image_worker
    if image_worker is not None:
        image_worker.stop()


def _reject_if_image_busy(db: Session) -> None:
    if llm_supervisor.image_busy or has_active_jobs(db):
        raise HTTPException(409, "参考图生成中，请稍后再试")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    db = database.SessionLocal()
    try:
        mark_stale_running_failed(db)
    finally:
        db.close()
    _start_image_worker()
    try:
        yield
    finally:
        _stop_image_worker()


app = FastAPI(title="novel2Lens", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5176", "http://localhost:5176"],
    allow_methods=["*"],
    allow_headers=["*"],
)
settings.data_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(settings.data_dir)), name="media")


def db_session():
    return database.SessionLocal()


def get_project(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    return project


def get_chapter(db: Session, project_id: str, chapter_id: str) -> Chapter:
    chapter = db.get(Chapter, chapter_id)
    if not chapter or chapter.project_id != project_id:
        raise HTTPException(404, "章节不存在")
    return chapter


class ProjectIn(BaseModel):
    title: str = "未命名小说"
    text: str = ""
    style: str = ""


class SettingsIn(BaseModel):
    title: str | None = None
    style: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    fallback_base_url: str | None = None
    fallback_model: str | None = None
    allow_fallback: bool | None = None
    thinking: str | None = None
    text: str | None = None
    zaoxiang_base_url: str | None = None
    image_output_dir: str | None = None


class ConfirmIn(BaseModel):
    items: list[dict] = Field(default_factory=list)


class MergeIn(BaseModel):
    keep_id: str
    drop_id: str


class ShotPatch(BaseModel):
    duration_s: float | None = None
    camera: str | None = None
    camera_detail: str | None = None
    narration: str | None = None
    action: str | None = None
    source_excerpt: str | None = None
    background: str | None = None
    half_lock: bool | None = None
    prompt_zh: str | None = None
    prompt_en: str | None = None
    h3_prompt: str | None = None
    lines: list[dict] | None = None
    scene_asset_id: str | None = None
    prop_asset_ids: list[str] | None = None
    recompile: bool = True


class AssetPatch(BaseModel):
    name: str | None = None
    aliases: list[str] | None = None
    refer_as: str | None = None
    age_band: str | None = None
    appearance: dict | None = None
    background_zh: str | None = None
    desc_zh: str | None = None
    desc_en: str | None = None
    confirmed: bool | None = None


class TranslateIn(BaseModel):
    desc_zh: str


def _bundle(db: Session, project: Project) -> dict:
    chapters = db.query(Chapter).filter(Chapter.project_id == project.id).order_by(Chapter.index).all()
    assets = db.query(Asset).filter(Asset.project_id == project.id).all()
    repair_shot_prompts_if_needed(db, project, assets)
    shots = db.query(Shot).filter(Shot.project_id == project.id).order_by(Shot.order_index).all()
    proposals = (
        db.query(Proposal)
        .filter(Proposal.project_id == project.id, Proposal.status == "pending")
        .all()
    )
    title_by = {c.id: c.title for c in chapters}
    return {
        "project": serialize_project(project),
        "chapters": [serialize_chapter(c) for c in chapters],
        "assets": [serialize_asset(a) for a in assets],
        "shots": [serialize_shot(s, title_by.get(s.chapter_id, ""), assets) for s in shots],
        "proposals": [{"id": p.id, "chapter_id": p.chapter_id, **(_load(p.payload_json, {}))} for p in proposals],
        "active_image_jobs": list_active_jobs(db, project.id, active_only=True),
    }


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/projects")
def list_projects():
    db = db_session()
    try:
        rows = db.query(Project).order_by(Project.created_at.desc()).all()
        return [serialize_project(p) for p in rows]
    finally:
        db.close()


@app.post("/api/projects")
async def create_project(body: ProjectIn):
    db = db_session()
    try:
        project = Project(id=_uid(), title=body.title.strip() or "未命名小说", style=body.style, source_text=body.text)
        db.add(project)
        db.flush()
        rebuild_chapters(db, project)
        db.commit()
        db.refresh(project)
        return _bundle(db, project)
    finally:
        db.close()


@app.post("/api/projects/upload")
async def upload_project(title: str = Form("未命名小说"), style: str = Form(""), file: UploadFile = File(...)):
    raw = await file.read()
    text = raw.decode("utf-8-sig", errors="replace")
    db = db_session()
    try:
        project = Project(id=_uid(), title=title.strip() or Path(file.filename or "novel").stem, style=style, source_text=text)
        db.add(project)
        db.flush()
        rebuild_chapters(db, project)
        db.commit()
        return _bundle(db, project)
    finally:
        db.close()


@app.get("/api/projects/{project_id}")
def get_project_bundle(project_id: str):
    db = db_session()
    try:
        return _bundle(db, get_project(db, project_id))
    finally:
        db.close()


@app.patch("/api/projects/{project_id}")
def patch_project(project_id: str, body: SettingsIn):
    db = db_session()
    try:
        project = get_project(db, project_id)
        data = body.model_dump(exclude_unset=True)
        rebuild = False
        if "text" in data and data["text"] is not None:
            project.source_text = data.pop("text")
            rebuild = True
        for key, value in data.items():
            setattr(project, key, value)
        if rebuild:
            rebuild_chapters(db, project)
        db.commit()
        return _bundle(db, project)
    finally:
        db.close()


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str):
    db = db_session()
    try:
        project = get_project(db, project_id)
        db.delete(project)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.post("/api/projects/{project_id}/prescan")
async def api_prescan(project_id: str, replace: bool = False):
    db = db_session()
    try:
        project = get_project(db, project_id)
        _reject_if_image_busy(db)
        try:
            result = await prescan_project(db, project, replace=replace)
        except Exception as exc:
            raise HTTPException(502, str(exc)) from exc
        return {**_bundle(db, project), "result": result}
    finally:
        db.close()


@app.post("/api/projects/{project_id}/generate-assets")
async def api_generate_assets(project_id: str, replace: bool = True):
    """One-click book-level asset generation (characters / scenes / props)."""
    db = db_session()
    try:
        project = get_project(db, project_id)
        _reject_if_image_busy(db)
        if not (project.source_text or "").strip():
            raise HTTPException(400, "项目没有正文，请先上传或粘贴小说 TXT")
        try:
            result = await full_registry_scan(db, project, replace=replace)
        except Exception as exc:
            raise HTTPException(502, str(exc)) from exc
        return {**_bundle(db, project), "result": result}
    finally:
        db.close()


@app.post("/api/projects/{project_id}/chapters/{chapter_id}/extract")
async def api_extract(project_id: str, chapter_id: str, overwrite: bool = False):
    db = db_session()
    try:
        project = get_project(db, project_id)
        chapter = get_chapter(db, project_id, chapter_id)
        _reject_if_image_busy(db)
        try:
            result = await extract_assets(db, project, chapter, overwrite=overwrite)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except Exception as exc:
            chapter.last_error = str(exc)
            db.commit()
            raise HTTPException(502, str(exc)) from exc
        return {**_bundle(db, project), "result": result}
    finally:
        db.close()


@app.post("/api/projects/{project_id}/chapters/{chapter_id}/confirm")
def api_confirm(project_id: str, chapter_id: str, body: ConfirmIn):
    db = db_session()
    try:
        project = get_project(db, project_id)
        chapter = get_chapter(db, project_id, chapter_id)
        confirm_proposals(db, project, chapter, body.items)
        return _bundle(db, project)
    finally:
        db.close()


@app.post("/api/projects/{project_id}/chapters/{chapter_id}/storyboard")
async def api_storyboard(project_id: str, chapter_id: str, overwrite: bool = False):
    db = db_session()
    try:
        project = get_project(db, project_id)
        chapter = get_chapter(db, project_id, chapter_id)
        _reject_if_image_busy(db)
        try:
            result = await generate_storyboard(db, project, chapter, overwrite=overwrite)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except Exception as exc:
            chapter.last_error = str(exc)
            db.commit()
            raise HTTPException(502, str(exc)) from exc
        return {**_bundle(db, project), "result": result}
    finally:
        db.close()


@app.patch("/api/projects/{project_id}/shots/{shot_id}")
def api_patch_shot(project_id: str, shot_id: str, body: ShotPatch):
    db = db_session()
    try:
        project = get_project(db, project_id)
        shot = db.get(Shot, shot_id)
        if not shot or shot.project_id != project_id:
            raise HTTPException(404, "分镜不存在")
        return update_shot(db, project, shot, body.model_dump(exclude_unset=True))
    finally:
        db.close()


@app.patch("/api/projects/{project_id}/assets/{asset_id}")
def api_patch_asset(project_id: str, asset_id: str, body: AssetPatch):
    db = db_session()
    try:
        get_project(db, project_id)
        asset = db.get(Asset, asset_id)
        if not asset or asset.project_id != project_id:
            raise HTTPException(404, "资产不存在")
        data = body.model_dump(exclude_unset=True)
        if "aliases" in data or "refer_as" in data or "name" in data:
            name = data.get("name", asset.name)
            refer_as = data.get("refer_as", asset.refer_as)
            aliases = data.get("aliases", _load(asset.aliases_json, []))
            if asset.kind == "character" or data.get("kind") == "character":
                cleaned = sanitize_character_fields(
                    {"name": name, "aliases": aliases, "refer_as": refer_as}
                )
                data["aliases"] = cleaned["aliases"]
                if "refer_as" in data or cleaned.get("refer_as"):
                    data["refer_as"] = cleaned["refer_as"] or refer_as
            else:
                data["aliases"] = sanitize_aliases(aliases, name=name, refer_as=refer_as or "")
        if "aliases" in data:
            asset.aliases_json = json_dumps(data.pop("aliases"))
        if "appearance" in data:
            asset.appearance_json = json_dumps(data.pop("appearance"))
        for key, value in data.items():
            setattr(asset, key, value)
        db.commit()
        return serialize_asset(asset)
    finally:
        db.close()


def json_dumps(value) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


@app.post("/api/projects/{project_id}/assets/merge")
def api_merge(project_id: str, body: MergeIn):
    db = db_session()
    try:
        get_project(db, project_id)
        merge_assets(db, project_id, body.keep_id, body.drop_id)
        return _bundle(db, get_project(db, project_id))
    finally:
        db.close()


@app.post("/api/projects/{project_id}/assets/{asset_id}/upload")
async def api_upload_asset(
    project_id: str,
    asset_id: str,
    field: str = Form(...),
    file: UploadFile = File(...),
):
    if field not in ("half", "full", "image", "voice"):
        raise HTTPException(400, "field 必须是 half/full/image/voice")
    db = db_session()
    try:
        project = get_project(db, project_id)
        asset = db.get(Asset, asset_id)
        if not asset or asset.project_id != project_id:
            raise HTTPException(404, "资产不存在")
        data = await file.read()
        save_upload(asset, field, file.filename or "upload.png", data)
        db.commit()
        refresh_shot_readiness(db, project)
        return serialize_asset(asset)
    finally:
        db.close()


@app.post("/api/projects/{project_id}/generate-images")
def api_generate_all_images(project_id: str):
    """Enqueue one-click reference images (t2i then edit); returns immediately."""
    db = db_session()
    try:
        project = get_project(db, project_id)
        result = enqueue_one_click(db, project)
        return {
            **_bundle(db, project),
            "batch_id": result["batch_id"],
            "jobs": result["jobs"],
            "image_gen": {
                "ok": True,
                "queued": len(result["job_ids"]),
                "batch_id": result["batch_id"],
                "job_ids": result["job_ids"],
                "image_output_dir": str(resolve_image_output_dir(project)),
            },
        }
    finally:
        db.close()


@app.post("/api/projects/{project_id}/assets/{asset_id}/generate-image")
def api_generate_asset_image(project_id: str, asset_id: str, field: str | None = None):
    db = db_session()
    try:
        project = get_project(db, project_id)
        asset = db.get(Asset, asset_id)
        if not asset or asset.project_id != project_id:
            raise HTTPException(404, "资产不存在")
        try:
            if field is None:
                jobs = enqueue_asset_all_slots(db, project, asset)
            else:
                jobs = [enqueue_asset_field(db, project, asset, field)]
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {
            "ok": True,
            "job": serialize_job(jobs[0]),
            "jobs": [serialize_job(j) for j in jobs],
            "asset": serialize_asset(asset),
        }
    finally:
        db.close()


@app.post("/api/projects/{project_id}/assets/{asset_id}/edit-image")
async def api_edit_image(
    project_id: str,
    asset_id: str,
    prompt: str = Form(...),
    target_field: str = Form(...),
    aspect: str = Form("3:4"),
    files: list[UploadFile] = File(default=[]),
    ref_paths: str = Form(""),
):
    db = db_session()
    try:
        project = get_project(db, project_id)
        asset = db.get(Asset, asset_id)
        if not asset or asset.project_id != project_id:
            raise HTTPException(404, "资产不存在")
        paths: list[str] = []
        if ref_paths.strip():
            import json as _json

            try:
                parsed = _json.loads(ref_paths)
                if isinstance(parsed, list):
                    paths.extend(str(p) for p in parsed)
                else:
                    paths.extend(p.strip() for p in ref_paths.split(",") if p.strip())
            except _json.JSONDecodeError:
                paths.extend(p.strip() for p in ref_paths.split(",") if p.strip())
        out_root = resolve_image_output_dir(project)
        upload_dir = out_root / "_edit_uploads" / asset.id
        upload_dir.mkdir(parents=True, exist_ok=True)
        for i, uf in enumerate(files or []):
            data = await uf.read()
            if not data:
                continue
            name = uf.filename or f"ref_{i}.png"
            dest = upload_dir / name
            dest.write_bytes(data)
            paths.append(str(dest))
        try:
            job = enqueue_manual_edit(
                db,
                project,
                asset,
                target_field=target_field,
                prompt=prompt,
                ref_paths=paths,
                aspect=aspect,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "job": serialize_job(job)}
    finally:
        db.close()


@app.get("/api/projects/{project_id}/image-jobs")
def api_list_image_jobs(project_id: str, active_only: bool = True):
    db = db_session()
    try:
        get_project(db, project_id)
        return {"jobs": list_active_jobs(db, project_id, active_only=active_only)}
    finally:
        db.close()


@app.post("/api/projects/{project_id}/image-batches/{batch_id}/cancel")
def api_cancel_batch(project_id: str, batch_id: str):
    db = db_session()
    try:
        get_project(db, project_id)
        n = cancel_batch(db, batch_id)
        return {"ok": True, "cancelled": n}
    finally:
        db.close()


@app.get("/api/projects/{project_id}/image-output-files")
def api_list_output_dir_files(project_id: str):
    db = db_session()
    try:
        project = get_project(db, project_id)
        return {
            "image_output_dir": str(resolve_image_output_dir(project)),
            "files": list_image_output_files(project),
        }
    finally:
        db.close()


@app.delete("/api/projects/{project_id}/assets/{asset_id}/image")
def api_clear_asset_image(project_id: str, asset_id: str, field: str = "image"):
    db = db_session()
    try:
        project = get_project(db, project_id)
        asset = db.get(Asset, asset_id)
        if not asset or asset.project_id != project_id:
            raise HTTPException(404, "资产不存在")
        try:
            return clear_asset_image(db, project, asset, field)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    finally:
        db.close()


@app.post("/api/projects/{project_id}/export")
def api_export(project_id: str):
    db = db_session()
    try:
        project = get_project(db, project_id)
        doc, md, path = export_project(db, project)
        return {"document": doc, "markdown": md, "path": str(path)}
    finally:
        db.close()


@app.get("/api/projects/{project_id}/export/file")
def api_export_file(project_id: str):
    db = db_session()
    try:
        project = get_project(db, project_id)
        _, _, path = export_project(db, project)
        return FileResponse(path, filename="novel2lens.json")
    finally:
        db.close()

