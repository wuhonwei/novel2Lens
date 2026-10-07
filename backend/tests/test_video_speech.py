# -*- coding: utf-8 -*-
from app.domain.video_speech import (
    combine_video_scores,
    extract_expected_speech,
    score_transcript,
    speech_expected,
)


def test_extract_dialogue_and_vo_from_h3():
    h3 = (
        "<Image 1> 为强参考首帧。 左一的少年，开口说道：「请问，是陈守义老伯吗？」。 "
        "旁白（画外音）：无 画外口播：「滚！」 画面中可辨认人物始终为 1 人。"
    )
    got = extract_expected_speech(h3)
    assert "请问，是陈守义老伯吗？" in got
    assert "滚！" in got


def test_extract_narration_when_not_wu():
    h3 = "运镜：固定。 旁白（画外音）：江雾更浓了。 画面中可辨认人物始终为 0 人。"
    got = extract_expected_speech(h3, narration="江雾更浓了。")
    assert any("江雾" in x for x in got)


def test_silent_shot_has_no_expected_speech():
    h3 = (
        "<Image 1> 为强参考首帧。 运镜：固定。 旁白（画外音）：无 "
        "本镜无人声：不要说话。 画面中可辨认人物始终为 0 人。"
    )
    got = extract_expected_speech(h3)
    assert got == []
    assert speech_expected(got) is False


def test_score_transcript_matches_dialogue():
    expected = ["请问，是陈守义老伯吗？"]
    out = score_transcript(expected, "请问是陈守义老伯吗")
    assert out["score"] >= 70
    assert "dialogue_mismatch" not in out["issues"]


def test_score_transcript_empty_when_speech_required():
    out = score_transcript(["给我滚"], "")
    assert out["score"] < 60
    assert "missing_speech" in out["issues"]


def test_score_transcript_silent_shot_penalizes_speech():
    out = score_transcript([], "こんにちは、今日はいい天気ですね")
    assert out["score"] < 60
    assert "unexpected_speech" in out["issues"]


def test_combine_weights_speech_vs_silent():
    spoken = combine_video_scores(80, 40, speech_expected=True)
    assert spoken["weights"]["visual"] == 0.6
    assert spoken["score"] == 64  # 0.6*80 + 0.4*40
    silent = combine_video_scores(80, 100, speech_expected=False)
    assert silent["weights"]["visual"] == 0.75
    assert silent["score"] == 85  # 0.75*80 + 0.25*100
    visual_only = combine_video_scores(70, None, speech_expected=True)
    assert visual_only["score"] == 70
    assert "audio_skipped" in visual_only["comment_hint"]
