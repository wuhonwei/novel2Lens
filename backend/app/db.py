from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    style: Mapped[str] = mapped_column(String(400), default="")
    source_text: Mapped[str] = mapped_column(Text, default="")
    llm_base_url: Mapped[str] = mapped_column(String(300), default="http://127.0.0.1:8080/v1")
    llm_model: Mapped[str] = mapped_column(String(120), default="qwen3.8-flash-next")
    fallback_base_url: Mapped[str] = mapped_column(String(300), default="http://127.0.0.1:11434/v1")
    fallback_model: Mapped[str] = mapped_column(String(120), default="qwen2.5:32b")
    allow_fallback: Mapped[bool] = mapped_column(Boolean, default=True)
    thinking: Mapped[str] = mapped_column(String(20), default="medium")
    registry_scan_json: Mapped[str] = mapped_column(Text, default="{}")
    zaoxiang_base_url: Mapped[str] = mapped_column(String(300), default="http://127.0.0.1:8000")
    image_output_dir: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    chapters: Mapped[list["Chapter"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    assets: Mapped[list["Asset"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    shots: Mapped[list["Shot"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    proposals: Mapped[list["Proposal"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="pending")
    used_fallback_llm: Mapped[bool] = mapped_column(Boolean, default=False)
    last_error: Mapped[str] = mapped_column(Text, default="")
    prescan_done: Mapped[bool] = mapped_column(Boolean, default=False)

    project: Mapped[Project] = relationship(back_populates="chapters")


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    refer_as: Mapped[str] = mapped_column(String(40), default="")
    age_band: Mapped[str] = mapped_column(String(40), default="")
    appearance_json: Mapped[str] = mapped_column(Text, default="{}")
    background_zh: Mapped[str] = mapped_column(Text, default="")
    desc_zh: Mapped[str] = mapped_column(Text, default="")
    desc_en: Mapped[str] = mapped_column(Text, default="")
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    variant_reason: Mapped[str] = mapped_column(String(20), default="")
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    half_path: Mapped[str] = mapped_column(String(400), default="")
    full_path: Mapped[str] = mapped_column(String(400), default="")
    far_path: Mapped[str] = mapped_column(String(400), default="")
    near_path: Mapped[str] = mapped_column(String(400), default="")
    image_path: Mapped[str] = mapped_column(String(400), default="")
    voice_path: Mapped[str] = mapped_column(String(400), default="")
    image_scores_json: Mapped[str] = mapped_column(Text, default="{}")
    created_chapter_id: Mapped[str] = mapped_column(String(36), default="")

    project: Mapped[Project] = relationship(back_populates="assets")


class ImageJob(Base):
    __tablename__ = "image_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    asset_id: Mapped[str] = mapped_column(String(36), index=True, default="")
    shot_id: Mapped[str] = mapped_column(String(36), index=True, default="")
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


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id"), index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")

    project: Mapped[Project] = relationship(back_populates="proposals")


class Shot(Base):
    __tablename__ = "shots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id"), index=True)
    order_index: Mapped[int] = mapped_column(Integer)
    duration_s: Mapped[float] = mapped_column(Float, default=6.0)
    scene_asset_id: Mapped[str] = mapped_column(String(36), default="")
    prop_asset_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    camera: Mapped[str] = mapped_column(String(40), default="固定")
    camera_detail: Mapped[str] = mapped_column(String(300), default="")
    narration: Mapped[str] = mapped_column(Text, default="")
    action: Mapped[str] = mapped_column(Text, default="")
    source_excerpt: Mapped[str] = mapped_column(Text, default="")
    character_count: Mapped[int] = mapped_column(Integer, default=0)
    first_frame_unready: Mapped[bool] = mapped_column(Boolean, default=True)
    prompt_zh: Mapped[str] = mapped_column(Text, default="")
    prompt_en: Mapped[str] = mapped_column(Text, default="")
    h3_prompt: Mapped[str] = mapped_column(Text, default="")
    background: Mapped[str] = mapped_column(Text, default="")
    slots_json: Mapped[str] = mapped_column(Text, default="[]")
    text_fallbacks_json: Mapped[str] = mapped_column(Text, default="[]")
    lines_json: Mapped[str] = mapped_column(Text, default="[]")
    half_lock: Mapped[bool] = mapped_column(Boolean, default=False)
    first_frame_path: Mapped[str] = mapped_column(String(400), default="")
    first_frame_score: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    first_frame_score_comment: Mapped[str] = mapped_column(Text, default="")

    project: Mapped[Project] = relationship(back_populates="shots")


settings.data_dir.mkdir(parents=True, exist_ok=True)
DB_PATH = settings.data_dir / "novel2lens.sqlite"
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def reset_engine(url: str | None = None) -> None:
    global engine, SessionLocal, DB_PATH
    if url is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        DB_PATH = settings.data_dir / "novel2lens.sqlite"
        url = f"sqlite:///{DB_PATH}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    ensure_schema()


def ensure_schema() -> None:
    """Add columns introduced after first create_all for existing SQLite files."""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(projects)")).fetchall()}
        if "registry_scan_json" not in cols:
            conn.execute(text("ALTER TABLE projects ADD COLUMN registry_scan_json TEXT DEFAULT '{}'"))
        if "zaoxiang_base_url" not in cols:
            conn.execute(text("ALTER TABLE projects ADD COLUMN zaoxiang_base_url VARCHAR(300) DEFAULT 'http://127.0.0.1:8000'"))
        if "image_output_dir" not in cols:
            conn.execute(text("ALTER TABLE projects ADD COLUMN image_output_dir VARCHAR(500) DEFAULT ''"))
        asset_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(assets)")).fetchall()}
        if "background_zh" not in asset_cols:
            conn.execute(text("ALTER TABLE assets ADD COLUMN background_zh TEXT DEFAULT ''"))
        if "far_path" not in asset_cols:
            conn.execute(text("ALTER TABLE assets ADD COLUMN far_path VARCHAR(400) DEFAULT ''"))
        if "near_path" not in asset_cols:
            conn.execute(text("ALTER TABLE assets ADD COLUMN near_path VARCHAR(400) DEFAULT ''"))
        if "image_scores_json" not in asset_cols:
            conn.execute(text("ALTER TABLE assets ADD COLUMN image_scores_json TEXT DEFAULT '{}'"))
        shot_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(shots)")).fetchall()}
        if "prop_asset_ids_json" not in shot_cols:
            conn.execute(text("ALTER TABLE shots ADD COLUMN prop_asset_ids_json TEXT DEFAULT '[]'"))
        if "text_fallbacks_json" not in shot_cols:
            conn.execute(text("ALTER TABLE shots ADD COLUMN text_fallbacks_json TEXT DEFAULT '[]'"))
        if "first_frame_path" not in shot_cols:
            conn.execute(text("ALTER TABLE shots ADD COLUMN first_frame_path VARCHAR(400) DEFAULT ''"))
        if "first_frame_score" not in shot_cols:
            conn.execute(text("ALTER TABLE shots ADD COLUMN first_frame_score INTEGER"))
        if "first_frame_score_comment" not in shot_cols:
            conn.execute(text("ALTER TABLE shots ADD COLUMN first_frame_score_comment TEXT DEFAULT ''"))
        job_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(image_jobs)")).fetchall()}
        if "shot_id" not in job_cols:
            conn.execute(text("ALTER TABLE image_jobs ADD COLUMN shot_id VARCHAR(36) DEFAULT ''"))


def init_db() -> None:
    Base.metadata.create_all(engine)
    ensure_schema()


def project_dir(project_id: str) -> Path:
    path = settings.data_dir / "projects" / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path
