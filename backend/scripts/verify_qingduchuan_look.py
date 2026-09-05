"""Generate book assets for 青渡川 and assert look fields are purely visual."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx

from app.domain.registry import LOOK_BANNED_TERMS, LOOK_EMOTION_WORDS, LOOK_EXPRESSION_MARKERS, sanitize_look_text

API = "http://127.0.0.1:8790"
NOVEL_DIR = Path(r"D:\Develop\aiVedioProducer\docs\novels")

BANNED_SNIPPETS = (
    "皮笑肉不笑",
    "眉眼温柔",
    "神情严肃",
    "神情",
    "神色",
    "神态",
    "表情",
    "温柔",
    "严肃",
    "坚定",
    "迷茫",
    "沉稳",
    "笑靥",
    "老船工",
    "动作沉稳",
    "阴冷",
    "傲慢",
    "狡诈",
    "无助",
)


def find_novel() -> Path:
    for f in NOVEL_DIR.glob("*.txt"):
        head = f.read_text(encoding="utf-8-sig")[:40]
        if "青川渡" in head or "青渡川" in head or "雾锁渡口" in head:
            return f
    raise SystemExit(f"novel not found in {NOVEL_DIR}")


def look_issues(text: str) -> list[str]:
    issues: list[str] = []
    if not text.strip():
        return ["empty_look"]
    for snip in BANNED_SNIPPETS:
        if snip in text:
            issues.append(f"contains:{snip}")
    for w in LOOK_EMOTION_WORDS:
        if w in text:
            issues.append(f"emotion:{w}")
    for m in LOOK_EXPRESSION_MARKERS:
        if m in text:
            issues.append(f"marker:{m}")
    for term in LOOK_BANNED_TERMS:
        if term in text:
            issues.append(f"occupation:{term}")

    def _norm(s: str) -> str:
        return re.sub(r"[，,\s]+", "", s)

    cleaned = sanitize_look_text(text)
    if _norm(cleaned) != _norm(text):
        issues.append("sanitizer_would_change")
    return sorted(set(issues))


def main() -> int:
    novel = find_novel()
    text = novel.read_text(encoding="utf-8-sig")
    print("novel", novel.name, "chars", len(text))

    with httpx.Client(base_url=API, timeout=1200.0) as client:
        health = client.get("/api/health")
        health.raise_for_status()

        files = {"file": (novel.name, text.encode("utf-8"), "text/plain")}
        data = {"title": "青渡川验证", "style": "半写实、东方江湖、电影布光、16:9"}
        up = client.post("/api/projects/upload", data=data, files=files)
        up.raise_for_status()
        body = up.json()
        pid = body["project"]["id"]
        print("project", pid)

        # Point at Flash-Next which is up
        patch = client.patch(
            f"/api/projects/{pid}",
            json={
                "llm_base_url": "http://127.0.0.1:8080/v1",
                "llm_model": "qwen3.8-flash-next",
                "allow_fallback": True,
                "fallback_base_url": "http://127.0.0.1:11434/v1",
                "fallback_model": "qwen2.5:32b",
            },
        )
        patch.raise_for_status()

        print("generating assets (may take several minutes)...")
        gen = client.post(f"/api/projects/{pid}/generate-assets?replace=true")
        if gen.status_code != 200:
            print("generate failed", gen.status_code, gen.text[:2000])
            return 1
        bundle = gen.json()
        chars = [a for a in bundle["assets"] if a.get("kind") == "character"]
        print(
            "characters",
            len(chars),
            "scenes",
            sum(1 for a in bundle["assets"] if a["kind"] == "scene"),
            "props",
            sum(1 for a in bundle["assets"] if a["kind"] == "prop"),
        )

        bad: list[dict] = []
        for a in chars:
            look = a.get("desc_zh") or ""
            appearance = a.get("appearance") or {}
            issues = look_issues(look)
            for k, v in appearance.items():
                issues.extend(f"{k}:{i}" for i in look_issues(str(v)) if i != "empty_look")
            if not look.strip() and not any(appearance.values()):
                issues.append("empty_look")
            print("---", a["name"])
            print("  bg:", (a.get("background_zh") or "")[:120])
            print("  look:", look[:200])
            if issues:
                print("  BAD:", issues)
                bad.append({"name": a["name"], "look": look, "appearance": appearance, "issues": issues})

        out = Path(__file__).resolve().parent / "qingduchuan_look_report.json"
        out.write_text(
            json.dumps({"project_id": pid, "bad": bad, "chars": chars}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print("report", out)
        if bad:
            print(f"FAILED: {len(bad)} characters still have non-visual look text")
            return 2
        print("OK: all character look fields passed visual-only checks")
        return 0


if __name__ == "__main__":
    sys.exit(main())
