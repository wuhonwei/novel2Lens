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
    desc_zh: Mapped[str] = mapped_column(Text, default="")
    desc_en: Mapped[str] = mapped_column(Text, default="")
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    variant_reason: Mapped[str] = mapped_column(String(20), default="")
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    half_path: Mapped[str] = mapped_column(String(400), default="")
    full_path: Mapped[str] = mapped_column(String(400), default="")
    image_path: Mapped[str] = mapped_column(String(400), default="")
    voice_path: Mapped[str] = mapped_column(String(400), default="")
    created_chapter_id: Mapped[str] = mapped_column(String(36), default="")

    project: Mapped[Project] = relationship(back_populates="assets")


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
    lines_json: Mapped[str] = mapped_column(Text, default="[]")
    half_lock: Mapped[bool] = mapped_column(Boolean, default=False)

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


def init_db() -> None:
    Base.metadata.create_all(engine)
    ensure_schema()


def project_dir(project_id: str) -> Path:
    path = settings.data_dir / "projects" / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path
