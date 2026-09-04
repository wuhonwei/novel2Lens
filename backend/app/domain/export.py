from __future__ import annotations

from typing import Any

EXPORT_VERSION = "1"
H3_ENCODER = "qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors"


def build_export_document(
    *,
    project: dict[str, Any],
    assets: list[dict[str, Any]],
    chapters: list[dict[str, Any]],
    shots: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "version": EXPORT_VERSION,
        "h3_encoder": H3_ENCODER,
        "project": project,
        "assets": assets,
        "chapters": chapters,
        "shots": shots,
    }


def build_shots_markdown(project_title: str, shots: list[dict[str, Any]]) -> str:
    lines = [f"# {project_title} 分镜脚本", ""]
    for shot in shots:
        lines.append(f"## {shot.get('chapter_title') or ''} 镜 {shot.get('order_index')}")
        lines.append(f"- 时长：{shot.get('duration_s')}s　运镜：{shot.get('camera')}")
        lines.append(f"- 人数锁：{shot.get('character_count')}")
        lines.append(f"- 首帧（中文）：{shot.get('prompt_zh')}")
        lines.append(f"- 首帧（英文）：{shot.get('prompt_en')}")
        lines.append(f"- H3：{shot.get('h3_prompt')}")
        lines.append("")
    return "\n".join(lines)
