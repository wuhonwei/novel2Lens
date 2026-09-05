from __future__ import annotations

from dataclasses import dataclass

from app.domain.slots import PackedSlot

CN_NUM = {1: "一", 2: "二", 3: "三"}

FACING_EN = {
    "面向镜头": "facing the camera",
    "朝左": "facing screen-left",
    "朝右": "facing screen-right",
    "背对镜头": "facing away from the camera",
    "面向左一": "facing the leftmost person",
    "面向中": "facing the center person",
    "面向右一": "facing the rightmost person",
}

POS_EN = {
    "左一": "leftmost",
    "中": "center",
    "右一": "rightmost",
}


@dataclass(frozen=True)
class FirstFramePrompts:
    zh: str
    en: str


def _slot_zh(slot: PackedSlot, actions: dict[str, str] | None = None) -> str:
    if slot.kind == "scene":
        return ""
    n = CN_NUM.get(slot.index, str(slot.index))
    if slot.kind == "prop":
        return f"图{n}是核心物品参考，保持其形制与材质。"
    pos = slot.position or "中"
    facing = slot.facing or "面向镜头"
    act = (actions or {}).get(pos, "")
    extra = f"，{act}" if act else ""
    if slot.image_key == "half":
        return f"图{n}是{pos}，{facing}，半身即图{n}人物{extra}。"
    return f"图{n}是{pos}，{facing}，全身即图{n}人物{extra}。"


def _slot_en(slot: PackedSlot, actions: dict[str, str] | None = None) -> str:
    if slot.kind == "scene":
        return ""
    if slot.kind == "prop":
        return f"image {slot.index} is the key prop; keep its shape and material."
    pos = slot.position or "中"
    facing = FACING_EN.get(slot.facing or "面向镜头", "facing the camera")
    act = (actions or {}).get(pos, "")
    extra = f", {act}" if act else ""
    if slot.image_key == "half":
        return (
            f"image {slot.index} is the {POS_EN.get(pos, pos)} person, {facing}, "
            f"upper body as in image {slot.index}{extra}."
        )
    return (
        f"image {slot.index} is the {POS_EN.get(pos, pos)} person, {facing}, "
        f"full body as in image {slot.index}{extra}."
    )


def compile_first_frame(
    *,
    style: str,
    slots: list[PackedSlot],
    character_count: int,
    background: str = "",
    actions: dict[str, str] | None = None,
) -> FirstFramePrompts:
    has_scene = any(s.kind == "scene" for s in slots)

    person_zh = "".join(_slot_zh(s, actions) for s in slots if s.kind != "scene")
    person_en = " ".join(_slot_en(s, actions) for s in slots if s.kind != "scene")

    if has_scene:
        zh = (
            f"画幅16:9。画风：{style}。"
            "以图一为场景底板，保持其空间、光线、陈设，不得换成别的地点。"
            f"在图一的背景下，{person_zh}"
            f"画面中可辨认人物恰好{character_count}人，禁止增加面孔；远处只允许不可辨认剪影。"
            "不要文字、水印、字幕。"
        )
        en = (
            f"16:9. Style: {style}. Use image 1 as the environment plate; keep layout and lighting. "
            f"In the setting of image 1, {person_en} "
            f"Exactly {character_count} identifiable people. No extra faces. No text, no watermark."
        )
        return FirstFramePrompts(zh=zh, en=en)

    bg = background.strip() or "符合画风的环境"
    zh = (
        f"画幅16:9。画风：{style}。按以下描述绘制背景：{bg}。"
        f"{person_zh}"
        f"画面中可辨认人物恰好{character_count}人，禁止增加面孔；远处只允许不可辨认剪影。"
        "不要文字、水印、字幕。"
    )
    en = (
        f"16:9. Style: {style}. Paint the background from this description: {bg}. "
        f"{person_en} "
        f"Exactly {character_count} identifiable people. No extra faces. No text, no watermark."
    )
    return FirstFramePrompts(zh=zh, en=en)


def compile_h3(
    *,
    camera: str,
    camera_detail: str = "",
    character_count: int,
    lines: list[dict],
    narration: str = "",
    audio_tags: list[str] | None = None,
) -> str:
    parts = [
        "<Image 1> 为强参考首帧：保持场景、站位、朝向、服装、外貌和人数不变。",
        f"运镜：{camera}。{camera_detail}".strip(),
    ]
    for line in lines:
        pos = line.get("position") or "中"
        refer = line.get("refer_as") or "人"
        facing = line.get("facing") or "面向镜头"
        action = line.get("action") or ""
        voice = line.get("voice_direction") or ""
        dialogue = line.get("dialogue") or ""
        chunk = f"{pos}的{refer}，{facing}"
        if action:
            chunk += f"，{action}"
        if dialogue:
            voice_bit = f"用{voice}" if voice else "开口"
            chunk += f"，{voice_bit}说道：「{dialogue}」"
        elif voice:
            chunk += f"，声线{voice}"
        chunk += "。"
        parts.append(chunk)
    nar = narration.strip() if narration else "无"
    parts.append(f"旁白（画外音）：{nar}")
    if audio_tags:
        parts.extend(audio_tags)
    parts.append(
        f"画面中可辨认人物始终为 {character_count} 人，禁止新增人物、禁止换脸、禁止换装、禁止换景。"
    )
    return " ".join(p.strip() for p in parts if p and p.strip())
