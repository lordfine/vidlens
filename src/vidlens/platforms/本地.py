"""本地媒体适配器：源文件只读，缓存保存内容寻址的媒体副本。"""

# ruff: noqa: N999
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .. import cache, ffutil
from ..agentio import VidlensError
from ..locking import cache_write_lock
from ..存储 import fingerprint
from .media import parse_any_subtitle


def fetch_meta(target, cookiefile=None, fresh=False) -> dict:
    source = Path(target.url)
    duration = ffutil.probe_duration(str(source))
    if not duration:
        raise VidlensError("本地文件不是可读取的媒体", errcode="bad_media",
                           hint="提供 FFmpeg 可解码的视频或音频文件。")
    return {**ffutil.probe_streams(str(source)),
            "platform": "local", "video_id": target.video_id, "title": source.stem,
            "duration": duration, "webpage_url": str(source), "uploader": None,
            "description": "本地媒体，源文件保持只读。", "subtitle_tracks": [], "pages": []}


def read_subtitles(path: Path, lang=None):
    try:
        records = parse_any_subtitle(path.read_text(encoding="utf-8-sig"), path.suffix.lstrip("."))
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise VidlensError("无法读取本地字幕", errcode="bad_subtitle",
                           hint="提供 UTF-8 编码且含有效时间戳的 SRT、VTT 或 JSON 字幕。") from error
    if not records:
        raise VidlensError("本地字幕没有有效时间段", errcode="bad_subtitle",
                           hint="检查字幕内容和格式，使用 SRT、VTT 或 JSON。")
    return {"lang": lang or "und", "name": "本地字幕", "auto": False,
            "source_sha256": fingerprint(path)}, records


def fetch_subtitles(target, metadata, cookiefile=None, lang=None):
    for suffix in (".srt", ".vtt", ".json"):
        sidecar = Path(target.url).with_suffix(suffix)
        if sidecar.is_file():
            return read_subtitles(sidecar, lang)
    return None, []


def download(target, meta, cookiefile, kind, max_height, fresh) -> dict:
    source = Path(target.url)
    directory = cache.video_dir("local", meta["video_id"]) / "media"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"source{source.suffix.lower()}"
    with cache_write_lock(directory):
        if not fresh and destination.is_file() and fingerprint(destination) == target.video_id:
            return {"path": str(destination.resolve()), "source_level": "cache", "retried": False}
        with tempfile.TemporaryDirectory(dir=directory, prefix=".local-") as temporary:
            staging = Path(temporary) / destination.name
            shutil.copyfile(source, staging)
            if fingerprint(staging) != target.video_id:
                raise VidlensError("复制期间本地源文件发生变化", errcode="media_changed",
                                   hint="等待源文件写入结束后重试。")
            staging.replace(destination)
    return {"path": str(destination.resolve()), "source_level": "local", "retried": False}
