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

# Per Qwen Edit call hard cap (sequential stages still respect this).
MAX_REF_IMAGES = 3
# Soft ceiling only for legacy callers; packing no longer rejects above this.
MAX_NAMED_CHARACTERS = 99
MAX_MULTI_CHAR_REF_IMAGES = 99


def max_named_characters(has_scene: bool = False) -> int:
    """Soft hint for storyboard UI; sequential packing does not enforce this."""
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
    """Pack reference layers for sequential first-frame stacking.

    Order: scene → characters → props. No people/scene/prop hard cap — ImageWorker
    stacks layers one edit at a time (≤3 images per call). Callers that know which
    assets lack files should move those entries to text_fallbacks after packing.
    """
    del half_lock
    del has_scene

    unique_chars: list[SlotSubject] = []
    seen_ids: set[str] = set()
    for char in characters:
        if char.asset_id in seen_ids:
            continue
        seen_ids.add(char.asset_id)
        unique_chars.append(char)
    characters = unique_chars

    prop_list: list[SlotSubject] = []
    if props:
        prop_list.extend(props)
    elif prop:
        prop_list.append(prop)

    ordered: list[SlotSubject] = []
    if scene and scene.asset_id:
        ordered.append(scene)
    ordered.extend(characters)
    for p in prop_list:
        if p and p.asset_id:
            ordered.append(p)

    slots: list[PackedSlot] = []
    for n, subject in enumerate(ordered, start=1):
        kind = subject.kind
        if kind == "character":
            image_key = normalize_portrait_key(subject.image_key)
        elif kind == "scene":
            image_key = "scene"
        else:
            image_key = subject.image_key or "prop"
            kind = "prop"
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

    return PackResult(slots=slots, text_fallbacks=[])
