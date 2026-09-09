"""Shared prop visual anchors for T2I (ZH brief + EN model lock)."""
from __future__ import annotations

import re

# Chinese shape briefs used in build_field_prompt.
# Keys match by longest substring inside the asset name (exact name first).
PROP_SHAPE_HINTS_ZH: dict[str, str] = {
    "玉佩": "中国古玉佩坠，碧玉或白玉雕成的佩饰，可对半分开的一对玉佩，刻字清晰，桌面静物",
    "文献": "一叠用丝线捆扎的古旧宣纸文书卷轴，纸张纹理可见",
    "木盒": "紫檀木雕花小方盒，合盖静物，可见盒身与盒盖，无挂件",
    "木箱": "深色紫檀木质方形合盖木箱静物，可见锁扣与锁孔，箱体占画面主体",
    "紫檀木箱": "深色紫檀木质方形合盖木箱静物，可见锁扣与锁孔，箱体占画面主体",
    "照片": "旧木相框内一张泛黄老照片纸面静物，照片为平面影像，相框与照片纸占主体",
    "泛黄照片": "旧木相框内一张泛黄老照片纸面静物，照片为平面影像，相框与照片纸占主体",
    "绝笔信": "展开的泛黄宣纸书信静物，墨色字迹工整，纸边可有磨损，纸面占主体",
    "信": "展开的泛黄宣纸书信静物，墨色字迹清晰可见，纸面占主体",
    "地图": "展开铺平的手绘古旧山河地图绢布或厚纸静物，平面地图文书，标注简洁",
    "火折子": "古代火折子点火器具，竹筒或金属小筒形随身火具",
    "乌木船": "乌木或深色硬木雕成的小型木船模型静物，船体、船舷与船桨形制清晰，无人物",
    "千年古松": "一棵苍劲千年古松的微缩盆景式特写，树干与松针清晰",
    "密道": "木门后的狭窄地下密道入口特写，石阶与木框，无人物",
}

# English anchors prepended in the Comfy worker (Guofeng often ignores bare Chinese names).
PROP_SHAPE_HINTS_EN: dict[str, str] = {
    "玉佩": "Chinese carved jade pendant bi disc, nephrite jade ornament",
    "文献": "bound ancient Chinese rice-paper documents scroll stack",
    "木盒": "carved rosewood wooden box, closed lid still life",
    "木箱": "dark rosewood rectangular wooden chest with lock clasp, still life",
    "紫檀木箱": "dark rosewood rectangular wooden chest with lock clasp, still life",
    "照片": "yellowed vintage photograph inside wooden frame, flat paper photo still life",
    "泛黄照片": "yellowed vintage photograph inside wooden frame, flat paper photo still life",
    "绝笔信": "unfolded yellowed Chinese rice-paper letter with ink calligraphy, paper still life",
    "信": "unfolded yellowed Chinese rice-paper letter with ink calligraphy",
    "地图": "unfolded hand-drawn antique mountain map on silk or thick paper, flat document",
    "火折子": "ancient Chinese fire starter tube flint lighter",
    "乌木船": "small dark ebony hardwood carved wooden boat model, clear hull and oars, no people",
    "千年古松": "miniature ancient pine tree bonsai",
    "密道": "narrow wooden secret tunnel doorway entrance",
}


def _longest_key_hit(name: str, table: dict[str, str]) -> str:
    name = (name or "").strip()
    if not name:
        return ""
    if name in table:
        return name
    hits = [k for k in table if k and k in name]
    if not hits:
        return ""
    return max(hits, key=len)


def lookup_prop_shape_zh(name: str) -> str:
    key = _longest_key_hit(name, PROP_SHAPE_HINTS_ZH)
    return PROP_SHAPE_HINTS_ZH.get(key, "")


def lookup_prop_shape_en(name: str) -> str:
    key = _longest_key_hit(name, PROP_SHAPE_HINTS_EN)
    return PROP_SHAPE_HINTS_EN.get(key, "")


def prop_en_anchor(prompt_or_name: str) -> str:
    """Return English anchor if any known prop name appears in the text."""
    return lookup_prop_shape_en(prompt_or_name or "")


def infer_prop_family(name: str) -> str:
    n = name or ""
    if any(k in n for k in ("玉佩", "玉坠", "玉璧")):
        return "jade"
    if any(k in n for k in ("照片", "相片", "相框")):
        return "photo"
    if any(k in n for k in ("绝笔", "书信")) or (n.endswith("信") and "信息" not in n):
        return "letter"
    if "地图" in n:
        return "map"
    if any(k in n for k in ("木箱", "木盒", "匣", "箱子")):
        return "box"
    if any(k in n for k in ("船",)):
        return "boat"
    return "generic"


def scrub_prop_desc(name: str, desc: str) -> str:
    """Keep appearance cues; drop containers / competing prop subjects / staging locations."""
    text = (desc or "").strip()
    if not text:
        return ""
    family = infer_prop_family(name)

    # Drop packaging / location staging that steals the hero object.
    text = re.sub(r"[，,。；;]*装在[^。；;]{0,20}(?:盒|箱|匣|袋|信封)[^。；;]*", "，", text)
    text = re.sub(r"[，,。；;]*置于[^。；;]{0,16}", "，", text)
    text = re.sub(r"[，,。；;]*放在[^。；;]{0,16}", "，", text)
    text = re.sub(r"[，,。；;]*藏于[^。；;]{0,20}", "，", text)
    text = re.sub(r"[，,。；;]*[^。；;]*(?:茅草屋|石室|山洞|桌上|屋内)[^。；;]*", "，", text)

    if family == "box":
        # Keep lock-shape cue, but do not let 玉佩 become the drawn subject.
        text = re.sub(r"锁孔形状与玉佩一致", "锁孔形制特殊", text)
        text = re.sub(r"[，,。；;]*[^。；;]*玉佩[^。；;]*", "，", text)
    elif family == "letter":
        text = re.sub(r"[，,。；;]*[^。；;]*(?:紫檀|木盒|木箱|盒子)[^。；;]*", "，", text)
    elif family == "photo":
        # Keep that it is an old portrait photo; drop live-character staging words.
        text = re.sub(r"[，,。；;]*[^。；;]*(?:站立|坐着|真人)[^。；;]*", "，", text)
    elif family == "map":
        text = re.sub(r"[，,。；;]*[^。；;]*(?:实景|风景写真|航拍)[^。；;]*", "，", text)

    text = re.sub(r"[，,]{2,}", "，", text).strip("，,。；; ")
    return text


def prop_subject_guards(name: str) -> tuple[str, str]:
    """Return (subject_lock_sentence, extra_negatives) for the prop family."""
    family = infer_prop_family(name)
    subject = f"主体只能是「{name}」本身，禁止改画成其他物件。"
    if family == "box":
        return (
            subject + "只画合盖木箱静物；锁孔可特殊，但不要单独画成玉佩或首饰。",
            "禁止玉佩挂件、禁止碧玉圆牌、禁止珠宝首饰特写、禁止盆景。",
        )
    if family == "photo":
        return (
            subject + "主体是相框与泛黄照片纸面；照片内可以是平面旧影像，但必须是平面纸面而非真人立体站立。",
            "禁止真人立体入镜、禁止雕像、禁止玉雕圆球、禁止盆景、禁止风景宽镜头。",
        )
    if family == "letter":
        return (
            subject + "主体是展开或折叠的纸质书信；不要画成装信的木盒。",
            "禁止紫檀木盒、禁止木箱、禁止玉佩、禁止信封堆成箱匣。",
        )
    if family == "map":
        return (
            subject + "主体是展开铺平的平面地图文书。",
            "禁止盆景、禁止雪地松树、禁止风景宽镜头、禁止真山真水实景、禁止把地图画成风景画。",
        )
    if family == "jade":
        return (
            subject + "主体是玉佩佩饰静物。",
            "禁止木箱、禁止人物、禁止风景。",
        )
    return (
        subject,
        "禁止改画成无关器物。",
    )
