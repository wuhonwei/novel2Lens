from app.comfy_supervisor import ComfySupervisor


def test_release_for_llm_prefers_unload_without_stop():
    calls: list[str] = []

    class FakeClient:
        def free_memory(self, *, unload_models: bool = True) -> None:
            calls.append("free")

        def health(self) -> dict:
            return {"ok": False}

    def stop() -> None:
        calls.append("stop")

    s = ComfySupervisor(
        base_url="http://127.0.0.1:8189",
        root=".",
        python="python",
        idle_seconds=180,
        stop_when_idle=True,
        prefer_unload_over_restart=True,
        client_factory=lambda _url: FakeClient(),
        start_process=lambda: None,
        stop_process=stop,
        is_up=lambda: False,
    )
    s.note_activity()
    s.release_for_llm()
    assert "free" in calls
    assert "stop" not in calls
    assert s._idle_handled is True


def test_release_for_llm_stops_when_prefer_unload_false():
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
        prefer_unload_over_restart=False,
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


def test_idle_still_stops_process():
    calls: list[str] = []

    class FakeClient:
        def free_memory(self, *, unload_models: bool = True) -> None:
            calls.append("free")

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
        idle_seconds=0,
        stop_when_idle=True,
        prefer_unload_over_restart=True,
        client_factory=lambda _url: FakeClient(),
        start_process=lambda: None,
        stop_process=stop,
        is_up=is_up,
    )
    s.note_activity()
    s.tick_idle(has_active_jobs=False)
    assert "free" in calls
    assert "stop" in calls
