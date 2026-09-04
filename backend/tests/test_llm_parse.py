from app.llm import parse_json_value


def test_parse_json_strips_fence_and_trailing_text():
    raw = """好的，如下：
```json
{"shots": [{"duration_s": 6}]}
```
额外说明。"""
    data = parse_json_value(raw)
    assert data["shots"][0]["duration_s"] == 6
