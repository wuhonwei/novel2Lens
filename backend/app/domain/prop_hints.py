"""Shared prop visual anchors for T2I (ZH brief + EN model lock)."""
from __future__ import annotations

# Chinese shape briefs used in build_field_prompt.
PROP_SHAPE_HINTS_ZH: dict[str, str] = {
    "玉佩": "中国古玉佩坠，碧玉或白玉雕成的佩饰，可对半分开的一对玉佩，刻字清晰，桌面静物",
    "文献": "一叠用丝线捆扎的古旧宣纸文书卷轴，纸张纹理可见",
    "木盒": "紫檀木雕花小方盒，合盖静物",
    "火折子": "古代火折子点火器具，竹筒或金属小筒形随身火具",
    "乌木船": "乌木或深色硬木雕成的小型木船模型静物，船体、船舷与船桨形制清晰，无人物",
    "千年古松": "一棵苍劲千年古松的微缩盆景式特写，树干与松针清晰",
    "密道": "木门后的狭窄地下密道入口特写，石阶与木框，无人物",
}

# English anchors prepended in the Comfy worker (Guofeng often ignores bare Chinese names).
PROP_SHAPE_HINTS_EN: dict[str, str] = {
    "玉佩": "Chinese carved jade pendant bi disc, nephrite jade ornament",
    "文献": "bound ancient Chinese rice-paper documents scroll stack",
    "木盒": "carved rosewood wooden box",
    "火折子": "ancient Chinese fire starter tube flint lighter",
    "乌木船": "small dark ebony hardwood carved wooden boat model, clear hull and oars, no people",
    "千年古松": "miniature ancient pine tree bonsai",
    "密道": "narrow wooden secret tunnel doorway entrance",
}


def prop_en_anchor(prompt_or_name: str) -> str:
    """Return English anchor if any known prop name appears in the text."""
    for zh, en in PROP_SHAPE_HINTS_EN.items():
        if zh in (prompt_or_name or ""):
            return en
    return ""
