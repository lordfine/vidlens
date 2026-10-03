
from vidlens import cache


def test_dirs_under_env(tmp_path, monkeypatch):
    monkeypatch.setenv("vidlens_CACHE", str(tmp_path))
    vd = cache.video_dir("douyin", "7607060532303169189")
    assert vd == tmp_path / "cache" / "douyin" / "7607060532303169189"
    assert vd.is_dir()
    jd = cache.job_dir("douyin", "7607060532303169189", "subs")
    assert jd.parent.name == "jobs" and jd.name.startswith("subs-")


def test_video_id_sanitized(tmp_path, monkeypatch):
    monkeypatch.setenv("vidlens_CACHE", str(tmp_path))
    vd = cache.video_dir("bilibili", "BV1../evil?*")
    assert vd.name == "BV1..evil" or all(
        c.isalnum() or c in "-_" for c in vd.name)


def test_clean_all(tmp_path, monkeypatch):
    monkeypatch.setenv("vidlens_CACHE", str(tmp_path))
    vd = cache.video_dir("douyin", "123")
    (vd / "media").mkdir(parents=True)
    (vd / "media" / "video.mp4").write_bytes(b"x" * 10000)
    r = cache.clean(all_=True)
    assert r["removed_bytes"] >= 10000
    assert not (vd / "media").exists()


def test_clean_lru_noop_when_under_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("vidlens_CACHE", str(tmp_path))
    vd = cache.video_dir("douyin", "123")
    (vd / "media").mkdir(parents=True)
    (vd / "media" / "v.bin").write_bytes(b"x" * 100)
    r = cache.clean(max_bytes=1024 * 1024)
    assert r["removed_bytes"] == 0
    assert (vd / "media" / "v.bin").exists()
