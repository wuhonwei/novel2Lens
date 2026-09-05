def test_set_image_busy_stops_llm():
    stops = []
    from app.llm_supervisor import LlmSupervisor

    s = LlmSupervisor(
        stop_cmd=lambda: stops.append("stop"),
        start_cmd=lambda: None,
        is_up=lambda: False,
        settle_seconds=0,
    )
    s.set_image_busy(True)
    assert s.image_busy is True
    assert stops == ["stop"]


def test_set_image_busy_false_does_not_start_llm():
    starts = []
    from app.llm_supervisor import LlmSupervisor

    s = LlmSupervisor(
        stop_cmd=lambda: None,
        start_cmd=lambda: starts.append("start"),
        is_up=lambda: False,
        settle_seconds=0,
    )
    s.set_image_busy(True)
    s.set_image_busy(False)
    assert s.image_busy is False
    assert starts == []


def test_stop_llm_waits_until_down_then_settles():
    """Kill may take a moment; stop_llm must wait for is_up=False before settle."""
    from app.llm_supervisor import LlmSupervisor

    state = {"up": True, "stops": 0, "slept": []}

    def stop():
        state["stops"] += 1
        if state["stops"] >= 2:
            state["up"] = False

    real_sleep = __import__("time").sleep

    def fake_sleep(sec):
        state["slept"].append(sec)

    import time as time_mod

    s = LlmSupervisor(
        stop_cmd=stop,
        start_cmd=lambda: None,
        is_up=lambda: state["up"],
        settle_seconds=0.5,
        poll_interval_seconds=0.01,
        release_timeout_seconds=5.0,
    )
    time_mod.sleep = fake_sleep  # type: ignore[assignment]
    try:
        s.stop_llm()
    finally:
        time_mod.sleep = real_sleep  # type: ignore[assignment]
    assert state["up"] is False
    assert state["stops"] >= 2
    assert any(abs(x - 0.5) < 1e-6 for x in state["slept"])


def test_tick_idle_skips_free_while_jobs_active():
    calls = []
    from app.comfy_supervisor import ComfySupervisor

    sup = ComfySupervisor(
        base_url="http://127.0.0.1:8189",
        root=r"D:\Develop\ComfyUI",
        python=r"D:\Develop\ComfyUI\venv\Scripts\python.exe",
        idle_seconds=1,
        stop_when_idle=False,
        client_factory=lambda url: type(
            "C",
            (),
            {
                "health": lambda self: {"ok": True},
                "free_memory": lambda self: calls.append("free"),
            },
        )(),
        start_process=lambda: None,
        stop_process=lambda: None,
        is_up=lambda: True,
    )
    sup.note_activity()
    import time

    time.sleep(1.2)
    sup.tick_idle(has_active_jobs=True)
    assert calls == []
    sup.tick_idle(has_active_jobs=False)
    assert calls == ["free"]


def test_idle_unload_calls_free(monkeypatch):
    calls = []
    from app.comfy_supervisor import ComfySupervisor

    sup = ComfySupervisor(
        base_url="http://127.0.0.1:8189",
        root=r"D:\Develop\ComfyUI",
        python=r"D:\Develop\ComfyUI\venv\Scripts\python.exe",
        idle_seconds=1,
        stop_when_idle=False,
        client_factory=lambda url: type(
            "C",
            (),
            {
                "health": lambda self: {"ok": True},
                "free_memory": lambda self: calls.append("free"),
            },
        )(),
        start_process=lambda: None,
        stop_process=lambda: None,
        is_up=lambda: True,
    )
    sup.note_activity()
    import time

    time.sleep(1.2)
    sup.tick_idle(has_active_jobs=False)
    assert "free" in calls


def test_ensure_running_starts_when_down():
    starts = []
    from app.comfy_supervisor import ComfySupervisor

    health_ok = {"ok": False}

    class FakeClient:
        def health(self):
            return dict(health_ok)

        def free_memory(self):
            pass

    def start():
        starts.append("start")
        health_ok["ok"] = True

    sup = ComfySupervisor(
        base_url="http://127.0.0.1:8189",
        root=r"D:\Develop\ComfyUI",
        python=r"D:\Develop\ComfyUI\venv\Scripts\python.exe",
        idle_seconds=180,
        stop_when_idle=False,
        client_factory=lambda url: FakeClient(),
        start_process=start,
        stop_process=lambda: None,
        is_up=lambda: health_ok["ok"],
        ready_timeout_seconds=2,
        poll_interval_seconds=0.05,
    )
    sup.ensure_running()
    assert starts == ["start"]


def test_tick_idle_stops_when_configured():
    calls = []
    from app.comfy_supervisor import ComfySupervisor

    sup = ComfySupervisor(
        base_url="http://127.0.0.1:8189",
        root=r"D:\Develop\ComfyUI",
        python=r"D:\Develop\ComfyUI\venv\Scripts\python.exe",
        idle_seconds=1,
        stop_when_idle=True,
        client_factory=lambda url: type(
            "C",
            (),
            {
                "health": lambda self: {"ok": True},
                "free_memory": lambda self: calls.append("free"),
            },
        )(),
        start_process=lambda: None,
        stop_process=lambda: calls.append("stop"),
        is_up=lambda: True,
    )
    sup.note_activity()
    import time

    time.sleep(1.2)
    sup.tick_idle(has_active_jobs=False)
    assert calls == ["free", "stop"]


def test_ensure_llm_skips_when_image_busy():
    starts = []
    from app.llm_supervisor import LlmSupervisor

    s = LlmSupervisor(
        stop_cmd=lambda: None,
        start_cmd=lambda: starts.append("start"),
        is_up=lambda: False,
        settle_seconds=0,
    )
    s.set_image_busy(True)
    s.ensure_llm()
    assert starts == []


def test_ensure_llm_starts_when_idle():
    starts = []
    from app.llm_supervisor import LlmSupervisor

    up = {"ok": False}

    def start():
        starts.append("start")
        up["ok"] = True

    s = LlmSupervisor(
        stop_cmd=lambda: None,
        start_cmd=start,
        is_up=lambda: up["ok"],
        settle_seconds=0,
    )
    s.set_image_busy(False)
    s.ensure_llm()
    assert starts == ["start"]


def test_stop_llm_invokes_stop_cmd():
    stops = []
    from app.llm_supervisor import LlmSupervisor

    s = LlmSupervisor(
        stop_cmd=lambda: stops.append("stop"),
        start_cmd=lambda: None,
        is_up=lambda: False,
        settle_seconds=0,
    )
    s.stop_llm()
    assert stops == ["stop"]
