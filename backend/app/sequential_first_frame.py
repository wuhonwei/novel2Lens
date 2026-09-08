"""Serial layered first-frame placement: scene → people → props."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from app.comfy_pipeline.qa import assess_companion_added, assess_image_bytes
from app.comfy_pipeline.workflows import compile_qwen_edit, next_seed
from app.db import ImageJob
from app.domain.edit_identity import (
    is_prop_ref_label,
    is_scene_ref_label,
    multi_char_first_frame_negative,
    person_ref_indices,
    standing_slot,
    two_pass_stage1_negative,
    wrap_rebind_identity,
    wrap_sequential_add_person,
    wrap_sequential_add_prop,
    wrap_sequential_place_first,
    wrap_sequential_place_on_scene,
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
    """Backward-compatible entry: layered sequential (scene → people → props)."""
    del session_factory
    return run_sequential_layered_first_frame(
        client=client,
        job=job,
        payload=payload,
        ref_paths=ref_paths,
        ref_labels=ref_labels,
        edit_prompt=edit_prompt,
        aspect=aspect,
        width=width,
        height=height,
        job_timeout=job_timeout,
        set_phase=set_phase,
    )


def run_sequential_layered_first_frame(
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
) -> bytes:
    """Stack scene plate, then each person, then each prop (≤3 refs per edit)."""
    scene_idxs = [i for i, lab in enumerate(ref_labels) if is_scene_ref_label(lab)]
    prop_idxs = [i for i, lab in enumerate(ref_labels) if is_prop_ref_label(lab)]
    person_idxs = person_ref_indices(ref_labels)
    if not person_idxs and not scene_idxs and not prop_idxs:
        # Fall back: treat unlabeled paths as people (legacy).
        person_idxs = list(range(min(len(ref_paths), max(2, len(ref_paths)))))

    people: list[tuple[str, bytes, str]] = []
    for i in person_idxs:
        if i >= len(ref_paths):
            continue
        lab = (ref_labels[i] if i < len(ref_labels) else f"person{i + 1}").strip()
        path = Path(ref_paths[i])
        people.append((lab, path.read_bytes(), path.name or f"person{i + 1}.png"))

    props: list[tuple[str, bytes, str]] = []
    for i in prop_idxs:
        if i >= len(ref_paths):
            continue
        lab = (ref_labels[i] if i < len(ref_labels) else f"prop{i + 1}").strip()
        path = Path(ref_paths[i])
        props.append((lab, path.read_bytes(), path.name or f"prop{i + 1}.png"))

    scene_blob: tuple[str, bytes, str] | None = None
    if scene_idxs:
        i = scene_idxs[0]
        if i < len(ref_paths):
            lab = (ref_labels[i] if i < len(ref_labels) else "scene").strip()
            path = Path(ref_paths[i])
            scene_blob = (lab, path.read_bytes(), path.name or "scene.png")

    total_people = len(people)
    if total_people < 1 and not scene_blob and not props:
        raise RuntimeError("sequential first_frame needs at least one layer ref")
    if total_people < 1 and not props and scene_blob:
        # Scene-only: return scene plate (resized via identity-ish edit not required).
        return scene_blob[1]

    def _phase(msg: str) -> None:
        if set_phase:
            set_phase(msg)

    last_err = ""
    max_attempts = 6
    for attempt in range(1, max_attempts + 1):
        steps = 28 + (attempt - 1) * 4
        cfg = min(6.0, 3.5 + (attempt - 1) * 0.4)
        plate: bytes | None = None
        last_person_lock: tuple[str, bytes, str] | None = None

        # --- Scene plate ---
        if scene_blob:
            _phase(f"seq_scene_a{attempt}")
            plate = scene_blob[1]

        # --- People ---
        for pi, (lab, raw, fname) in enumerate(people):
            _phase(f"seq_p{pi + 1}/{max(1, total_people)}_a{attempt}")
            if pi == 0 and plate is not None and scene_blob is not None:
                assert scene_blob is not None
                slab, sraw, sname = scene_blob
                ref_names = [
                    client.upload_image(sraw if plate == sraw else plate, sname or "scene.png"),
                    client.upload_image(raw, fname),
                ]
                wrap = wrap_sequential_place_on_scene(
                    scene_label=slab,
                    person_label=lab,
                    edit_prompt=edit_prompt,
                    total_people=max(1, total_people),
                    aspect=aspect,
                    width=width,
                    height=height,
                )
                neg = two_pass_stage1_negative() if total_people > 1 else multi_char_first_frame_negative()
                wf = compile_qwen_edit(
                    prompt=wrap,
                    negative=neg,
                    ref_names=ref_names,
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
                    last_err = "sequential_scene_place: no images"
                    plate = None
                    break
                plate = imgs[0]
                qa = assess_image_bytes(
                    plate, require_fullbody=bool(payload.get("require_fullbody"))
                )
                if not (qa.get("ok") or qa.get("passed")):
                    last_err = f"sequential_scene_place_qa:{','.join(qa.get('reasons') or [])}"
                    plate = None
                    break
                last_person_lock = (lab, raw, fname)
                continue

            if pi == 0:
                name0 = client.upload_image(raw, fname)
                wrap = wrap_sequential_place_first(
                    label=lab,
                    edit_prompt=edit_prompt,
                    total_people=max(1, total_people),
                    aspect=aspect,
                    width=width,
                    height=height,
                )
                wf = compile_qwen_edit(
                    prompt=wrap,
                    negative=two_pass_stage1_negative() if total_people > 1 else "",
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
                last_person_lock = (lab, raw, fname)
                continue

            assert plate is not None
            prev = plate
            kept = visual_lock_indices(placed_count=pi, max_lock_slots=1)
            dropped = dropped_lock_indices(placed_count=pi, kept=kept)
            wrap_locks = [people[j][0] for j in kept]
            ref_names = [client.upload_image(prev, f"plate_{attempt}_p{pi}.png")]
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
                total_people=total_people,
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
            slot = standing_slot(pi, total_people)
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

            for dj in dropped:
                dlab, draw, dfname = people[dj]
                dslot = standing_slot(dj, total_people)
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
            last_person_lock = (lab, raw, fname)

        if plate is None and people:
            continue
        if plate is None and scene_blob:
            plate = scene_blob[1]

        # --- Props ---
        for pj, (plab, praw, pfname) in enumerate(props):
            if plate is None:
                last_err = "sequential_prop: missing plate"
                break
            _phase(f"seq_prop{pj + 1}/{len(props)}_a{attempt}")
            prev = plate
            lock_lab = last_person_lock[0] if last_person_lock else None
            ref_names = [client.upload_image(prev, f"plate_{attempt}_prop{pj}.png")]
            if last_person_lock:
                ref_names.append(
                    client.upload_image(
                        last_person_lock[1], last_person_lock[2] or "lock_prop.png"
                    )
                )
            ref_names.append(client.upload_image(praw, pfname))
            wrap = wrap_sequential_add_prop(
                base_label="composition plate — keep people and scene",
                prop_label=plab,
                lock_label=lock_lab,
                edit_prompt=edit_prompt,
                aspect=aspect,
                width=width,
                height=height,
            )
            wf = compile_qwen_edit(
                prompt=wrap,
                negative=multi_char_first_frame_negative(),
                ref_names=ref_names,
                seed=next_seed(None, attempt + 80 + pj, True),
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
                last_err = f"sequential_prop{pj + 1}: no images"
                plate = None
                break
            cand = imgs[0]
            qa = assess_image_bytes(
                cand, require_fullbody=bool(payload.get("require_fullbody")) and total_people > 0
            )
            if not (qa.get("ok") or qa.get("passed")):
                # Soft: prop stage fullbody may fail on object-heavy crops — only fail hard
                # when people were expected and QA says missing_person-ish.
                reasons = qa.get("reasons") or []
                hard = [r for r in reasons if "missing" in str(r) or "person" in str(r)]
                if hard and total_people > 0:
                    last_err = f"sequential_prop{pj + 1}_qa:{','.join(reasons)}"
                    plate = None
                    break
            plate = cand

        if plate is not None:
            return plate
    raise RuntimeError(last_err or "sequential layered first_frame edit failed")
