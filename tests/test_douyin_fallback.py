"""douyin download fallback chain + one-shot retry, tested at the `douyin.download()` / `_download_with_fallback()` seam (network mocked)."""

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


def test_download_wraps_direct_chain_in_lock(monkeypatch, tmp_path):
    """The direct-link path (not just yt-dlp) must hold the per-video lock."""
    import contextlib

    seen = []

    @contextlib.contextmanager
    def fake_lock(d, timeout=300.0):
        seen.append(str(d))
        yield

    monkeypatch.setattr("vidlens.locking.cache_write_lock", fake_lock)
    monkeypatch.setattr(douyin, "_cookie_jar", lambda cf: {})
    monkeypatch.setattr(douyin, "cache_mod",
                        type("C", (), {"video_dir": staticmethod(
                            lambda p, v: tmp_path)})())
    monkeypatch.setattr(douyin, "_fetch_item", lambda vid, cf: FAKE_ITEM)
    monkeypatch.setattr(douyin, "_download_url",
                        lambda url, dest, jar: (_mk(dest), True)[1])
    out = douyin.download(
        _T("https://www.douyin.com/video/7607060532303169189"),
        {"platform": "douyin", "video_id": "7607060532303169189",
         "webpage_url": "x"},
        None, "video", 1080, fresh=True)
    assert out["source_level"] == "no_watermark"
    assert len(seen) == 1 and seen[0].endswith("media")


def test_fetch_meta_reraises_auth_error(monkeypatch):
    """A dead user cookie must surface as exit-2 AuthNeeded (ADR-0004),
    not be swallowed into exit-3 Blocked."""
    import types

    import pytest

    from vidlens.agentio import AuthNeededError

    monkeypatch.setattr(douyin, "_fetch_item_with_refresh",
                        lambda vid, cf: None)
    monkeypatch.setattr(douyin, "load_meta", lambda p, v: None)
    monkeypatch.setattr(douyin, "save_meta", lambda p, v, m: None)

    class FakeDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            raise RuntimeError("Fresh cookies (not necessarily logged in) "
                               "are needed. Login required.")

    fake_mod = types.ModuleType("yt_dlp")
    fake_mod.YoutubeDL = FakeDL
    monkeypatch.setattr(douyin, "yt_dlp", fake_mod)

    with pytest.raises(AuthNeededError):
        douyin.fetch_meta(
            _T("https://www.douyin.com/video/7607060532303169189"),
            "user-cookie.txt", fresh=True)


class _T:
    def __init__(self, url):
        from vidlens.urls import Platform
        self.platform = Platform.douyin
        self.url = url
        self.video_id = "7607060532303169189"
