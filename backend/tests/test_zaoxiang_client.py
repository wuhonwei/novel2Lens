from app.zaoxiang_client import ZaoxiangClient, ZaoxiangError


class _Resp:
    def __init__(self, status_code=200, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content
        self.text = str(payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.text)

    def json(self):
        return self._payload


def test_zaoxiang_client_wait_and_download(monkeypatch):
    calls = {"n": 0}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, path):
            if path == "/api/health":
                return _Resp(200, {"ok": True})
            if path.startswith("/api/jobs/"):
                calls["n"] += 1
                if calls["n"] < 2:
                    return _Resp(200, {"id": "j1", "status": "running", "images": []})
                return _Resp(
                    200,
                    {"id": "j1", "status": "succeeded", "images": [{"id": "img1", "role": "success"}]},
                )
            if path.startswith("/api/images/"):
                return _Resp(200, content=b"PNGDATA")
            return _Resp(404, {"error": "no"})

        def post(self, path, json=None, data=None, files=None):
            return _Resp(200, {"id": "j1", "status": "queued"})

    monkeypatch.setattr("app.zaoxiang_client.httpx.Client", FakeClient)
    client = ZaoxiangClient("http://zaoxiang.test")
    assert client.health()["ok"] is True
    job = client.create_generate({"prompt": "test", "count": 1})
    assert job["id"] == "j1"
    done = client.wait_job("j1", poll_s=0.01, timeout_s=2)
    assert done["status"] == "succeeded"
    assert client.first_success_image_id(done) == "img1"
    assert client.download_image("img1") == b"PNGDATA"


def test_zaoxiang_client_raises_on_generate_error(monkeypatch):
    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, path, json=None, data=None, files=None):
            return _Resp(500, {"error": "boom"})

    monkeypatch.setattr("app.zaoxiang_client.httpx.Client", FakeClient)
    client = ZaoxiangClient("http://zaoxiang.test")
    try:
        client.create_generate({"prompt": "x"})
        raise AssertionError("expected ZaoxiangError")
    except ZaoxiangError as exc:
        assert "500" in str(exc)
