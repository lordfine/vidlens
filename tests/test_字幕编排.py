"""字幕错误应在所有公开入口保持同一语义。"""

import pytest

from vidlens import prepare
from vidlens.agentio import AuthNeededError, BlockedError
from vidlens.urls import Platform, Target


@pytest.mark.parametrize("error_type", [AuthNeededError, BlockedError])
def test_bundle_preserves_subtitle_failure(tmp_path, error_type):
    class Source:
        @staticmethod
        def fetch_subtitles(*arguments, **options):
            raise error_type("字幕读取失败", hint="提供有效登录态后重试。")

        @staticmethod
        def download(*arguments, **options):
            raise AssertionError("字幕登录或风控失败时应先返回错误")

    target = Target(Platform.bilibili, "https://www.bilibili.com/video/BVtest", "BVtest")
    with pytest.raises(error_type):
        prepare.build(target, Source, {"platform": "bilibili", "video_id": "BVtest"},
                      out_dir=tmp_path)


@pytest.mark.parametrize("status,exit_code,error_code", [
    (401, 2, "auth_needed"), (403, 3, "blocked"), (429, 3, "blocked"), (503, 3, "blocked"),
    ("超时", 3, "blocked"),
])
def test_cli_maps_subtitle_http_failures(tmp_path, monkeypatch, capsys, status, exit_code, error_code):
    import json

    import httpx
    import yt_dlp

    from vidlens.cli import main

    monkeypatch.setenv("vidlens_CACHE", str(tmp_path / "管理缓存"))
    information = {"id": "BVtest", "subtitles": {"zh": [
        {"ext": "json", "url": "https://字幕来源.invalid/caption.json"}]}}

    class Extractor:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *arguments):
            return False

        def extract_info(self, *arguments, **options):
            return information

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Extractor)
    client = httpx.Client

    def respond(request):
        if status == "超时":
            raise httpx.ReadTimeout("字幕读取超时", request=request)
        return httpx.Response(status)

    monkeypatch.setattr(httpx, "Client", lambda **options: client(
        transport=httpx.MockTransport(respond), trust_env=False))
    assert main(["subs", "https://www.bilibili.com/video/BVtest"]) == exit_code
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == error_code
