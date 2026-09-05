from app.comfy_pipeline.workflows import compile_sdxl_t2i, resolve_size


def test_resolve_size_half_and_far():
    assert resolve_size("3:4")[0] < resolve_size("3:4")[1] or resolve_size("3:4") == (768, 1024)
    w, h = resolve_size("16:9")
    assert w > h


def test_compile_sdxl_returns_prompt_dict():
    graph = compile_sdxl_t2i(
        prompt="test character full body",
        negative="",
        width=704,
        height=1472,
        steps=20,
        cfg=5.0,
        seed=1,
        ckpt="RealVisXL_V5.0_fp16.safetensors",
    )
    assert isinstance(graph, dict)
    assert len(graph) >= 3
