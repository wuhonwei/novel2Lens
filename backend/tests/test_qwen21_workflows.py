from app.comfy_pipeline.workflows import (
    compile_qwen21_edit,
    compile_qwen21_t2i,
    compile_qwen_edit,
)


def test_compile_qwen21_t2i_uses_gguf_q8():
    wf = compile_qwen21_t2i(
        prompt="a young man in white robes",
        negative="blurry",
        width=1152,
        height=640,
        seed=42,
    )
    assert wf["1"]["class_type"] == "UnetLoaderGGUF"
    assert wf["1"]["inputs"]["unet_name"] == "qwen-image-2.1-Q8_0.gguf"
    assert wf["2"]["inputs"]["clip_name"] == "qwen3vl_8b_bf16.safetensors"
    assert wf["3"]["inputs"]["vae_name"] == "qwen_image_2.1_vae_bf16.safetensors"
    assert wf["4"]["class_type"] == "TextEncodeQwenImage21"
    assert wf["4"]["inputs"]["prompt"] == "a young man in white robes"
    assert wf["5"]["inputs"]["width"] == 1152
    assert wf["5"]["inputs"]["height"] == 640
    assert wf["6"]["inputs"]["steps"] == 25
    assert wf["6"]["inputs"]["cfg"] == 1.0
    assert "8" in wf  # SaveImage


def test_compile_qwen21_edit_wires_only_provided_refs():
    wf = compile_qwen21_edit(
        prompt="keep identity, look at the photo frame",
        negative="extra people",
        ref_names=["char.png", "photo.png"],
        seed=7,
        width=1344,
        height=768,
    )
    assert wf["1"]["inputs"]["unet_name"] == "qwen-image-2.1-Q8_0.gguf"
    assert wf["10"]["inputs"]["image"] == "char.png"
    assert wf["11"]["inputs"]["image"] == "photo.png"
    assert "12" not in wf
    enc = wf["20"]["inputs"]
    assert enc["images.image_1"] == ["10", 0]
    assert enc["images.image_2"] == ["11", 0]
    assert "images.image_3" not in enc
    assert wf["40"]["inputs"]["latent_image"] == ["30", 0]
    assert wf["30"]["inputs"]["width"] == 1344


def test_compile_qwen_edit_alias_routes_to_qwen21():
    wf = compile_qwen_edit(
        prompt="x",
        negative="",
        ref_names=["a.png"],
        seed=1,
        steps=4,
        use_lightning=True,
        width=1024,
        height=1024,
    )
    assert wf["1"]["class_type"] == "UnetLoaderGGUF"
    assert wf["20"]["class_type"] == "TextEncodeQwenImage21"
