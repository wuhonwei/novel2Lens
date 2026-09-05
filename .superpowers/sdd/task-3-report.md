# Task 3 Report: ComfySupervisor + LlmSupervisor

**Status:** DONE  
**Branch:** `feature/embedded-image-pipeline`  
**Commit:** `4a2c27e` — Add Comfy and LLM supervisors for on-demand load and hard mutex.

## Summary

Added injectable `ComfySupervisor` (on-demand ComfyUI start, `/free` idle unload, optional process stop) and `LlmSupervisor` (port-8080 stop/start + `image_busy` hard mutex gate). No ImageWorker wiring yet.

## TDD Steps Executed

| Step | Action | Result |
|------|--------|--------|
| 1 | Added `backend/tests/test_supervisors.py` (brief tests + ensure/stop coverage) | OK |
| 2 | Ran tests before implementation | `ModuleNotFoundError` for both modules (expected) |
| 3 | Implemented `comfy_supervisor.py` + `llm_supervisor.py` with DI hooks | OK |
| 4 | Re-ran supervisor tests | 7 passed |
| 5 | Full suite | 42 passed |
| 6 | Commit | per brief message |

## Files Created

| File | Role |
|------|------|
| `backend/app/comfy_supervisor.py` | `ensure_running`, `free_models`, `note_activity`, `tick_idle`; inject `client_factory` / `start_process` / `stop_process` / `is_up` |
| `backend/app/llm_supervisor.py` | `set_image_busy` / `image_busy`, `stop_llm`, `ensure_llm`; inject `stop_cmd` / `start_cmd` / `is_up` |
| `backend/tests/test_supervisors.py` | Mutex, idle `/free`, start-when-down, stop-when-idle, ensure_llm skip/start |

## Behavior Notes

- **Comfy start:** `python main.py --listen 127.0.0.1 --port <from base_url>` in `comfy_root` (mirrors aiImage `start.ps1`); wait up to 180s.
- **Idle:** after `note_activity`, `tick_idle(has_active_jobs=False)` once past `idle_seconds` calls `free_memory`; if `stop_when_idle` also stops process. Idempotent until next activity.
- **LLM stop:** default kills listeners on port **8080** via PowerShell `Get-NetTCPConnection` (same idea as aiImage `Stop-PortListeners`).
- **LLM start:** default runs repo `start-llm.ps1`; skipped while `image_busy`.

## Concerns

1. Default kill is Windows/PowerShell-oriented (matches this machine’s scripts); no PID file from `start-llm.ps1`.
2. `ensure_llm` waits up to 900s for readiness (Flash-Next can be slow); callers may want a shorter timeout or async later.
3. Supervisors are not yet wired into `main.py` / ImageWorker (Task 4).

## Verification Commands

```powershell
Set-Location D:\Develop\novel2Lens\backend
python -m pytest tests/test_supervisors.py -v
python -m pytest -v
```
