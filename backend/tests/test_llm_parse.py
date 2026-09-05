from app.llm import parse_json_value, strip_thinking


def test_parse_json_strips_fence_and_trailing_text():
    raw = """好的，如下：
```json
{"shots": [{"duration_s": 6}]}
```
额外说明。"""
    data = parse_json_value(raw)
    assert data["shots"][0]["duration_s"] == 6


def test_parse_json_strips_empty_think_tags():
    raw = '<think>\n\n</think>\n\n{"characters":[{"name":"林砚之"}]}'
    assert strip_thinking(raw).startswith("{")
    data = parse_json_value(raw)
    assert data["characters"][0]["name"] == "林砚之"
