import pytest


@pytest.fixture(autouse=True)
def _disable_video_worker_in_api_tests(monkeypatch, request):
    """Prevent VideoWorker from attaching to temp DBs during TestClient lifespan."""
    if "test_video_worker" in request.node.nodeid:
        return
    monkeypatch.setattr("app.main._start_video_worker", lambda: None, raising=False)
    monkeypatch.setattr("app.main._stop_video_worker", lambda: None, raising=False)
