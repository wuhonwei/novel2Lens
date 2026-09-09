from app.h3_pipeline.params import resolution_from_aspect_clarity, seconds_to_frames
from app.h3_pipeline.workflow import build_h3_i2v_workflow


def test_seconds_to_frames_aligns_to_17n_plus_5():
    frames = seconds_to_frames(6)
    assert frames % 17 == 5
    assert frames >= 5


def test_resolution_16x9_clarity_075():
    w, h = resolution_from_aspect_clarity("16:9", "0.75")
    assert w > h
    assert w % 32 == 0
    assert h % 32 == 0


def test_build_h3_i2v_has_minimax_node():
    graph = build_h3_i2v_workflow(
        image_filename="frame.png",
        prompt="camera slowly pushes in",
        width=1280,
        height=720,
        length=145,
        seed=1,
        turbo=True,
        steps=8,
        unet_name="u.safetensors",
        clip_name="c.safetensors",
        video_vae_name="vv.safetensors",
        audio_vae_name="av.safetensors",
        turbo_lora_name="t.safetensors",
    )
    assert graph["9"]["class_type"] == "MiniMaxH3ImageToVideo"
    assert graph["9"]["inputs"]["prompt"] == "camera slowly pushes in"
    assert "18" in graph  # SaveVideo
