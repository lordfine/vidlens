from vidlens.asr.sensevoice import _merge_fragments


def test_merges_word_cut_across_segments():
    segs = [
        {"start": 0.0, "end": 3.8, "text": "再分享4个省 to"},
        {"start": 3.9, "end": 5.1, "text": "ken的省钱技巧。"},
    ]
    out = _merge_fragments(segs)
    assert len(out) == 1
    assert out[0]["text"] == "再分享4个省 token的省钱技巧。"
    assert out[0]["end"] == 5.1


def test_no_merge_when_punctuated():
    segs = [
        {"start": 0.0, "end": 3.8, "text": "先说结论。"},
        {"start": 3.9, "end": 5.1, "text": "app很好用"},
    ]
    assert len(_merge_fragments(segs)) == 2


def test_no_merge_when_far_apart():
    segs = [
        {"start": 0.0, "end": 3.8, "text": "提到 to"},
        {"start": 30.0, "end": 31.0, "text": "ken 这个词"},
    ]
    assert len(_merge_fragments(segs)) == 2


def test_no_merge_chinese():
    segs = [
        {"start": 0.0, "end": 3.8, "text": "我们继续说"},
        {"start": 3.9, "end": 5.1, "text": "下一件事"},
    ]
    assert len(_merge_fragments(segs)) == 2
