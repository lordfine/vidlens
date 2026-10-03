"""Shared fixtures for platform tests."""

import pytest

from vidlens.platforms import douyin


class _FakeCache:
    """Redirects cache_mod.video_dir() to a temp root."""

    def __init__(self, root):
        self.root = root

    def video_dir(self, platform, video_id):
        return self.root


@pytest.fixture
def douyin_tmp_cache(tmp_path, monkeypatch):
    """Douyin cache pointed at tmp_path, cookie jar stubbed empty."""
    monkeypatch.setattr(douyin, "cache_mod", _FakeCache(tmp_path))
    monkeypatch.setattr(douyin, "_cookie_jar", lambda cf: {})
    return tmp_path
