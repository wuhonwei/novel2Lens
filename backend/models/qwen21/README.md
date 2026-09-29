# Qwen Image 2.1 GGUF models (hardlinked from the Quark download pack).
# ComfyUI resolves these via its own models/ tree; this folder is the project mirror.
#
# Required files:
# - diffusion_models/qwen-image-2.1-Q8_0.gguf
# - text_encoders/qwen3vl_8b_bf16.safetensors
# - vae/qwen_image_2.1_vae_bf16.safetensors
#
# Image Comfy defaults to:
#   D:\Comfy-Desktop\ComfyUI-Installs\qwen-image-2.1\ComfyUI  (:8189)
#
# One-time: install ComfyUI-GGUF deps in that Comfy venv:
#   .venv\Scripts\python.exe -m pip install "gguf>=0.13.0" sentencepiece protobuf
