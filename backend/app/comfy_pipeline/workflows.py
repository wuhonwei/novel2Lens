from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from app.comfy_pipeline.character_prompt import is_fullbody_prompt
from app.comfy_pipeline.ideogram_prompt import build_ideogram_caption


WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / "workflows"

ASPECT_TO_SIZE = {
    # Ideogram / Flux2-ish sweet spots
    "ideogram": {
        "1:1": (1024, 1024),
        "3:4": (896, 1152),
        "4:3": (1152, 896),
        "16:9": (1344, 768),
        "9:16": (768, 1344),
    },
    "sdxl": {
        "1:1": (1024, 1024),
        "3:4": (832, 1216),
        "4:3": (1216, 832),
        "16:9": (1344, 768),
        "9:16": (768, 1344),
        # 全身专用：加高画布，给脚部留边
        "9:16_fullbody": (704, 1472),
    },
}

QUALITY_PARAMS = {
    "fast": {"steps": 12, "cfg": 5.5, "ideogram_steps": 12},
    "standard": {"steps": 20, "cfg": 7.0, "ideogram_steps": 20},
    "high": {"steps": 28, "cfg": 7.5, "ideogram_steps": 28},
}

STYLE_SUFFIX = {
    "realistic": "photorealistic, natural lighting, highly detailed, 8k",
    "guofeng": "中国风, 工笔与写意结合, 精致服饰纹样, cinematic",
    "guofeng_cg": (
        "stylized 3D CGI donghua character, Unreal Engine 5, octane render, "
        "doll-like idealized face, soft cinematic glow, smooth porcelain skin, "
        "ultra detailed hair strands, masterpiece"
    ),
    "guofeng_cg_fullbody": (
        "stylized 3D CGI donghua full-body character standing, Unreal Engine 5, "
        "octane render, entire figure head to toe in frame, visible shoes, "
        "soft cinematic glow, masterpiece"
    ),
    "anime": "anime style, clean lineart, vibrant colors, detailed eyes",
    "product": "product photography, studio softbox lighting, clean background",
    "scenery": "cinematic landscape, atmospheric perspective, rich depth",
    "concept": "concept art, design sheet, clear silhouette, masterful composition",
}

STYLE_DEFAULT_NEGATIVE = (
    "blurry, low quality, deformed, extra fingers, watermark, text artifacts, "
    "oversaturated, ugly, jpeg artifacts"
)


def load_workflow(workflows_dir: Path, name: str) -> dict[str, Any]:
    path = workflows_dir / name
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("_meta", None)
    return data


def resolve_size(aspect: str, backend: str = "sdxl") -> tuple[int, int]:
    table = ASPECT_TO_SIZE["ideogram" if backend == "ideogram4" else "sdxl"]
    return table.get(aspect, table["1:1"])


CKPT_REALVIS = "RealVisXL_V5.0_fp16.safetensors"
CKPT_GUOFENG = "Guofeng4.2XL.safetensors"
CKPT_ANIME = "animagine-xl-4.0-opt.safetensors"
IDEO_UNET = "ideogram4_fp8_scaled.safetensors"

BACKEND_CKPT = {
    "sdxl_realvis": CKPT_REALVIS,
    "sdxl_guofeng": CKPT_GUOFENG,
    "sdxl_anime": CKPT_ANIME,
}


def pick_t2i_backend(
    style: str,
    quality: str,
    models_dir: Path,
    prompt: str = "",
    subject_type: str = "scenery",
    available_ckpts: set[str] | None = None,
) -> str:
    """Route by explicit subject_type first, then style.

    When available_ckpts is set (from live ComfyUI), only route to models Comfy can load.
    Disk existence alone is not enough — a wrong Comfy instance on :8189 can see [].
    """

    def _ckpt(name: str) -> bool:
        if available_ckpts is not None:
            return name in available_ckpts
        return (models_dir / "checkpoints" / name).exists()

    has_ideo = (models_dir / "diffusion_models" / IDEO_UNET).exists()
    has_guofeng = _ckpt(CKPT_GUOFENG)
    has_realvis = _ckpt(CKPT_REALVIS)
    has_anime = _ckpt(CKPT_ANIME)

    if subject_type == "character":
        if style == "guofeng_cg":
            if is_fullbody_prompt(prompt):
                if has_guofeng:
                    return "sdxl_guofeng"
                if has_realvis:
                    return "sdxl_realvis"
            if has_guofeng:
                return "sdxl_guofeng"
            if has_anime:
                return "sdxl_anime"
            if has_realvis:
                return "sdxl_realvis"
            raise ValueError(
                "ComfyUI 未加载任何人物模型（checkpoints 为空）。请确认 8189 是 D:\\Develop\\ComfyUI，"
                "而不是 Comfy Desktop 共享目录。"
            )
        if is_fullbody_prompt(prompt) and has_realvis:
            if style == "anime" and has_anime:
                return "sdxl_anime"
            return "sdxl_realvis"
        if style == "anime" and has_anime:
            return "sdxl_anime"
        if style == "guofeng" and has_guofeng and not is_fullbody_prompt(prompt):
            return "sdxl_guofeng"
        if has_realvis:
            return "sdxl_realvis"
        if has_guofeng:
            return "sdxl_guofeng"
        if has_anime:
            return "sdxl_anime"
        raise ValueError(
            "ComfyUI 未加载任何 SDXL 检查点（ckpt_name list 为空）。"
            "请重启造像 start.bat，确保 8189 指向 D:\\Develop\\ComfyUI。"
        )

    if has_ideo and style in {"scenery", "realistic", "product", "concept"}:
        return "ideogram4"
    if quality == "fast" and has_realvis:
        return "sdxl_realvis"
    if has_realvis:
        return "sdxl_realvis"
    if has_guofeng:
        return "sdxl_guofeng"
    if has_ideo:
        return "ideogram4"
    if has_anime:
        return "sdxl_anime"
    raise ValueError(
        "ComfyUI 未加载可用模型。请确认端口 8189 运行的是 D:\\Develop\\ComfyUI（models\\checkpoints 含 RealVis/Guofeng）。"
    )


def ckpt_for_backend(backend: str) -> str | None:
    return BACKEND_CKPT.get(backend)


def build_positive(prompt: str, style: str) -> str:
    key = style
    if style == "guofeng_cg" and is_fullbody_prompt(prompt):
        key = "guofeng_cg_fullbody"
    suffix = STYLE_SUFFIX.get(key) or STYLE_SUFFIX.get(style, "")
    base = (prompt or "").strip()
    return f"{base}, {suffix}" if suffix else base


def compile_ideogram_t2i(
    *,
    prompt: str,
    negative: str,
    width: int,
    height: int,
    seed: int,
    steps: int,
    cfg: float,
    batch: int = 1,
    style: str = "scenery",
    workflows_dir: Path | None = None,
) -> dict[str, Any]:
    wf_dir = workflows_dir or WORKFLOWS_DIR
    wf = load_workflow(wf_dir, "ideogram4_t2i_api_v1.json")
    caption = build_ideogram_caption(prompt, width=width, height=height, style=style)
    wf["24"]["inputs"]["text"] = caption
    wf["11"]["inputs"]["width"] = width
    wf["11"]["inputs"]["height"] = height
    wf["11"]["inputs"]["batch_size"] = batch
    wf["17"]["inputs"]["steps"] = steps
    wf["17"]["inputs"]["width"] = width
    wf["17"]["inputs"]["height"] = height
    wf["18"]["inputs"]["noise_seed"] = seed
    wf["155"]["inputs"]["cfg"] = cfg
    wf["158"]["inputs"]["filename_prefix"] = "novel2lens_ideo"
    return wf


def compile_sdxl_t2i(
    *,
    ckpt: str,
    prompt: str,
    negative: str,
    width: int,
    height: int,
    seed: int,
    steps: int,
    cfg: float,
    batch: int = 1,
    workflows_dir: Path | None = None,
) -> dict[str, Any]:
    wf_dir = workflows_dir or WORKFLOWS_DIR
    wf = load_workflow(wf_dir, "sdxl_t2i_api_v1.json")
    wf["4"]["inputs"]["ckpt_name"] = ckpt
    wf["5"]["inputs"]["width"] = width
    wf["5"]["inputs"]["height"] = height
    wf["5"]["inputs"]["batch_size"] = batch
    wf["6"]["inputs"]["text"] = prompt
    wf["7"]["inputs"]["text"] = negative or STYLE_DEFAULT_NEGATIVE
    wf["3"]["inputs"]["seed"] = seed
    wf["3"]["inputs"]["steps"] = steps
    wf["3"]["inputs"]["cfg"] = cfg
    wf["9"]["inputs"]["filename_prefix"] = "novel2lens_sdxl"
    return wf


def compile_qwen_edit(
    *,
    prompt: str,
    negative: str,
    ref_names: list[str],
    seed: int,
    steps: int = 4,
    cfg: float = 1.0,
    use_lightning: bool = True,
    width: int | None = None,
    height: int | None = None,
    workflows_dir: Path | None = None,
) -> dict[str, Any]:
    wf_dir = workflows_dir or WORKFLOWS_DIR
    wf = load_workflow(wf_dir, "qwen_image_edit_2511_api_v1.json")
    names = list(ref_names)
    if not names:
        raise ValueError("at least one reference image required")
    while len(names) < 3:
        names.append(names[-1])
    wf["10"]["inputs"]["image"] = names[0]
    wf["11"]["inputs"]["image"] = names[1]
    wf["12"]["inputs"]["image"] = names[2]
    wf["20"]["inputs"]["prompt"] = prompt
    wf["21"]["inputs"]["prompt"] = negative or ""
    wf["40"]["inputs"]["seed"] = seed
    wf["40"]["inputs"]["steps"] = steps
    wf["40"]["inputs"]["cfg"] = cfg
    if width and height:
        wf["35"] = {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": int(width), "height": int(height), "batch_size": 1},
        }
        wf["40"]["inputs"]["latent_image"] = ["35", 0]
    if not use_lightning:
        wf["4"]["inputs"]["strength_model"] = 0.0
        wf["40"]["inputs"]["steps"] = max(steps, 20)
        wf["40"]["inputs"]["cfg"] = max(cfg, 2.5)
    wf["60"]["inputs"]["filename_prefix"] = "novel2lens_edit"
    return wf


def next_seed(base: int | None, index: int, locked: bool) -> int:
    if base is None:
        return random.randint(0, 2**31 - 1)
    if locked:
        return int(base) + index
    return random.randint(0, 2**31 - 1)
