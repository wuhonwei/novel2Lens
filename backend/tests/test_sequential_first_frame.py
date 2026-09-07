"""Sequential multi-char first-frame — FakeComfy records uploads/locks/rebinds."""
from __future__ import annotations

from pathlib import Path

from app.db import ImageJob
from app.sequential_first_frame import run_sequential_multi_char_first_frame


TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


class RecordingComfy:
    def __init__(self) -> None:
        self.uploads: list[str] = []
        self.queue_calls = 0
        self.prompts: list[str] = []
        self.ref_name_batches: list[list[str]] = []

    def upload_image(self, data: bytes, filename: str) -> str:
        self.uploads.append(filename)
        return filename

    def queue_prompt(self, prompt, client_id=None) -> str:
        self.queue_calls += 1
        # compile_qwen_edit packs prompt under node "6" / text
        text = ""
        try:
            text = prompt["20"]["inputs"]["prompt"]
        except Exception:
            text = str(prompt)
        self.prompts.append(text)
        refs = []
        for nid in ("10", "11", "12"):
            try:
                refs.append(prompt[nid]["inputs"]["image"])
            except Exception:
                pass
        self.ref_name_batches.append(refs)
        return f"p{self.queue_calls}"

    def wait_history(self, prompt_id: str, timeout_seconds: float = 600.0):
        return {
            "outputs": {
                "9": {"images": [{"filename": f"{prompt_id}.png", "subfolder": "", "type": "output"}]}
            }
        }

    def collect_images(self, history_entry):
        return [TINY_PNG]


def _write_refs(tmp: Path, n: int) -> tuple[list[str], list[str]]:
    paths: list[str] = []
    labels: list[str] = []
    for i in range(n):
        p = tmp / f"person{i}.png"
        p.write_bytes(TINY_PNG)
        paths.append(str(p))
        labels.append(f"人物{i + 1}·youth")
    return paths, labels


def test_two_person_sequential_uploads_plate_lock_new(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.sequential_first_frame.assess_image_bytes",
        lambda *a, **k: {"ok": True, "passed": True, "reasons": []},
    )
    monkeypatch.setattr(
        "app.sequential_first_frame.assess_companion_added",
        lambda *a, **k: None,
    )
    paths, labels = _write_refs(tmp_path, 2)
    client = RecordingComfy()
    job = ImageJob(
        id="job-2p",
        project_id="p",
        asset_id="",
        kind="edit",
        target_field="first_frame",
        prompt="两人站立",
        status="running",
        phase="",
        payload_json="{}",
    )
    phases: list[str] = []
    out = run_sequential_multi_char_first_frame(
        client=client,
        job=job,
        payload={},
        ref_paths=paths,
        ref_labels=labels,
        edit_prompt="两人站立",
        aspect="16:9",
        width=1280,
        height=720,
        job_timeout=30.0,
        set_phase=phases.append,
    )
    assert out == TINY_PNG
    # stage1 (1 ref) + stage2 (plate+lock+new = 3)
    assert client.queue_calls == 2
    assert any("seq_p1/2" in p for p in phases)
    assert any("seq_p2/2" in p for p in phases)
    assert "person0.png" in client.uploads
    assert "person1.png" in client.uploads
    assert any(n.startswith("plate_") for n in client.uploads)


def test_three_person_keeps_newest_lock_then_rebinds_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.sequential_first_frame.assess_image_bytes",
        lambda *a, **k: {"ok": True, "passed": True, "reasons": []},
    )
    monkeypatch.setattr(
        "app.sequential_first_frame.assess_companion_added",
        lambda *a, **k: None,
    )
    paths, labels = _write_refs(tmp_path, 3)
    client = RecordingComfy()
    job = ImageJob(
        id="job-3p",
        project_id="p",
        asset_id="",
        kind="edit",
        target_field="first_frame",
        prompt="三人站立",
        status="running",
        phase="",
        payload_json="{}",
    )
    phases: list[str] = []
    out = run_sequential_multi_char_first_frame(
        client=client,
        job=job,
        payload={},
        ref_paths=paths,
        ref_labels=labels,
        edit_prompt="三人站立",
        aspect="16:9",
        width=1280,
        height=720,
        job_timeout=30.0,
        set_phase=phases.append,
    )
    assert out == TINY_PNG
    # p1 place + p2 add + p3 add + rebind dropped person0 = 4 prompts
    assert client.queue_calls == 4
    assert any("REBIND" in p or "rebind" in p.lower() for p in client.prompts)
    assert any("seq_rebind_p1" in p for p in phases)
    # When adding person 3 (index 2), lock should be newest placed (person1), not person0
    add_p3_batches = [
        b for b, prompt in zip(client.ref_name_batches, client.prompts) if "COMPOSITE ADD" in prompt and "image 3" in prompt
    ]
    # Last COMPOSITE ADD is person3; refs = plate, lock(person1), new(person2)
    last_add = [b for b, prompt in zip(client.ref_name_batches, client.prompts) if "COMPOSITE ADD" in prompt][-1]
    assert "person1.png" in last_add  # newest lock
    assert "person2.png" in last_add  # new person
    assert "person0.png" not in last_add  # dropped from visual lock; rebound later
    assert any("rebind" in u for u in client.uploads)
