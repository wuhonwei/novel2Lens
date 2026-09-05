from app.comfy_supervisor import ComfySupervisor


def test_release_for_llm_frees_and_stops():
    calls: list[str] = []

    class FakeClient:
        def free_memory(self, *, unload_models: bool = True) -> None:
            calls.append("free")

        def health(self) -> dict:
            return {"ok": False}

    def stop() -> None:
        calls.append("stop")

    up = {"v": True}

    def is_up() -> bool:
        if up["v"]:
            up["v"] = False
            return True
        return False

    s = ComfySupervisor(
        base_url="http://127.0.0.1:8189",
        root=".",
        python="python",
        idle_seconds=180,
        stop_when_idle=True,
        client_factory=lambda _url: FakeClient(),
        start_process=lambda: None,
        stop_process=stop,
        is_up=is_up,
    )
    s.note_activity()
    s.release_for_llm()
    assert "free" in calls
    assert "stop" in calls
    assert s._idle_handled is True
