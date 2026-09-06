from __future__ import annotations

from dataclasses import dataclass

from app.domain.slots import PackedSlot, TextFallback

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
    n = CN_NUM.get(slot.index, str(slot.index))
    if slot.kind == "scene":
        return f"以图{n}为场景底板，保持其空间、光线、陈设，不得换成别的地点。"
    if slot.kind == "prop":
        return f"图{n}是核心物品参考，保持其形制与材质。"
    pos = slot.position or "中"
    facing = slot.facing or "面向镜头"
    act = (actions or {}).get(pos, "")
    extra = f"，{act}" if act else ""
    who = ""
    if (slot.name or "").strip():
        who = f"「{slot.name}」"
        if (slot.refer_as or "").strip() and slot.refer_as.strip() not in ("人", "人物"):
            who += f"（{slot.refer_as.strip()}）"
    if slot.image_key == "half":
        return f"图{n}是{pos}，{facing}，半身即图{n}人物{who}{extra}。"
    return f"图{n}是{pos}，{facing}，全身即图{n}人物{who}{extra}。"


def _slot_en(slot: PackedSlot, actions: dict[str, str] | None = None) -> str:
    if slot.kind == "scene":
        return (
            f"Use image {slot.index} as the environment plate; keep layout and lighting; "
            "do not change location."
        )
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


def _fallback_zh(item: TextFallback) -> str:
    name = item.name or "未名"
    text = (item.text or "").strip() or "（无详细描述）"
    if item.kind == "scene":
        return f"场景「{name}」无参考图槽，按文字绘制：{text}。"
    if item.kind == "prop":
        return f"核心物品「{name}」无参考图槽，按文字绘制：{text}。"
    pos = item.position or "中"
    return f"{pos}人物「{name}」无参考图槽，按外貌文字绘制：{text}。"


def _fallback_en(item: TextFallback) -> str:
    name = item.name or "unnamed"
    text = (item.text or "").strip() or "(no description)"
    if item.kind == "scene":
        return f"Scene '{name}' has no image slot; paint from text: {text}."
    if item.kind == "prop":
        return f"Prop '{name}' has no image slot; paint from text: {text}."
    pos = POS_EN.get(item.position or "中", item.position or "center")
    return f"{pos} person '{name}' has no image slot; paint from look text: {text}."


def compile_first_frame(
    *,
    style: str,
    slots: list[PackedSlot],
    character_count: int,
    background: str = "",
    actions: dict[str, str] | None = None,
    text_fallbacks: list[TextFallback] | None = None,
) -> FirstFramePrompts:
    scene_slot = next((s for s in slots if s.kind == "scene"), None)
    fallbacks = text_fallbacks or []
    scene_fb = next((f for f in fallbacks if f.kind == "scene"), None)

    parts_zh: list[str] = [f"画幅16:9。画风：{style}。"]
    parts_en: list[str] = [f"16:9. Style: {style}."]

    if scene_slot:
        parts_zh.append(_slot_zh(scene_slot, actions))
        parts_en.append(_slot_en(scene_slot, actions))
    elif scene_fb and scene_fb.text.strip():
        parts_zh.append(_fallback_zh(scene_fb))
        parts_en.append(_fallback_en(scene_fb))
    else:
        bg = background.strip() or "符合画风的环境"
        parts_zh.append(f"按以下描述绘制背景：{bg}。")
        parts_en.append(f"Paint the background from this description: {bg}.")

    for slot in slots:
        if slot.kind == "scene":
            continue
        parts_zh.append(_slot_zh(slot, actions))
        parts_en.append(_slot_en(slot, actions))

    for fb in fallbacks:
        if fb.kind == "scene":
            continue  # already handled above
        parts_zh.append(_fallback_zh(fb))
        parts_en.append(_fallback_en(fb))

    parts_zh.append(
        f"画面中可辨认人物恰好{character_count}人，禁止增加面孔；远处只允许不可辨认剪影。"
        "不要文字、水印、字幕。"
    )
    if character_count >= 2:
        parts_zh.append(
            "每位具名人物必须互不相同，禁止复制同一张脸或同一套服饰到多人。"
            "图一与图二人脸年龄发型必须分别严格跟随各自参考图，禁止把其中一人的脸贴到另一人身上。"
        )
        parts_en.append(
            "Each named person must look distinct; do not clone the same face or outfit onto multiple people. "
            "Follow each reference image for that person's face and age; never paste one face onto the other."
        )
    parts_en.append(
        f"Exactly {character_count} identifiable people. No extra faces. No text, no watermark."
    )
    return FirstFramePrompts(zh="".join(parts_zh), en=" ".join(parts_en))


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
