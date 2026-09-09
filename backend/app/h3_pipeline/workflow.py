from __future__ import annotations

from typing import Any


def _sampler_tail(
    *,
    workflow: dict[str, Any],
    model_ref: list[Any],
    cond_ref: list[Any],
    latent_ref: list[Any],
    steps: int,
    filename_prefix: str,
) -> None:
    workflow["12"] = {
        "class_type": "BasicScheduler",
        "inputs": {
            "model": model_ref,
            "scheduler": "simple",
            "steps": int(steps),
            "denoise": 1.0,
        },
    }
    workflow["13"] = {
        "class_type": "BasicGuider",
        "inputs": {
            "model": model_ref,
            "conditioning": cond_ref,
        },
    }
    workflow["14"] = {
        "class_type": "SamplerCustomAdvanced",
        "inputs": {
            "noise": ["10", 0],
            "guider": ["13", 0],
            "sampler": ["11", 0],
            "sigmas": ["12", 0],
            "latent_image": latent_ref,
        },
    }
    workflow["15"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["14", 0], "vae": ["4", 0]},
    }
    workflow["16"] = {
        "class_type": "VAEDecodeAudio",
        "inputs": {"samples": ["14", 0], "vae": ["5", 0]},
    }
    workflow["17"] = {
        "class_type": "CreateVideo",
        "inputs": {
            "images": ["15", 0],
            "audio": ["16", 0],
            "fps": 24.0,
            "bit_depth": "auto",
            "color_space": "sRGB",
        },
    }
    workflow["18"] = {
        "class_type": "SaveVideo",
        "inputs": {
            "video": ["17", 0],
            "filename_prefix": filename_prefix,
            "format": "auto",
        },
    }


def _base_loaders(
    *,
    clip_name: str,
    video_vae_name: str,
    audio_vae_name: str,
    seed: int,
) -> dict[str, Any]:
    return {
        "3": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": clip_name,
                "type": "minimax",
                "device": "default",
            },
        },
        "4": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": video_vae_name},
        },
        "5": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": audio_vae_name},
        },
        "10": {
            "class_type": "RandomNoise",
            "inputs": {"noise_seed": int(seed)},
        },
        "11": {
            "class_type": "KSamplerSelect",
            "inputs": {"sampler_name": "res_multistep"},
        },
    }


def _attach_unet(
    workflow: dict[str, Any],
    *,
    unet_name: str,
    turbo: bool,
    turbo_lora_name: str,
) -> list[Any]:
    workflow["2"] = {
        "class_type": "UNETLoader",
        "inputs": {"unet_name": unet_name, "weight_dtype": "default"},
    }
    if not turbo:
        return ["2", 0]
    workflow["6"] = {
        "class_type": "LoraLoaderModelOnly",
        "inputs": {
            "model": ["2", 0],
            "lora_name": turbo_lora_name,
            "strength_model": 1.0,
        },
    }
    return ["6", 0]


def build_h3_i2v_workflow(
    *,
    image_filename: str,
    prompt: str,
    width: int,
    height: int,
    length: int,
    seed: int,
    turbo: bool,
    steps: int,
    unet_name: str,
    clip_name: str,
    video_vae_name: str,
    audio_vae_name: str,
    turbo_lora_name: str,
    filename_prefix: str = "video/novel2Lens",
) -> dict[str, Any]:
    """fl2va I2V workflow for MiniMax H3."""
    workflow = _base_loaders(
        clip_name=clip_name,
        video_vae_name=video_vae_name,
        audio_vae_name=audio_vae_name,
        seed=seed,
    )
    workflow["1"] = {
        "class_type": "LoadImage",
        "inputs": {"image": image_filename},
    }
    model_ref = _attach_unet(
        workflow, unet_name=unet_name, turbo=turbo, turbo_lora_name=turbo_lora_name
    )
    workflow["9"] = {
        "class_type": "MiniMaxH3ImageToVideo",
        "inputs": {
            "clip": ["3", 0],
            "vae": ["4", 0],
            "first_frame": ["1", 0],
            "prompt": prompt,
            "width": int(width),
            "height": int(height),
            "length": int(length),
        },
    }
    _sampler_tail(
        workflow=workflow,
        model_ref=model_ref,
        cond_ref=["9", 0],
        latent_ref=["9", 1],
        steps=steps,
        filename_prefix=filename_prefix,
    )
    return workflow
