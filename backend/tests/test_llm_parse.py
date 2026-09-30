from app.llm import LLMError, parse_json_value, strip_thinking


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


def test_parse_json_tolerates_trailing_commas():
    raw = '{"shots":[{"duration_s":6,"camera":"固定",},],}'
    data = parse_json_value(raw)
    assert data["shots"][0]["duration_s"] == 6


def test_parse_json_recovers_truncated_object():
    # Model hit max_tokens mid-array; keep complete leading shots.
    raw = (
        '{"shots":[{"duration_s":6,"scene_name":"渡口","characters":[{"name":"林砚之"}]},'
        '{"duration_s":5,"scene_name":"茅屋","characters":[{"name":"陈守义"'
    )
    data = parse_json_value(raw)
    assert isinstance(data["shots"], list)
    assert len(data["shots"]) >= 1
    assert data["shots"][0]["scene_name"] == "渡口"


def test_parse_json_unclosed_think_block():
    raw = '<think>\nlong reasoning without close\n{"shots":[{"duration_s":4}]}'
    data = parse_json_value(raw)
    assert data["shots"][0]["duration_s"] == 4
