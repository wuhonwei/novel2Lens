from __future__ import annotations

"""Facade: re-export service APIs so `from app.services import X` keeps working."""

from app.llm import OperationCancelled, chat_json, ensure_not_cancelled  # noqa: F401
from app.registry_ops import (  # noqa: F401
    APPEARANCE_KEYS,
    MAX_REGISTRY_AUDIT_PASSES,
    NOVEL_SCAN_CHARS,
    confirm_proposals,
    detach_shot_asset_refs,
    extract_assets,
    full_registry_scan,
    merge_assets,
    prescan_project,
    rebuild_chapters,
    _apply_registry_rows_to_db,
    _asset_dicts,
    _audit_rows,
    _call_llm,
    _find_asset,
    _find_db_asset,
    _merge_appearance,
    _normalize_proposals,
    _pass1_rows,
    _registry,
)
from app.serialize import (  # noqa: F401
    asset_ref_ready,
    missing_asset_image_messages,
    require_asset_images,
    serialize_asset,
    serialize_chapter,
    serialize_project,
    serialize_shot,
    _asset_media_version,
    _dump,
    _effective_far_path,
    _load,
    _uid,
)
from app.storyboard_ops import (  # noqa: F401
    LEGACY_DUAL_PORTRAIT_MARKERS,
    compile_shot_prompts,
    export_project,
    generate_all_storyboards,
    generate_storyboard,
    refresh_shot_readiness,
    repair_shot_prompts_if_needed,
    save_upload,
    shot_needs_portrait_repair,
    update_shot,
    _asset_desc,
    _line_portrait_key,
    _match_name,
    _pick_portrait,
    _shot_unready,
)
