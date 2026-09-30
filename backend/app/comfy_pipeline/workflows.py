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
    "guofeng_cg_male": (
        "stylized 3D CGI donghua male character, Unreal Engine 5, octane render, "
        "masculine Chinese historical hero look, ancient Chinese costume or jianghu outfit, "
        "hanfu or martial robe, soft cinematic glow, ultra detailed hair strands, masterpiece, "
        "NOT a real photo, NOT modern clothing"
    ),
    "guofeng_cg_elder": (
        "stylized 3D CGI donghua elderly character, Unreal Engine 5, octane render, "
        "aged wrinkled face, gray-white hair, traditional Chinese costume, "
        "soft cinematic glow, masterpiece, NOT a young idol face, NOT a real photo"
    ),
    "guofeng_cg_fullbody": (
        "stylized 3D CGI donghua full-body character standing, Unreal Engine 5, "
        "octane render, entire figure head to toe in frame, visible shoes, "
        "soft cinematic glow, masterpiece"
    ),
    "guofeng_cg_male_fullbody": (
        "stylized 3D CGI donghua full-body male character standing, Unreal Engine 5, "
        "octane render, ancient Chinese / jianghu costume, entire figure head to toe, "
        "visible period shoes, soft cinematic glow, masterpiece, NOT modern clothes, NOT photoreal"
    ),
    "guofeng_cg_elder_fullbody": (
        "stylized 3D CGI donghua full-body elderly character standing, Unreal Engine 5, "
        "octane render, traditional Chinese costume, wrinkled aged face, "
        "entire figure head to toe, soft cinematic glow, masterpiece, NOT young, NOT photoreal"
    ),
    "anime": "anime style, clean lineart, vibrant colors, detailed eyes",
    "product": "product photography, studio softbox lighting, clean background",
    "scenery": (
        "cinematic empty landscape plate, atmospheric perspective, rich depth, "
        "deserted location, no people, no characters, no human figures"
    ),
    "concept": "concept art, design sheet, clear silhouette, masterful composition",
}

GUOFENG_PERIOD_NEGATIVE = (
    "modern clothes, contemporary fashion, blue dress shirt, jeans, chinos, sneakers, "
    "suit, necktie, photorealistic photo, real photograph, DSLR photo, studio catalog photo, "
    "western business casual, t-shirt, hoodie"
)

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


def build_positive(
    prompt: str,
    style: str,
    *,
    gender: str = "unknown",
    age_tier: str = "unknown",
) -> str:
    key = style
    if style == "guofeng_cg":
        full = is_fullbody_prompt(prompt)
        if age_tier == "elder":
            key = "guofeng_cg_elder_fullbody" if full else "guofeng_cg_elder"
        elif gender == "male":
            key = "guofeng_cg_male_fullbody" if full else "guofeng_cg_male"
        elif full:
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


def compile_qwen21_t2i(
    *,
    prompt: str,
    negative: str = "",
    width: int,
    height: int,
    seed: int,
    steps: int | None = None,
    cfg: float | None = None,
    unet_name: str | None = None,
    clip_name: str | None = None,
    vae_name: str | None = None,
    resolution: int | None = None,
    workflows_dir: Path | None = None,
) -> dict[str, Any]:
    """Qwen Image 2.1 GGUF text-to-image (jailbreak t2i workflow)."""
    from app.config import settings

    wf_dir = workflows_dir or WORKFLOWS_DIR
    wf = load_workflow(wf_dir, "qwen_image_2_1_t2i_gguf_api_v1.json")
    wf["1"]["inputs"]["unet_name"] = unet_name or settings.qwen21_unet_name
    wf["2"]["inputs"]["clip_name"] = clip_name or settings.qwen21_clip_name
    wf["3"]["inputs"]["vae_name"] = vae_name or settings.qwen21_vae_name
    wf["4"]["inputs"]["prompt"] = prompt
    wf["4"]["inputs"]["negative_prompt"] = negative or STYLE_DEFAULT_NEGATIVE
    # Prefer the longer edge as encoder resolution hint.
    wf["4"]["inputs"]["resolution"] = int(resolution or max(width, height))
    wf["5"]["inputs"]["width"] = int(width)
    wf["5"]["inputs"]["height"] = int(height)
    wf["5"]["inputs"]["batch_size"] = 1
    wf["6"]["inputs"]["seed"] = int(seed)
    wf["6"]["inputs"]["steps"] = int(steps if steps is not None else settings.qwen21_steps)
    wf["6"]["inputs"]["cfg"] = float(cfg if cfg is not None else settings.qwen21_cfg)
    wf["8"]["inputs"]["filename_prefix"] = "novel2lens_qwen21_t2i"
    return wf


# Qwen Image 2.1 TextEncodeQwenImage21 accepts image_1 … image_10.
MAX_QWEN21_EDIT_REFS = 10
_QWEN21_EDIT_LOAD_IDS = tuple(str(i) for i in range(10, 10 + MAX_QWEN21_EDIT_REFS))


def compile_qwen21_edit(
    *,
    prompt: str,
    negative: str,
    ref_names: list[str],
    seed: int,
    steps: int | None = None,
    cfg: float | None = None,
    width: int | None = None,
    height: int | None = None,
    unet_name: str | None = None,
    clip_name: str | None = None,
    vae_name: str | None = None,
    resolution: int | None = None,
    use_encoder_latent: bool = False,
    workflows_dir: Path | None = None,
) -> dict[str, Any]:
    """Qwen Image 2.1 GGUF edit (flattened jailbreak edit subgraph; ≤10 refs)."""
    from app.config import settings

    wf_dir = workflows_dir or WORKFLOWS_DIR
    wf = load_workflow(wf_dir, "qwen_image_2_1_edit_gguf_api_v1.json")
    names = [n for n in ref_names if n]
    if not names:
        raise ValueError("at least one reference image required")
    if len(names) > MAX_QWEN21_EDIT_REFS:
        raise ValueError(f"Qwen Image 2.1 edit supports at most {MAX_QWEN21_EDIT_REFS} reference images")

    wf["1"]["inputs"]["unet_name"] = unet_name or settings.qwen21_unet_name
    wf["2"]["inputs"]["clip_name"] = clip_name or settings.qwen21_clip_name
    wf["3"]["inputs"]["vae_name"] = vae_name or settings.qwen21_vae_name

    encode_inputs = wf["20"]["inputs"]
    # Clear template image bindings then attach only provided refs.
    for key in list(encode_inputs.keys()):
        if key.startswith("images."):
            encode_inputs.pop(key)
    for i, load_id in enumerate(_QWEN21_EDIT_LOAD_IDS):
        if i < len(names):
            node = wf.get(load_id) or {"class_type": "LoadImage", "inputs": {}}
            node["class_type"] = "LoadImage"
            node.setdefault("inputs", {})["image"] = names[i]
            wf[load_id] = node
            encode_inputs[f"images.image_{i + 1}"] = [load_id, 0]
        else:
            wf.pop(load_id, None)

    encode_inputs["prompt"] = prompt
    encode_inputs["negative_prompt"] = negative or ""
    if width and height:
        encode_inputs["resolution"] = int(resolution or max(width, height))
        wf["30"]["inputs"]["width"] = int(width)
        wf["30"]["inputs"]["height"] = int(height)
        wf["40"]["inputs"]["latent_image"] = ["30", 0]
    elif use_encoder_latent:
        encode_inputs["resolution"] = int(resolution or 1024)
        wf.pop("30", None)
        wf["40"]["inputs"]["latent_image"] = ["20", 2]
    else:
        encode_inputs["resolution"] = int(resolution or 1024)
        wf["40"]["inputs"]["latent_image"] = ["20", 2]
        wf.pop("30", None)

    wf["40"]["inputs"]["seed"] = int(seed)
    wf["40"]["inputs"]["steps"] = int(steps if steps is not None else settings.qwen21_steps)
    wf["40"]["inputs"]["cfg"] = float(cfg if cfg is not None else settings.qwen21_cfg)
    wf["60"]["inputs"]["filename_prefix"] = "novel2lens_qwen21_edit"
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
    """Backward-compatible alias → Qwen Image 2.1 GGUF edit."""
    del use_lightning  # 2.1 jailbreak stack does not use the 2511 Lightning LoRA.
    return compile_qwen21_edit(
        prompt=prompt,
        negative=negative,
        ref_names=ref_names,
        seed=seed,
        steps=steps if steps and steps >= 8 else None,
        cfg=cfg if cfg else None,
        width=width,
        height=height,
        workflows_dir=workflows_dir,
    )


def next_seed(base: int | None, index: int, locked: bool) -> int:
    if base is None:
        return random.randint(0, 2**31 - 1)
    if locked:
        return int(base) + index
    return random.randint(0, 2**31 - 1)
