"""本地媒体通过公开命令完成素材准备。"""

import json
from pathlib import Path

import pytest

from vidlens.cli import main


def test_local_prepare_with_subtitles(local_video, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("vidlens_CACHE", str(tmp_path / "管理缓存"))
    subtitle = local_video.with_suffix(".srt")
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,500\n本地视频证据\n", encoding="utf-8")
    assert main(["prepare", str(local_video), "--no-asr", "--frames-count", "5",
                 "--max-frames", "5", "--out", str(tmp_path / "素材包")]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["subtitle"]["source"] == "cc"
    manifest = json.loads(Path(result["files"]["manifest"]).read_text(encoding="utf-8"))
    assert manifest["video"]["platform"] == "local"
    assert manifest["frames"]["budget"]["selected"] <= 5
    assert Path(manifest["files"]["video_local"]).is_file()
    assert Path(manifest["files"]["audio_local"]).is_file()
    assert "本地视频证据" in Path(manifest["files"]["context_md"]).read_text(encoding="utf-8")


def test_export_survives_bundle_and_cache_relocation(local_video, tmp_path, monkeypatch, capsys):
    cache = tmp_path / "管理缓存"
    monkeypatch.setenv("vidlens_CACHE", str(cache))
    local_video.with_suffix(".srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,500\n可搬迁证据\n", encoding="utf-8")
    bundle = tmp_path / "原素材包"
    assert main(["prepare", str(local_video), "--no-asr", "--frames-count", "3",
                 "--max-frames", "3", "--out", str(bundle)]) == 0
    capsys.readouterr()
    exported = tmp_path / "导出素材包"
    assert main(["export", str(bundle), "--out", str(exported)]) == 0
    capsys.readouterr()
    bundle.rename(tmp_path / "已移走的原素材包")
    cache.rename(tmp_path / "已移走的缓存")
    relocated = tmp_path / "另一台电脑" / "素材包"
    relocated.parent.mkdir()
    exported.rename(relocated)
    assert main(["verify", str(relocated)]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["portable"] is True
    manifest = json.loads((relocated / "manifest.json").read_text(encoding="utf-8"))
    assert not Path(manifest["files"]["video_local"]).is_absolute()
    assert (relocated / manifest["files"]["video_local"]).is_file()
    assert str(bundle).replace("\\", "/") not in (relocated / "context.md").read_text(encoding="utf-8")
    original_directory = manifest["files"]["frames_dir"]
    manifest["files"]["frames_dir"] = str(tmp_path / "不存在的帧图目录")
    (relocated / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert main(["verify", str(relocated)]) == 1
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "bundle_invalid"
    manifest["files"]["frames_dir"] = original_directory
    (relocated / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (relocated / manifest["files"]["video_local"]).write_bytes(b"changed")
    assert main(["verify", str(relocated)]) == 1
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "bundle_invalid"


@pytest.mark.parametrize("suffix,content", [
    (".json", '{"segments":[{"start":0,"end":1,"text":"JSON字幕"}]}'),
    (".vtt", "WEBVTT\n\n00:00.000 --> 00:01.000\nVTT字幕\n"),
])
def test_local_subtitle_formats(local_video, tmp_path, monkeypatch, capsys, suffix, content):
    monkeypatch.setenv("vidlens_CACHE", str(tmp_path / "管理缓存"))
    subtitle = tmp_path / f"指定字幕{suffix}"
    subtitle.write_text(content, encoding="utf-8")
    assert main(["subs", str(local_video), "--no-asr", "--subtitle-file", str(subtitle)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["source"] == "cc"
    assert result["segments"] == 1


def test_audio_only_bundle_is_portable(tmp_path, monkeypatch, capsys):
    import wave

    monkeypatch.setenv("vidlens_CACHE", str(tmp_path / "管理缓存"))
    audio = tmp_path / "音频.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b"\0\0" * 16000)
    audio.with_suffix(".srt").write_text("1\n00:00:00,000 --> 00:00:00,900\n音频证据\n", encoding="utf-8")
    bundle = tmp_path / "音频素材包"
    assert main(["prepare", str(audio), "--no-asr", "--out", str(bundle)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["frames_count"] == 0
    assert result["files"]["video_local"] is None
    exported = tmp_path / "独立音频素材包"
    assert main(["export", str(bundle), "--out", str(exported)]) == 0
    capsys.readouterr()
    assert main(["verify", str(exported)]) == 0
    capsys.readouterr()
    assert main(["frames", str(audio)]) == 1
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "no_video"


def test_output_cannot_overwrite_source_subtitle(local_video, tmp_path, monkeypatch, capsys):
    import shutil

    monkeypatch.setenv("vidlens_CACHE", str(tmp_path / "管理缓存"))
    source = tmp_path / "subtitle.mp4"
    shutil.copyfile(local_video, source)
    subtitle = source.with_suffix(".srt")
    content = "1\n00:00:00,000 --> 00:00:01,000\n源字幕保持原样\n"
    subtitle.write_text(content, encoding="utf-8")
    assert main(["subs", str(source), "--out", str(tmp_path)]) == 1
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "output_exists"
    assert subtitle.read_text(encoding="utf-8") == content
