"""Helpers for selecting which identity locks fit in Qwen Edit's 3-ref budget."""
from __future__ import annotations


def visual_lock_indices(*, placed_count: int, max_lock_slots: int) -> list[int]:
    """Indices of already-placed people to upload as visual locks (0-based).

    Qwen Edit has 3 image inputs: plate + locks + new person.
    max_lock_slots is usually 1 (3 - plate - new). Prefer the *most recently*
    placed person — they sit nearest the insertion and are easiest to overwrite.
    """
    if placed_count <= 0 or max_lock_slots <= 0:
        return []
    if placed_count <= max_lock_slots:
        return list(range(placed_count))
    # Keep the newest N locks (drop the oldest visually; plate still holds them).
    start = placed_count - max_lock_slots
    return list(range(start, placed_count))


def dropped_lock_indices(*, placed_count: int, kept: list[int]) -> list[int]:
    kept_set = set(kept)
    return [i for i in range(placed_count) if i not in kept_set]
