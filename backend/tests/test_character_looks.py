# -*- coding: utf-8 -*-
from __future__ import annotations

from app.db import Asset, Project, reset_engine
from app.domain.character_looks import (
    clothes_differ,
    expand_character_look_rows,
    normalize_clothes_key,
    score_look_match,
)
from app.image_jobs import _build_asset_field_job
from app.registry_ops import _apply_registry_rows_to_db
from app.services import _uid


def test_expand_looks_splits_variants():
    rows = expand_character_look_rows(
        [
            {
                "kind": "character",
                "name": "林砚之",
                "background": "遗孤",
                "looks": [
                    {
                        "variant_reason": "",
                        "look_zh": "性别：男，年龄段：青年，身材：清瘦，洗白长衫",
                        "appearance": {"gender": "男", "body": "清瘦", "clothing": "洗白长衫"},
                    },
                    {
                        "variant_reason": "outfit",
                        "look_zh": "性别：男，年龄段：青年，身材：清瘦，黑色劲装",
                        "appearance": {"gender": "男", "body": "清瘦", "clothing": "黑色劲装"},
                    },
                ],
            }
        ]
    )
    assert len(rows) == 2
    assert rows[0].get("action") != "clone_variant"
    assert rows[0]["appearance"]["clothing"] == "洗白长衫"
    assert rows[1]["action"] == "clone_variant"
    assert rows[1]["variant_reason"] == "outfit"
    assert rows[1]["appearance"]["clothing"] == "黑色劲装"


def test_clothes_differ_and_score():
    assert clothes_differ("洗白长衫", "黑色劲装")
    assert not clothes_differ("身穿黑色劲装", "黑色劲装")
    assert score_look_match("黑色劲装", "少年黑衣", "黑衣劲装") >= 4
    assert normalize_clothes_key("身穿洗白长衫") == "洗白长衫"


def test_apply_registry_creates_parent_and_variant(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 'looks.sqlite'}")
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        pid = _uid()
        p = Project(id=pid, title="t", style="国漫3D", source_text="x")
        db.add(p)
        db.commit()
        existing: list[Asset] = []
        created, _updated = _apply_registry_rows_to_db(
            db,
            p,
            "",
            [
                {
                    "kind": "character",
                    "name": "林砚之",
                    "refer_as": "少年",
                    "background": "遗孤",
                    "looks": [
                        {
                            "look_zh": "性别：男，年龄段：青年，身材：清瘦，洗白长衫",
                            "appearance": {"gender": "男", "body": "清瘦", "clothing": "洗白长衫"},
                            "age_band": "青年",
                        },
                        {
                            "variant_reason": "outfit",
                            "look_zh": "性别：男，年龄段：青年，身材：清瘦，黑色劲装",
                            "appearance": {"gender": "男", "body": "清瘦", "clothing": "黑色劲装"},
                            "age_band": "青年",
                        },
                    ],
                }
            ],
            existing,
        )
        db.commit()
        assert created >= 2
        roots = [a for a in existing if not a.parent_id]
        variants = [a for a in existing if a.parent_id]
        assert len(roots) == 1
        assert len(variants) == 1
        assert variants[0].parent_id == roots[0].id
        assert "黑" in (variants[0].desc_zh or "" + str(variants[0].appearance_json))
    finally:
        db.close()


def test_variant_full_job_edits_from_parent(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.data_dir", tmp_path)
    reset_engine(f"sqlite:///{tmp_path / 'vjob.sqlite'}")
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        pid = _uid()
        p = Project(id=pid, title="t", style="国漫3D", source_text="x")
        parent = Asset(
            id=_uid(),
            project_id=pid,
            kind="character",
            name="林砚之",
            desc_zh="性别：男，年龄段：青年，身材：清瘦，洗白长衫",
            appearance_json='{"gender":"男","body":"清瘦","clothing":"洗白长衫"}',
            full_path=f"assets/{pid}/parent_full.png",
            confirmed=True,
        )
        child = Asset(
            id=_uid(),
            project_id=pid,
            kind="character",
            name="林砚之",
            parent_id=parent.id,
            variant_reason="outfit",
            desc_zh="性别：男，年龄段：青年，身材：清瘦，黑色劲装",
            appearance_json='{"gender":"男","body":"清瘦","clothing":"黑色劲装"}',
            confirmed=True,
        )
        db.add_all([p, parent, child])
        db.commit()
        job = _build_asset_field_job(p, child, "full", db=db)
        assert job.kind == "edit"
        assert job.target_field == "full"
        import json

        payload = json.loads(job.payload_json)
        assert payload.get("from_parent_variant") is True
        assert payload.get("ref_asset_id") == parent.id
        assert payload.get("ref_field") == "full"
    finally:
        db.close()
