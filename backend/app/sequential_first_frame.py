"""Serial multi-character first-frame placement (one person per Comfy edit)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from app.comfy_pipeline.qa import assess_companion_added, assess_image_bytes
from app.comfy_pipeline.workflows import compile_qwen_edit, next_seed
from app.db import ImageJob
from app.domain.edit_identity import (
    multi_char_first_frame_negative,
    person_ref_indices,
    standing_slot,
    two_pass_stage1_negative,
    wrap_rebind_identity,
    wrap_sequential_add_person,
    wrap_sequential_place_first,
)
from app.domain.seq_locks import dropped_lock_indices, visual_lock_indices


SetPhase = Callable[[str], None]


def run_sequential_multi_char_first_frame(
    *,
    client: Any,
    job: ImageJob,
    payload: dict[str, Any],
    ref_paths: list[str],
    ref_labels: list[str],
    edit_prompt: str,
    aspect: str,
    width: int,
    height: int,
    job_timeout: float,
    set_phase: SetPhase | None = None,
    session_factory: Callable[[], Any] | None = None,
) -> bytes:
    """Place each named person into the first frame one at a time."""
    idxs = person_ref_indices(ref_labels)
    if len(idxs) < 2:
        idxs = list(range(min(3, len(ref_paths))))
    people: list[tuple[str, bytes, str]] = []
    for i in idxs:
        lab = (ref_labels[i] if i < len(ref_labels) else f"person{i + 1}").strip()
        path = Path(ref_paths[i])
        people.append((lab, path.read_bytes(), path.name or f"person{i + 1}.png"))
    total = len(people)
    if total < 2:
        raise RuntimeError("sequential first_frame needs >=2 person refs")

    def _phase(msg: str) -> None:
        if set_phase:
            set_phase(msg)

    last_err = ""
    max_attempts = 6
    for attempt in range(1, max_attempts + 1):
        steps = 28 + (attempt - 1) * 4
        cfg = min(6.0, 3.5 + (attempt - 1) * 0.4)
        plate: bytes | None = None
        for pi, (lab, raw, fname) in enumerate(people):
            _phase(f"seq_p{pi + 1}/{total}_a{attempt}")
            if pi == 0:
                name0 = client.upload_image(raw, fname)
                wrap = wrap_sequential_place_first(
                    label=lab,
                    edit_prompt=edit_prompt,
                    total_people=total,
                    aspect=aspect,
                    width=width,
                    height=height,
                )
                wf = compile_qwen_edit(
                    prompt=wrap,
                    negative=two_pass_stage1_negative(),
                    ref_names=[name0],
                    seed=next_seed(None, attempt, True),
                    steps=steps,
                    cfg=cfg,
                    use_lightning=False,
                    width=width,
                    height=height,
                )
                pid = client.queue_prompt(wf)
                hist = client.wait_history(pid, timeout_seconds=job_timeout)
                imgs = client.collect_images(hist)
                if not imgs:
                    last_err = "sequential_stage1: no images"
                    plate = None
                    break
                plate = imgs[0]
                qa = assess_image_bytes(
                    plate, require_fullbody=bool(payload.get("require_fullbody"))
                )
                if not (qa.get("ok") or qa.get("passed")):
                    last_err = f"sequential_stage1_qa:{','.join(qa.get('reasons') or [])}"
                    plate = None
                    break
                continue

            assert plate is not None
            prev = plate
            # plate + locks + new ≤ 3 → at most 1 visual lock when adding.
            kept = visual_lock_indices(placed_count=pi, max_lock_slots=1)
            dropped = dropped_lock_indices(placed_count=pi, kept=kept)
            wrap_locks = [people[j][0] for j in kept]
            ref_names: list[str] = [
                client.upload_image(prev, f"plate_{attempt}_p{pi}.png"),
            ]
            for j in kept:
                ref_names.append(
                    client.upload_image(people[j][1], people[j][2] or f"lock{j}.png")
                )
            ref_names.append(client.upload_image(raw, fname))

            keep_note = (
                "KEEP every identifiable person already visible on image 1 with distinct faces "
                "(do not merge or clone them)."
            )
            if dropped:
                drop_names = ", ".join(people[j][0] for j in dropped)
                keep_note += (
                    f" Especially preserve identities of {drop_names} who are already on the plate "
                    "(their reference slots were full — do not overwrite them)."
                )

            wrap = wrap_sequential_add_person(
                base_label=f"composition plate with {pi} person(s) — keep them",
                new_label=lab,
                lock_labels=wrap_locks,
                person_index=pi,
                total_people=total,
                edit_prompt=edit_prompt,
                aspect=aspect,
                width=width,
                height=height,
                plate_keep_note=keep_note,
            )
            wf = compile_qwen_edit(
                prompt=wrap,
                negative=multi_char_first_frame_negative(),
                ref_names=ref_names,
                seed=next_seed(None, attempt + pi * 10, True),
                steps=steps,
                cfg=cfg,
                use_lightning=False,
                width=width,
                height=height,
            )
            pid = client.queue_prompt(wf)
            hist = client.wait_history(pid, timeout_seconds=job_timeout)
            imgs = client.collect_images(hist)
            if not imgs:
                last_err = f"sequential_stage{pi + 1}: no images"
                plate = None
                break
            plate = imgs[0]
            qa = assess_image_bytes(
                plate, require_fullbody=bool(payload.get("require_fullbody"))
            )
            if not (qa.get("ok") or qa.get("passed")):
                last_err = f"sequential_stage{pi + 1}_qa:{','.join(qa.get('reasons') or [])}"
                plate = None
                break
            slot = standing_slot(pi, total)
            delta = assess_companion_added(prev, plate, slot=slot)
            if delta is not None:
                last_err = f"sequential_stage{pi + 1}_qa:{delta}"
                try:
                    from app.config import settings as _settings

                    dbg = _settings.data_dir / "debug" / f"seq_{job.id}_a{attempt}_p{pi}.png"
                    dbg.parent.mkdir(parents=True, exist_ok=True)
                    dbg.write_bytes(plate)
                except Exception:
                    pass
                plate = None
                break

            # Rebind locks that did not fit in the 3-ref add call.
            for dj in dropped:
                dlab, draw, dfname = people[dj]
                dslot = standing_slot(dj, total)
                _phase(f"seq_rebind_p{dj + 1}_a{attempt}")
                rebind_names = [
                    client.upload_image(plate, f"rebind_plate_{attempt}_{dj}.png"),
                    client.upload_image(draw, dfname or f"rebind{dj}.png"),
                ]
                rwrap = wrap_rebind_identity(
                    base_label="plate after add — rebind dropped lock",
                    lock_label=dlab,
                    slot=dslot,
                    count_people=pi + 1,
                    edit_prompt=edit_prompt,
                    aspect=aspect,
                    width=width,
                    height=height,
                )
                rwf = compile_qwen_edit(
                    prompt=rwrap,
                    negative=multi_char_first_frame_negative(),
                    ref_names=rebind_names,
                    seed=next_seed(None, attempt + 40 + dj, True),
                    steps=steps,
                    cfg=cfg,
                    use_lightning=False,
                    width=width,
                    height=height,
                )
                rpid = client.queue_prompt(rwf)
                rhist = client.wait_history(rpid, timeout_seconds=job_timeout)
                rimgs = client.collect_images(rhist)
                if not rimgs:
                    last_err = f"sequential_rebind_p{dj + 1}: no images"
                    plate = None
                    break
                cand = rimgs[0]
                rqa = assess_image_bytes(
                    cand, require_fullbody=bool(payload.get("require_fullbody"))
                )
                if not (rqa.get("ok") or rqa.get("passed")):
                    last_err = (
                        f"sequential_rebind_p{dj + 1}_qa:{','.join(rqa.get('reasons') or [])}"
                    )
                    plate = None
                    break
                plate = cand
            if plate is None:
                break

        if plate is not None:
            return plate
    raise RuntimeError(last_err or "sequential multi-char first_frame edit failed")
