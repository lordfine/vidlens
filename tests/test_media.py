from vidtool.platforms import media


SEGS = [
    {"start": 0.0, "end": 2.5, "text": "你好"},
    {"start": 2.5, "end": 5.0, "text": "世界"},
    {"start": 5.0, "end": 8.245, "text": "hello world"},
]


def test_render_srt_roundtrip():
    text = media.render(SEGS, "srt")
    assert "00:00:00,000 --> 00:00:02,500" in text
    parsed = media.parse_srt(text)
    assert len(parsed) == 3
    assert parsed[0]["start"] == 0.0
    assert abs(parsed[0]["end"] - 2.5) < 0.01
    assert parsed[2]["text"] == "hello world"


def test_render_vtt_header():
    text = media.render(SEGS, "vtt")
    assert text.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:02.500" in text


def test_render_txt_dedup():
    segs = SEGS + [{"start": 9.0, "end": 10.0, "text": "世界"}]
    # note: dedup only drops *consecutive* repeats
    text = media.render(segs, "txt")
    lines = [l for l in text.splitlines() if l]
    assert "世界" in lines


def test_render_json():
    text = media.render(SEGS, "json")
    import json
    obj = json.loads(text)
    assert len(obj["segments"]) == 3
    assert obj["segments"][0]["text"] == "你好"


def test_parse_bili_json():
    body = '{"body": [{"from": 0.0, "to": 1.0, "content": "第一句"}, '\
           '{"from": 1.0, "to": 2.0, "content": "第二句"}]}'
    segs = media.parse_bili_json(body)
    assert segs[1]["text"] == "第二句"


def test_parse_any_subtitle_dispatch():
    assert media.parse_any_subtitle('{"body": []}') == []
    srt = media.render(SEGS, "srt")
    assert len(media.parse_any_subtitle(srt)) == 3


def test_parse_ts_minutes_only():
    assert media.parse_ts("01:02.500") == 62.5
