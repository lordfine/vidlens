"""S1+S2: douyin download fallback chain + one-shot retry, tested at the
`douyin.download()` / `_download_with_fallback()` seam (network mocked)."""

from vidlens.platforms import douyin

FAKE_ITEM = {
    "aweme_id": "7607060532303169189",
    "desc": "x",
    "video": {
        "duration": 10000,
        "play_addr": {"url_list": [
            "https://aweme.snssdk.com/aweme/v1/playwm/?video_id=v1"]},
    },
}


def _mk(dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"x" * 2048)


# ------------------------------------------------------------------ S1 ----

def test_fallback_no_watermark_first(monkeypatch, tmp_path):
    """First URL (playwm->play) succeeds => source_level no_watermark."""
    calls = []

    def fake_dl(url, dest, jar):
        calls.append(url)
        _mk(dest)
        return True

    monkeypatch.setattr(douyin, "_download_url", fake_dl)
    level = douyin._download_with_fallback(FAKE_ITEM, tmp_path / "v.mp4", {})
    assert level == "no_watermark"
    assert calls == ["https://aweme.snssdk.com/aweme/v1/play/?video_id=v1"]


def test_fallback_falls_to_watermark(monkeypatch, tmp_path):
    """No-watermark 403s => watermark URL wins, level recorded."""
    calls = []

    def fake_dl(url, dest, jar):
        calls.append(url)
        if "playwm" in url:          # watermark variant works
            _mk(dest)
            return True
        return False

    monkeypatch.setattr(douyin, "_download_url", fake_dl)
    level = douyin._download_with_fallback(FAKE_ITEM, tmp_path / "v.mp4", {})
    assert level == "watermark"
    assert len(calls) == 2


def test_fallback_all_dead_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(douyin, "_download_url",
                        lambda url, dest, jar: False)
    level = douyin._download_with_fallback(FAKE_ITEM, tmp_path / "v.mp4", {})
    assert level is None


# ------------------------------------------------------------------ S2 ----

def test_download_retries_meta_once(monkeypatch, tmp_path):
    """All URLs fail on first pass => meta re-fetched once, second pass wins."""
    monkeypatch.setattr(douyin, "_cookie_jar", lambda cf: {})
    monkeypatch.setattr(douyin, "cache_mod",
                        type("C", (), {"video_dir": staticmethod(
                            lambda p, v: tmp_path)})())
    attempts = {"n": 0}

    def fake_fetch(vid, cf):
        attempts["n"] += 1
        return FAKE_ITEM

    def fake_dl(url, dest, jar):
        if attempts["n"] == 1:       # first pass: all dead
            return False
        _mk(dest)
        return True

    monkeypatch.setattr(douyin, "_fetch_item", fake_fetch)
    monkeypatch.setattr(douyin, "_download_url", fake_dl)
    out = douyin.download(
        _T("https://www.douyin.com/video/7607060532303169189"),
        {"platform": "douyin", "video_id": "7607060532303169189",
         "webpage_url": "x"},
        None, "video", 1080, fresh=True)
    assert out["source_level"] == "no_watermark"
    assert out["retried"] is True
    assert attempts["n"] == 2


def test_download_returns_dict_shape(monkeypatch, tmp_path):
    """Platform download contract: {path, source_level, retried}."""
    monkeypatch.setattr(douyin, "_cookie_jar", lambda cf: {})
    monkeypatch.setattr(douyin, "cache_mod",
                        type("C", (), {"video_dir": staticmethod(
                            lambda p, v: tmp_path)})())
    monkeypatch.setattr(douyin, "_fetch_item", lambda vid, cf: FAKE_ITEM)

    def fake_dl(url, dest, jar):
        _mk(dest)
        return True

    monkeypatch.setattr(douyin, "_download_url", fake_dl)
    out = douyin.download(
        _T("https://www.douyin.com/video/7607060532303169189"),
        {"platform": "douyin", "video_id": "7607060532303169189",
         "webpage_url": "x"},
        None, "video", 1080, fresh=True)
    assert set(out) >= {"path", "source_level", "retried"}
    assert out["path"].endswith("video.mp4")


class _T:
    def __init__(self, url):
        from vidlens.urls import Platform
        self.platform = Platform.douyin
        self.url = url
        self.video_id = "7607060532303169189"
