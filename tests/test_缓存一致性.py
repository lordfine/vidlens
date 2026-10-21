"""缓存必须对应当前源内容和刷新意图。"""

import wave

import pytest

from vidlens.asr import prepare_wav


def write_audio(path, seconds):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0\0" * (16000 * seconds))


def test_changed_source_invalidates_derived_audio(tmp_path):
    source = tmp_path / "音频.wav"
    write_audio(source, 1)
    assert prepare_wav(str(source))[1] == pytest.approx(1)
    write_audio(source, 2)
    assert prepare_wav(str(source))[1] == pytest.approx(2)


def test_corrupted_derived_audio_is_regenerated(tmp_path):
    from pathlib import Path

    source = tmp_path / "音频.wav"
    write_audio(source, 1)
    derived, _ = prepare_wav(str(source))
    write_audio(Path(derived), 2)
    assert prepare_wav(str(source))[1] == pytest.approx(1)


def test_transcript_cache_tracks_content_and_refresh(tmp_path, monkeypatch):
    from vidlens import asr

    monkeypatch.setenv("vidlens_CACHE", str(tmp_path / "管理缓存"))
    source = tmp_path / "音频.wav"
    calls = []

    def recognize(media, *, fresh=False, **options):
        calls.append(fresh)
        duration = prepare_wav(media, fresh=fresh)[1]
        return {"engine": "测试识别适配器", "model": "测试模型",
                "lang": "zh", "duration": duration,
                "segments": [{"start": 0, "end": duration, "text": "识别结果"}]}

    monkeypatch.setattr(asr, "get_transcript", recognize)
    write_audio(source, 1)
    first = asr.get_transcript_cached("测试", "相同素材", str(source))
    assert asr.get_transcript_cached("测试", "相同素材", str(source)) == first
    assert calls == [False]
    write_audio(source, 2)
    second = asr.get_transcript_cached("测试", "相同素材", str(source))
    assert second["duration"] == pytest.approx(2)
    assert second["provenance"]["media_sha256"] != first["provenance"]["media_sha256"]
    assert asr.get_transcript_cached("测试", "相同素材", str(source), fresh=True)["duration"] == 2
    assert calls == [False, False, True]


def test_download_does_not_consume_unrelated_cached_media(tmp_path, monkeypatch):
    import yt_dlp

    from vidlens.agentio import BlockedError
    from vidlens.platforms.media import download_media, media_cache_path

    monkeypatch.setenv("vidlens_CACHE", str(tmp_path / "管理缓存"))
    video = media_cache_path("bilibili", "测试素材", "video")
    video.parent.mkdir(parents=True, exist_ok=True)
    original = "原有视频".encode() * 1024
    video.write_bytes(original)

    class EmptyDownload:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *arguments):
            return False

        def download(self, urls):
            return 0

    monkeypatch.setattr(yt_dlp, "YoutubeDL", EmptyDownload)
    with pytest.raises(BlockedError):
        download_media({"platform": "bilibili", "video_id": "测试素材",
                        "webpage_url": "测试来源"}, kind="audio", cookiefile=None)
    assert video.read_bytes() == original


def test_real_downloader_reports_cache_and_preserves_failed_refresh(local_video, tmp_path, monkeypatch):
    import functools
    import http.server
    import threading

    from vidlens.agentio import VidlensError
    from vidlens.platforms import bilibili
    from vidlens.urls import Platform, Target

    monkeypatch.setenv("vidlens_CACHE", str(tmp_path / "管理缓存"))
    # 使用本地 HTTP 源验证真实 yt-dlp 与视频来源适配器的下载接缝。
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(local_video.parent)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        from urllib.parse import quote
        url = f"http://127.0.0.1:{server.server_port}/{quote(local_video.name)}"
        target = Target(Platform.bilibili, url, "离线下载验证")
        metadata = {"platform": "bilibili", "video_id": target.video_id, "webpage_url": url}
        first = bilibili.download(target, metadata, None, "video", 1080, False)
        assert first["source_level"] == "ytdlp"
        second = bilibili.download(target, metadata, None, "video", 1080, False)
        assert second["source_level"] == "cache"
        from pathlib import Path
        preserved = Path(first["path"]).read_bytes()
        metadata["webpage_url"] = url + "-不存在"
        with pytest.raises(VidlensError):
            bilibili.download(target, metadata, None, "video", 1080, True)
        assert Path(first["path"]).read_bytes() == preserved
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_rules_execution_order_invalidates_cache(tmp_path, monkeypatch):
    from vidlens import asr
    from vidlens.lexicon import normalize_text

    monkeypatch.setenv("vidlens_CACHE", str(tmp_path / "管理缓存"))
    source = tmp_path / "音频.wav"
    write_audio(source, 1)

    def recognize(media, *, glossary, **options):
        return {"engine": "测试识别适配器", "model": "测试模型", "lang": "zh", "duration": 1,
                "segments": [{"start": 0, "end": 1, "text": normalize_text("甲", glossary)}]}

    monkeypatch.setattr(asr, "get_transcript", recognize)
    first = asr.get_transcript_cached("测试", "字幕", str(source), glossary={"甲": "乙", "乙": "丙"})
    second = asr.get_transcript_cached("测试", "字幕", str(source), glossary={"乙": "丙", "甲": "乙"})
    assert first["segments"][0]["text"] == "丙"
    assert second["segments"][0]["text"] == "乙"


def test_failed_cache_record_keeps_previous_media(tmp_path, monkeypatch):
    import json
    from pathlib import Path

    import yt_dlp

    from vidlens.agentio import VidlensError
    from vidlens.platforms import media
    from vidlens.存储 import fingerprint

    monkeypatch.setenv("vidlens_CACHE", str(tmp_path / "管理缓存"))
    old = media.media_cache_path("bilibili", "素材", "video")
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_bytes(b"old" * 1024)
    record = old.parent / "video.cache.json"
    record.write_text(json.dumps({"file": old.name, "sha256": fingerprint(old)}), encoding="utf-8")
    old_record = record.read_bytes()

    class Download:
        def __init__(self, options):
            self.output = Path(options["outtmpl"].replace("%(ext)s", "mp4"))

        def __enter__(self):
            return self

        def __exit__(self, *arguments):
            return False

        def download(self, urls):
            self.output.write_bytes(b"new" * 1024)

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Download)

    def denied(*arguments):
        raise PermissionError("缓存记录无法写入")

    monkeypatch.setattr(media, "write_json", denied)
    with pytest.raises(VidlensError) as caught:
        media.download_media({"platform": "bilibili", "video_id": "素材", "webpage_url": "来源"},
                             kind="video", cookiefile=None, fresh=True)
    assert caught.value.errcode == "cache_write_failed"
    assert old.read_bytes() == b"old" * 1024
    assert record.read_bytes() == old_record


def test_fresh_download_repairs_corrupted_content_address(tmp_path, monkeypatch):
    from pathlib import Path

    import yt_dlp

    from vidlens.platforms.media import download_media

    monkeypatch.setenv("vidlens_CACHE", str(tmp_path / "管理缓存"))

    class Download:
        def __init__(self, options):
            self.output = Path(options["outtmpl"].replace("%(ext)s", "mp4"))

        def __enter__(self):
            return self

        def __exit__(self, *arguments):
            return False

        def download(self, urls):
            self.output.write_bytes(b"correct" * 1024)

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Download)
    metadata = {"platform": "bilibili", "video_id": "修复测试", "webpage_url": "来源"}
    first = download_media(metadata, kind="video", cookiefile=None)
    Path(first["path"]).write_bytes(b"corrupted" * 1024)
    refreshed = download_media(metadata, kind="video", cookiefile=None, fresh=True)
    assert Path(refreshed["path"]).read_bytes() == b"correct" * 1024
