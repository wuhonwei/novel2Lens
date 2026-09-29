"""Smoke: start Qwen 2.1 Comfy and run one tiny T2I + one-edit compile validation."""
from __future__ import annotations

import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.comfy_pipeline.comfy import ComfyClient
from app.comfy_pipeline.workflows import compile_qwen21_edit, compile_qwen21_t2i
from app.comfy_supervisor import ComfySupervisor
from app.config import settings


def main() -> int:
    print("comfy_root", settings.comfy_root)
    print("unet", settings.qwen21_unet_name)
    models = Path(settings.comfy_root) / "models"
    for rel in [
        f"diffusion_models/{settings.qwen21_unet_name}",
        f"text_encoders/{settings.qwen21_clip_name}",
        f"vae/{settings.qwen21_vae_name}",
    ]:
        p = models / rel
        print("model", rel, "ok" if p.is_file() else "MISSING", p.stat().st_size if p.is_file() else "")

    comfy = ComfySupervisor(
        base_url=settings.comfy_base_url,
        root=settings.comfy_root,
        python=settings.comfy_python,
        idle_seconds=3600,
        stop_when_idle=False,
        ready_timeout_seconds=300,
    )
    print("ensuring Comfy…")
    comfy.ensure_running()
    client = ComfyClient(settings.comfy_base_url)
    health = client.health()
    print("health", health)

    # Node presence
    import httpx

    for node in ("UnetLoaderGGUF", "TextEncodeQwenImage21", "QwenImage21Cache"):
        r = httpx.get(f"{settings.comfy_base_url}/object_info/{node}", timeout=30.0)
        print("node", node, r.status_code, "ok" if r.status_code == 200 and node in r.json() else "FAIL")

    # Tiny T2I
    wf = compile_qwen21_t2i(
        prompt="simple Chinese ink sketch of a tea cup, white background",
        negative="people, text",
        width=512,
        height=512,
        seed=123,
        steps=8,
        cfg=1.0,
    )
    print("queue t2i…")
    t0 = time.time()
    pid = client.queue_prompt(wf)
    hist = client.wait_history(pid, timeout_seconds=900)
    imgs = client.collect_images(hist)
    print(f"t2i done in {time.time()-t0:.1f}s images={len(imgs)}")
    if not imgs:
        print("FAIL no t2i images")
        return 1
    out = Path("scripts/_qwen21_smoke_t2i.png")
    out.write_bytes(imgs[0])
    print("wrote", out, len(imgs[0]))

    # Edit: use t2i result as ref
    ref = Image.open(out).convert("RGB")
    ref_path = Path("scripts/_qwen21_smoke_ref.png")
    ref.save(ref_path)
    uploaded = client.upload_image(ref_path.read_bytes(), "qwen21_smoke_ref.png")
    ewf = compile_qwen21_edit(
        prompt="Using image 1, keep the tea cup, add soft warm light.",
        negative="people",
        ref_names=[uploaded],
        seed=456,
        steps=8,
        cfg=1.0,
        width=512,
        height=512,
    )
    print("queue edit…")
    t1 = time.time()
    epid = client.queue_prompt(ewf)
    ehist = client.wait_history(epid, timeout_seconds=900)
    eimgs = client.collect_images(ehist)
    print(f"edit done in {time.time()-t1:.1f}s images={len(eimgs)}")
    if not eimgs:
        print("FAIL no edit images")
        return 1
    eout = Path("scripts/_qwen21_smoke_edit.png")
    eout.write_bytes(eimgs[0])
    print("wrote", eout, len(eimgs[0]))
    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
