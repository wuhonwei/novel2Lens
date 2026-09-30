from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_H3_ROOT = Path(r"D:\Comfy-Desktop\ComfyUI-Installs\minmaxH3\ComfyUI")
_DEFAULT_SHARED = Path(r"D:\Comfy-Desktop\ComfyUI-Shared")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="N2L_")

    data_dir: Path = Path(__file__).resolve().parents[1].parent / "data"
    host: str = "127.0.0.1"
    port: int = 8790
    default_llm_base_url: str = "http://127.0.0.1:8080/v1"
    default_llm_model: str = "qwen3.8-flash-next"
    fallback_llm_base_url: str = "http://127.0.0.1:11434/v1"
    fallback_llm_model: str = "qwen2.5:32b"
    vision_llm_base_url: str = "http://127.0.0.1:11434/v1"
    vision_llm_model: str = "qwen2.5vl:7b"
    zaoxiang_base_url: str = "http://127.0.0.1:8000"
    comfy_base_url: str = "http://127.0.0.1:8189"
    # Qwen Image 2.1 GGUF stack (jailbreak workflows). Override via N2L_COMFY_ROOT.
    comfy_root: str = r"D:\Comfy-Desktop\ComfyUI-Installs\qwen-image-2.1\ComfyUI"
    comfy_python: str = r"D:\Comfy-Desktop\ComfyUI-Installs\qwen-image-2.1\ComfyUI\.venv\Scripts\python.exe"
    qwen21_unet_name: str = "qwen-image-2.1-Q8_0.gguf"
    qwen21_clip_name: str = "qwen3vl_8b_bf16.safetensors"
    qwen21_vae_name: str = "qwen_image_2.1_vae_bf16.safetensors"
    qwen21_steps: int = 25
    qwen21_cfg: float = 1.0
    image_idle_unload_seconds: int = 1800
    stop_comfy_when_idle: bool = False
    # Prefer unload (/free) over full Comfy process restart when flipping LLM↔image.
    # Full stop still happens after idle_seconds if stop_comfy_when_idle is True.
    comfy_prefer_unload_over_restart: bool = True
    worker_poll_interval: float = 0.4
    worker_idle_poll_interval: float = 2.0
    # Multi-ref Qwen 2.1 edit (≤10 images) can exceed 10 minutes on first load.
    image_job_timeout_s: float = 1800.0
    llm_settle_seconds: float = 8.0
    # When True, release_for_llm stops the Comfy process; when False, only /free.
    llm_requires_comfy_stop: bool = False

    # MiniMax H3 I2V (separate Comfy install / port from image stack).
    h3_comfy_host: str = "127.0.0.1"
    h3_comfy_port: int = 8190
    h3_comfy_root: str = str(_DEFAULT_H3_ROOT)
    h3_comfy_python: str = str(_DEFAULT_H3_ROOT / ".venv" / "Scripts" / "python.exe")
    h3_comfy_main: str = str(_DEFAULT_H3_ROOT / "main.py")
    h3_shared_models: str = str(_DEFAULT_SHARED / "models")
    h3_shared_input: str = str(_DEFAULT_SHARED / "input")
    h3_shared_output: str = str(_DEFAULT_SHARED / "output")
    h3_comfy_ready_timeout_s: float = 180.0
    h3_comfy_poll_interval_s: float = 1.5
    h3_job_poll_interval_s: float = 2.0
    h3_job_timeout_s: float = 3600.0
    h3_unet_name: str = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
    h3_clip_name: str = "qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors"
    h3_video_vae_name: str = "minimax_h3_video_vae_fp16.safetensors"
    h3_audio_vae_name: str = "minimax_h3_audio_vae_fp32.safetensors"
    h3_turbo_lora_name: str = "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"
    # Single-GPU safety: stop H3 Comfy before image/first-frame jobs so Qwen Edit
    # does not compete with H3 UNet + Qwen3-VL for VRAM (OOM freezes the machine).
    h3_stop_for_image: bool = True

    @property
    def h3_comfy_base_url(self) -> str:
        return f"http://{self.h3_comfy_host}:{self.h3_comfy_port}"


settings = Settings()
