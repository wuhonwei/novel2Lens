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

MAX_REF_IMAGES = 3
# Sequential first frames place people one-by-one; allow more named faces than one Qwen call.
MAX_NAMED_CHARACTERS = 8
MAX_MULTI_CHAR_REF_IMAGES = 8


def max_named_characters(has_scene: bool = False) -> int:
    """Soft UI/storyboard cap for named people (sequential edit supports up to this)."""
    del has_scene
    return MAX_NAMED_CHARACTERS


def normalize_portrait_key(raw: str | None) -> str:
    """Return 'half' or 'full'. Never both for one person in one shot."""
    key = (raw or "").strip().lower()
    if key in {"half", "bust", "半身", "半身图", "胸像"}:
        return "half"
    return "full"


@dataclass
class SlotSubject:
    asset_id: str
    kind: str = "character"
    position: str | None = None
    facing: str | None = None
    image_key: str = "full"
    refer_as: str = ""
    name: str = ""
    desc_zh: str = ""
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
    name: str = ""


@dataclass
class TextFallback:
    """Asset that belongs to the shot but did not get an image slot."""

    kind: str  # scene | prop | character
    asset_id: str
    image_key: str
    name: str = ""
    position: str = ""
    text: str = ""
    note: str = "文字描述补足"


@dataclass
class PackResult:
    slots: list[PackedSlot]
    text_fallbacks: list[TextFallback]


def pack_qwen_slots(
    *,
    has_scene: bool = False,
    characters: list[SlotSubject],
    half_lock: bool = False,
    prop: SlotSubject | None = None,
    props: list[SlotSubject] | None = None,
    scene: SlotSubject | None = None,
) -> PackResult:
    """Pack reference image slots for a shot.

    Single-character / mixed shots: ≤3 images (Qwen Edit hard cap per call).
    Multi-character (≥2): all character portraits as image slots (≤8); scene/props
    stay text — ImageWorker places people sequentially.
    Overflow beyond the slot budget becomes text_fallbacks.
    """
    del half_lock
    del has_scene  # scene no longer changes character cap or forced first slot

    unique_chars: list[SlotSubject] = []
    seen_ids: set[str] = set()
    for char in characters:
        if char.asset_id in seen_ids:
            continue
        seen_ids.add(char.asset_id)
        unique_chars.append(char)
    characters = unique_chars

    if len(characters) > MAX_NAMED_CHARACTERS:
        raise ValueError(f"具名出镜人物不能超过 {MAX_NAMED_CHARACTERS} 人")

    prop_list: list[SlotSubject] = []
    if props:
        prop_list.extend(props)
    elif prop:
        prop_list.append(prop)

    candidates: list[tuple[int, SlotSubject]] = []
    # priority rank: lower = earlier
    for char in characters:
        candidates.append((0, char))
    # With 2+ named people, keep image slots for faces; describe scene AND props in text.
    # Qwen-Image-Edit often clones/drops a face when a 3rd plate (scene or prop) shares the budget.
    early_text_fallbacks: list[TextFallback] = []
    if scene and scene.asset_id:
        if len(characters) >= 2:
            early_text_fallbacks.append(
                TextFallback(
                    kind="scene",
                    asset_id=scene.asset_id,
                    image_key="scene",
                    name=scene.name or "",
                    position="",
                    text=(scene.desc_zh or "").strip(),
                    note="双人镜优先人物参考槽，场景改文字",
                )
            )
        else:
            candidates.append((1, scene))
    for p in prop_list:
        if not (p and p.asset_id):
            continue
        if len(characters) >= 2:
            early_text_fallbacks.append(
                TextFallback(
                    kind="prop",
                    asset_id=p.asset_id,
                    image_key=p.image_key or "prop",
                    name=p.name or "",
                    position="",
                    text=(p.desc_zh or "").strip(),
                    note="双人镜优先人物参考槽，物品改文字",
                )
            )
        else:
            candidates.append((2, p))

    max_slots = MAX_MULTI_CHAR_REF_IMAGES if len(characters) >= 2 else MAX_REF_IMAGES
    slots: list[PackedSlot] = []
    text_fallbacks: list[TextFallback] = list(early_text_fallbacks)
    n = 1
    for _rank, subject in candidates:
        kind = subject.kind
        if kind == "character":
            image_key = normalize_portrait_key(subject.image_key)
        elif kind == "scene":
            image_key = "scene"
        else:
            image_key = subject.image_key or "prop"
            kind = "prop"

        if n <= max_slots:
            slots.append(
                PackedSlot(
                    index=n,
                    kind=kind,
                    asset_id=subject.asset_id,
                    position=subject.position,
                    facing=subject.facing,
                    image_key=image_key,
                    refer_as=subject.refer_as,
                    name=subject.name or "",
                )
            )
            n += 1
        else:
            text_fallbacks.append(
                TextFallback(
                    kind=kind,
                    asset_id=subject.asset_id,
                    image_key=image_key,
                    name=subject.name or "",
                    position=subject.position or "",
                    text=(subject.desc_zh or "").strip(),
                    note="文字描述补足",
                )
            )

    return PackResult(slots=slots, text_fallbacks=text_fallbacks)
