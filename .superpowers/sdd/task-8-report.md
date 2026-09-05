# Task 8 Report — 青渡川 real-GPU E2E

## Status: DONE

## What ran

Full UI-equivalent HTTP flow against live API (no FakeComfy):

1. Create project `青渡川` from full novel
2. `generate-assets` (real Flash-Next LLM)
3. First-chapter `storyboard` (real LLM)
4. `generate-images` one-click (real Comfy :8189)
5. Assert storyboard → 409 while image busy
6. Poll until all jobs done; assert asset paths on disk

## Result (second run, after LLM settle hardening)

| Field | Value |
|-------|--------|
| Report | `backend/scripts/qingduchuan_e2e_report.json` |
| `ok` | **true** |
| `fake_comfy` | false |
| project_id | `f34ba90e-d4fc-4e75-9da8-bbc0d1d4f208` |
| assets | 10 character / 9 scene / 7 prop |
| shots | 8 |
| jobs | **45 succeeded**, 0 failed |
| storyboard_busy_status | 409 |
| t2i_before_edit | true |
| path_issues | none |
| total_s | ~2295.5 (~38 min) |
| generate_assets | ~493 s |
| storyboard | ~176 s |
| generate_images | ~1626 s |

Exit code: **0**

## Prior failure (first attempt before harden)

Died right after enqueue with empty JSON on first `image-jobs` poll (API/Comfy cold-start race with LLM). Fixed by settle wait + poll retries (`cbd1566`), then this run completed.

## Files

- `backend/scripts/e2e_qingduchuan_flow.py`
- `backend/tests/test_e2e_qingduchuan_flow_gpu.py` (`@pytest.mark.gpu`, not in default CI)
- `backend/pyproject.toml` markers

## Concerns

- Full-book image batch is long (~27 min GPU); prefer running E2E in an external terminal for Cursor stability.
- Comfy/LLM processes may still be up after the run (idle unload after 180s).
