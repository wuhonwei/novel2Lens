from __future__ import annotations

from dataclasses import dataclass, field


POSITIONS = ("左一", "中", "右一")
FACINGS = (
    "面向镜头",
    "朝左",
    "朝右",
    "背对镜头",
    "面向左一",
    "面向中",
    "面向右一",
)
CAMERAS = (
    "固定",
    "缓慢推近",
    "缓慢拉远",
    "慢摇左",
    "慢摇右",
    "微仰",
    "微俯",
    "轻度跟随左一",
    "轻度跟随中",
    "轻度跟随右一",
)
VARIANT_REASONS = ("outfit", "age", "injury", "season", "other")
H3_ENCODER = "qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors"


def max_named_characters(has_scene: bool) -> int:
    return 2 if has_scene else 3


@dataclass
class SlotSubject:
    asset_id: str
    kind: str = "character"
    position: str | None = None
    facing: str | None = None
    image_key: str = "full"
    refer_as: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class PackedSlot:
    index: int  # 1-based: 图一 / image 1
    kind: str  # scene | character | prop
    asset_id: str | None = None
    position: str | None = None
    facing: str | None = None
    image_key: str = "full"
    refer_as: str = ""


def pack_qwen_slots(
    *,
    has_scene: bool,
    characters: list[SlotSubject],
    half_lock: bool = False,
    prop: SlotSubject | None = None,
) -> list[PackedSlot]:
    cap = max_named_characters(has_scene)
    if len(characters) > cap:
        raise ValueError(f"具名出镜人物不能超过 {cap} 人（有场景时最多 2 人）")

    slots: list[PackedSlot] = []
    n = 1
    if has_scene:
        slots.append(PackedSlot(index=n, kind="scene", image_key="scene"))
        n += 1

    for char in characters:
        slots.append(
            PackedSlot(
                index=n,
                kind="character",
                asset_id=char.asset_id,
                position=char.position,
                facing=char.facing,
                image_key=char.image_key or "full",
                refer_as=char.refer_as,
            )
        )
        n += 1

    if has_scene and len(characters) == 1 and half_lock and n <= 3:
        slots.append(
            PackedSlot(
                index=n,
                kind="character",
                asset_id=characters[0].asset_id,
                position=characters[0].position,
                facing=characters[0].facing,
                image_key="half",
                refer_as=characters[0].refer_as,
            )
        )
        n += 1

    if (
        prop
        and not has_scene
        and len(characters) <= 2
        and n <= 3
    ):
        slots.append(
            PackedSlot(
                index=n,
                kind="prop",
                asset_id=prop.asset_id,
                image_key=prop.image_key or "prop",
            )
        )

    return slots[:3]
