# -*- coding: utf-8 -*-
from app.ollama_vram import list_ollama_running, unload_all_ollama


def test_list_ollama_running_parses(monkeypatch):
    class FakeResp:
        def read(self):
            return b'{"models":[{"name":"qwen2.5:32b"},{"model":"qwen2.5vl:7b"}]}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("app.ollama_vram.urlopen", lambda *a, **k: FakeResp())
    assert list_ollama_running() == ["qwen2.5:32b", "qwen2.5vl:7b"]


def test_unload_all_calls_each(monkeypatch):
    calls = []
    monkeypatch.setattr("app.ollama_vram.list_ollama_running", lambda _base="http://127.0.0.1:11434": ["qwen2.5:32b", "qwen2.5vl:7b"])
    monkeypatch.setattr("app.ollama_vram.unload_ollama_model", lambda name, base_url="http://127.0.0.1:11434", **kw: calls.append(name))
    out = unload_all_ollama()
    assert out == ["qwen2.5:32b", "qwen2.5vl:7b"]
    assert calls == ["qwen2.5:32b", "qwen2.5vl:7b"]
