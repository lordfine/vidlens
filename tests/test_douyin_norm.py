from vidlens.platforms import douyin

FAKE_ITEM = {
    "aweme_id": "7607060532303169189",
    "desc": "测试视频描述 #标签",
    "create_time": 1739577600,
    "author": {"nickname": "测试作者", "unique_id": "author_1"},
    "statistics": {"play_count": 12345, "digg_count": 678},
    "video": {
        "duration": 231643,  # ms
        "cover": {"url_list": ["https://x/cover.jpg"]},
        "play_addr": {
            "uri": "v1e00fgi",
            "url_list": [
                "https://aweme.snssdk.com/aweme/v1/playwm/?ratio=720p&video_id=v1e00fgi"],
        },
    },
}


def test_normalize_item():
    m = douyin._normalize_item(FAKE_ITEM)
    assert m["platform"] == "douyin"
    assert m["video_id"] == "7607060532303169189"
    assert m["uploader"] == "测试作者"
    assert abs(m["duration"] - 231.643) < 0.01     # ms -> s
    assert m["like_count"] == 678
    assert m["thumbnail"] == "https://x/cover.jpg"
    assert m["upload_date"]  # yyyymmdd


def test_normalize_item_seconds_duration():
    item = dict(FAKE_ITEM)
    item["video"] = dict(FAKE_ITEM["video"], duration=59)  # already seconds
    m = douyin._normalize_item(item)
    assert m["duration"] == 59


def test_play_urls_nowatermark_first():
    urls = douyin._play_urls(FAKE_ITEM)
    assert urls[0] == ("no_watermark",
                       "https://aweme.snssdk.com/aweme/v1/play/?ratio=720p"
                       "&video_id=v1e00fgi")
    assert ("watermark",
            "https://aweme.snssdk.com/aweme/v1/playwm/?ratio=720p"
            "&video_id=v1e00fgi") in urls


def test_map_lang():
    from vidlens.asr.sensevoice import _map_lang
    assert _map_lang("zh-CN") == "zh"
    assert _map_lang("AUTO") == "auto"
    assert _map_lang("cantonese") == "yue"


def test_cookie_file_written(tmp_path):
    from vidlens.platforms import write_cookie_file
    p = write_cookie_file("bilibili", "SESSDATA=abc123; bili_jct=xyz")
    txt = p.read_text(encoding="utf-8")
    assert ".bilibili.com" in txt and "SESSDATA\tabc123" in txt
