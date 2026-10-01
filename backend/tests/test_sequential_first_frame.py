"""Sequential multi-char first-frame — FakeComfy records uploads/locks/rebinds."""
from __future__ import annotations

from pathlib import Path

from app.db import ImageJob
from app.sequential_first_frame import (
    run_sequential_multi_char_first_frame,
    should_run_sequential_first_frame,
)


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
        for nid in (str(i) for i in range(10, 20)):
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


def test_three_person_keeps_all_prior_locks_with_ten_slot_budget(tmp_path, monkeypatch):
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
    # With ≤10-ref budget: p1 place + p2 add + p3 add; no rebind (all prior locks fit).
    assert client.queue_calls == 3
    assert not any("REBIND" in p or "rebind" in p.lower() for p in client.prompts)
    last_add = [b for b, prompt in zip(client.ref_name_batches, client.prompts) if "COMPOSITE ADD" in prompt][-1]
    assert "person0.png" in last_add
    assert "person1.png" in last_add
    assert "person2.png" in last_add


def test_should_run_sequential_skips_within_ten_ref_budget():
    assert should_run_sequential_first_frame(person_n=1, scene_n=1, prop_n=0) is False
    assert should_run_sequential_first_frame(person_n=1, scene_n=1, prop_n=1) is False
    assert should_run_sequential_first_frame(person_n=1, scene_n=0, prop_n=0) is False
    # Multi-person fits one Qwen 2.1 call (≤10) — prefer one-shot identity binding.
    assert should_run_sequential_first_frame(person_n=2, scene_n=1, prop_n=0) is False
    assert should_run_sequential_first_frame(person_n=5, scene_n=1, prop_n=2) is False
    assert should_run_sequential_first_frame(person_n=8, scene_n=1, prop_n=1) is False


def test_should_run_sequential_when_person_labels_age_conflict():
    labels = [
        "青川渡·参考场景图",
        "林砚之·少年·无胡须·LIGHT garments as in ref·full-body",
        "陈守义·老人·白须·DARK garments as in ref·full-body",
    ]
    assert (
        should_run_sequential_first_frame(person_n=2, scene_n=1, prop_n=0, ref_labels=labels)
        is True
    )


def test_should_run_sequential_only_when_over_ten_refs():
    assert should_run_sequential_first_frame(person_n=9, scene_n=1, prop_n=1) is True
    assert should_run_sequential_first_frame(person_n=10, scene_n=1, prop_n=0) is True
    assert should_run_sequential_first_frame(person_n=5, scene_n=1, prop_n=5) is True