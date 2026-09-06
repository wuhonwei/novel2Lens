# -*- coding: utf-8 -*-
from pathlib import Path

from app.db import Asset, Project
from app.image_gen import (
    KIND_FOLDERS,
    kind_folder_name,
    list_image_output_files,
    resolve_image_output_dir,
    safe_asset_filename,
    write_asset_image,
)


def test_kind_folder_names():
    assert kind_folder_name("character") == "人物"
    assert kind_folder_name("scene") == "场景"
    assert kind_folder_name("prop") == "物品"
    assert set(KIND_FOLDERS.values()) == {"人物", "场景", "物品"}


def test_safe_asset_filename():
    assert "周" in safe_asset_filename("周大人")
    assert "/" not in safe_asset_filename("a/b\\c")
    assert safe_asset_filename("???") == "asset"


def test_write_asset_image_uses_kind_folder(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    out = tmp_path / "refs"
    out.mkdir()
    project = Project(id="p1", title="t", style="s", source_text="x", image_output_dir=str(out))
    asset = Asset(id="a1", project_id="p1", kind="character", name="林砚之")
    stored = write_asset_image(project, asset, "full", b"fakepng")
    assert (out / "人物" / "林砚之_full.png").is_file()
    assert (tmp_path / stored).is_file()
    assert asset.full_path == stored


def test_list_files_filters_by_kind(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    out = tmp_path / "refs"
    (out / "人物").mkdir(parents=True)
    (out / "场景").mkdir(parents=True)
    (out / "物品").mkdir(parents=True)
    (out / "人物" / "a.png").write_bytes(b"1")
    (out / "场景" / "b.png").write_bytes(b"2")
    legacy = out / "legacy_id"
    legacy.mkdir(parents=True)
    (legacy / "full.png").write_bytes(b"3")
    project = Project(id="p1", title="t", style="s", source_text="x", image_output_dir=str(out))
    chars = list_image_output_files(project, kind="character")
    assert all(f.get("folder") == "人物" for f in chars)
    assert any(f["name"] == "a.png" for f in chars)
    assert not any(f["name"] == "full.png" for f in chars)
    all_files = list_image_output_files(project)
    assert {f["name"] for f in all_files} == {"a.png", "b.png"}
