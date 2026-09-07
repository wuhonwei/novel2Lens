from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # Override via N2L_COMFY_ROOT / N2L_COMFY_PYTHON when the install is elsewhere.
    comfy_root: str = r"D:\Develop\ComfyUI"
    comfy_python: str = r"D:\Develop\ComfyUI\venv\Scripts\python.exe"
    image_idle_unload_seconds: int = 180
    stop_comfy_when_idle: bool = True
    # Prefer unload (/free) over full Comfy process restart when flipping LLM↔image.
    # Full stop still happens after idle_seconds if stop_comfy_when_idle is True.
    comfy_prefer_unload_over_restart: bool = True
    worker_poll_interval: float = 0.4
    worker_idle_poll_interval: float = 2.0
    llm_settle_seconds: float = 8.0
    # When True, release_for_llm stops the Comfy process; when False, only /free.
    llm_requires_comfy_stop: bool = False


settings = Settings()
