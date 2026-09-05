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
    zaoxiang_base_url: str = "http://127.0.0.1:8000"
    comfy_base_url: str = "http://127.0.0.1:8189"
    comfy_root: str = r"D:\Develop\ComfyUI"
    comfy_python: str = r"D:\Develop\ComfyUI\venv\Scripts\python.exe"
    image_idle_unload_seconds: int = 180
    stop_comfy_when_idle: bool = True


settings = Settings()
