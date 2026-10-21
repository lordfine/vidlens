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


@pytest.fixture
def local_video(tmp_path):
    """生成含音轨的真实视频，供离线公开接口测试复用。"""
    import subprocess

    from vidlens.ffutil import ffmpeg_path

    path = tmp_path / "本地视频.mp4"
    subprocess.run([
        ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000",
        "-t", "2", "-c:v", "mpeg4", "-c:a", "aac", str(path),
    ], check=True, capture_output=True, timeout=30)
    return path
