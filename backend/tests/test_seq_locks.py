from app.domain.seq_locks import dropped_lock_indices, visual_lock_indices


def test_visual_lock_prefers_most_recent_when_capped():
    assert visual_lock_indices(placed_count=1, max_lock_slots=1) == [0]
    assert visual_lock_indices(placed_count=2, max_lock_slots=1) == [1]
    assert visual_lock_indices(placed_count=2, max_lock_slots=2) == [0, 1]
    assert dropped_lock_indices(placed_count=2, kept=[1]) == [0]
