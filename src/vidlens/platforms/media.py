"""Shared media download (yt-dlp wrapper) + subtitle parsing helpers."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

import httpx

from .. import cache as cache_mod
from ..agentio import AuthNeededError, BlockedError, VidlensError
from ..存储 import fingerprint, write_json
from . import _cookie_hint, interpret_ytdlp_error, ytdlp_opts

# ---------------------------------------------------------------- media ----

def media_cache_path(platform: str, video_id: str, kind: str) -> Path:
    name = "video.mp4" if kind == "video" else "audio.m4a"
    return cache_mod.video_dir(platform, video_id) / "media" / name


def download_media(meta: dict, *, kind: str, cookiefile: str | None,
                   max_height: int = 1080, fresh: bool = False,
                   ffmpeg_location: str | None = None) -> dict:
    """Download video or best-audio into the cache; returns local path.
    Holds the per-video write lock so concurrent runs can't corrupt files."""
    from ..locking import cache_write_lock
    try:
        with cache_write_lock(media_cache_path(meta["platform"],
                                               meta["video_id"], kind).parent):
            return _download_media_locked(
                meta, kind=kind, cookiefile=cookiefile, max_height=max_height,
                fresh=fresh, ffmpeg_location=ffmpeg_location)
    except OSError as error:
        raise VidlensError("媒体缓存写入失败，已保留此前缓存", errcode="cache_write_failed",
                           hint="检查缓存目录权限和磁盘空间后重试。") from error


def _download_media_locked(meta: dict, *, kind: str, cookiefile: str | None,
                           max_height: int = 1080, fresh: bool = False,
                           ffmpeg_location: str | None = None) -> dict:
    """在独立暂存目录下载，确认本次产物后再发布到共享缓存。"""
    platform, vid = meta["platform"], meta["video_id"]
    dest = media_cache_path(platform, vid, kind)
    cached = cached_media(platform, vid, kind)
    if cached and not fresh:
        return {"path": str(cached), "source_level": "cache", "retried": False}
    dest.parent.mkdir(parents=True, exist_ok=True)

    import yt_dlp

    if kind == "video":
        fmt = (f"bv*[height<=?{max_height}][ext=mp4]+ba[ext=m4a]"
               f"/b[height<=?{max_height}]/bv*+ba/b")
    else:
        fmt = "ba[ext=m4a]/ba/b"
    opts = ytdlp_opts(cookiefile=cookiefile, ffmpeg=ffmpeg_location)
    with tempfile.TemporaryDirectory(dir=dest.parent, prefix=f".{kind}-") as temporary:
        staging = Path(temporary)
        opts.update({"format": fmt, "outtmpl": str(staging / f"{kind}.%(ext)s"),
                     "merge_output_format": "mp4", "overwrites": True})
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([meta["webpage_url"]])
        except Exception as e:
            raise interpret_ytdlp_error(platform, e) from e
        extensions = {".mp4", ".mkv", ".webm", ".m4a", ".mp3", ".wav", ".ogg", ".opus", ".aac"}
        produced = [p for p in staging.iterdir() if p.is_file() and p.stem == kind
                    and p.suffix.lower() in extensions and p.stat().st_size > 1024]
        if len(produced) != 1:
            raise BlockedError("下载未产生唯一完整媒体文件",
                               hint="原有缓存已保留；稍后重试或带有效 --cookie 重试。")
        digest = fingerprint(produced[0])
        dest = dest.with_name(f"{kind}-{digest}{produced[0].suffix}")
        created = not dest.exists()
        backup = None
        if not created and fingerprint(dest) != digest:
            backup = staging / f"previous{dest.suffix}"
            shutil.copyfile(dest, backup)
        if created or backup:
            produced[0].replace(dest)
        try:
            write_json(dest.parent / f"{kind}.cache.json",
                       {"file": dest.name, "sha256": digest, "source_level": "ytdlp"})
        except OSError:
            if backup:
                backup.replace(dest)
            elif created:
                dest.unlink(missing_ok=True)
            raise
    return {"path": str(dest.resolve()), "source_level": "ytdlp", "retried": False}


def cached_media(platform: str, video_id: str, kind: str) -> Path | None:
    """只接受该种媒体的缓存记录，兼容旧版的确定文件名。"""
    expected = media_cache_path(platform, video_id, kind)
    record = expected.parent / f"{kind}.cache.json"
    try:
        if record.is_file():
            information = json.loads(record.read_text(encoding="utf-8"))
            path = (expected.parent / information["file"]).resolve()
            if (path.parent == expected.parent.resolve()
                    and (path.stem == kind or path.stem.startswith(f"{kind}-"))
                    and path.is_file() and path.stat().st_size > 1024
                    and fingerprint(path) == information["sha256"]):
                path.touch()
                return path
            return None
        if expected.is_file() and expected.stat().st_size > 1024:
            expected.touch()
            return expected.resolve()
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


# ------------------------------------------------------------- subtitles ----

def parse_ts(t: str) -> float:
    m = re.match(r"(\d+):(\d+):(\d+)[.,](\d+)", t.strip())
    if m:
        h, mi, s, ms = m.groups()
        return int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000
    m = re.match(r"(\d+):(\d+)[.,](\d+)", t.strip())
    if m:
        mi, s, ms = m.groups()
        return int(mi) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000
    return 0.0


def parse_srt(text: str) -> list[dict]:
    segs, cur = [], None
    for line in text.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if not line:
            cur = None
            continue
        ts = re.match(r"((?:\d+:)?\d+:\d+[.,]\d+)\s*-->\s*((?:\d+:)?\d+:\d+[.,]\d+)", line)
        if ts:
            cur = {"start": parse_ts(ts.group(1)), "end": parse_ts(ts.group(2)),
                   "text": ""}
            segs.append(cur)
            continue
        if cur is not None and not line.isdigit():
            cur["text"] = (cur["text"] + "\n" + line).strip()
    return segs


def parse_vtt(text: str) -> list[dict]:
    body = re.sub(r"^WEBVTT.*?\n\n", "", text, flags=re.S)
    return parse_srt(body)


def parse_bili_json(text: str) -> list[dict]:
    data = json.loads(text)
    return [{"start": float(b.get("from", 0)), "end": float(b.get("to", 0)),
             "text": b.get("content", "")} for b in data.get("body", [])]


def fetch_url_text(url: str, cookiefile: str | None = None,
                   referer: str | None = None) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                             "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"}
    if referer:
        headers["Referer"] = referer
    cookies: dict[str, str] = {}
    if cookiefile:
        for line in Path(cookiefile).read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or "\t" not in line:
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                cookies[parts[5]] = parts[6]
    try:
        with httpx.Client(timeout=30, follow_redirects=True,
                          headers=headers, cookies=cookies) as c:
            response = c.get(url)
            response.raise_for_status()
            return response.text
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        if status == 401:
            platform = "bilibili" if "bilibili" in (referer or url) else "douyin"
            raise AuthNeededError("字幕来源需要登录", hint=_cookie_hint(platform)) from error
        if status == 404:
            raise VidlensError("字幕来源已经失效", errcode="content_gone",
                               hint="用 --fresh 刷新元信息，或提供本地字幕文件。") from error
        raise BlockedError(f"字幕来源暂时不可访问: HTTP {status}",
                           hint="稍后重试；风控持续时使用已有授权的有效登录态。") from error
    except httpx.HTTPError as error:
        raise BlockedError("字幕读取超时或网络连接失败",
                           hint="检查网络后重试，或通过 --subtitle-file 提供已有字幕。") from error


def parse_any_subtitle(text: str, fmt_hint: str = "") -> list[dict]:
    t = text.strip().lstrip("\ufeff")
    if t.startswith(("{", "[")):
        data = json.loads(t)
        if isinstance(data, dict) and "body" in data:
            return parse_bili_json(t)
        records = data.get("segments", []) if isinstance(data, dict) else data
        if not isinstance(records, list):
            raise ValueError("字幕片段必须是列表")
        return [{"start": float(record["start"]), "end": float(record["end"]),
                 "text": str(record["text"])} for record in records]
    if "WEBVTT" in t[:64]:
        return parse_vtt(t)
    return parse_srt(t)


# ------------------------------------------------------------- rendering ----

def _fmt_ts(sec: float, comma: bool = True) -> str:
    ms = int(round(max(sec, 0) * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    sep = "," if comma else "."
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def render(segments: list[dict], fmt: str) -> str:
    from ..textflow import render_paragraphs, to_paragraphs
    if fmt == "json":
        return json.dumps(
            {
                "segments": [
                    {"start": round(s["start"], 3), "end": round(s["end"], 3),
                     "text": s["text"]} for s in segments],
                "paragraphs": to_paragraphs(segments),
            },
            ensure_ascii=False, indent=1)
    if fmt == "txt":
        # paragraph style with a [m:ss] anchor per block — the readable view
        return render_paragraphs(to_paragraphs(segments))
    if fmt == "vtt":
        out = ["WEBVTT", ""]
        for i, s in enumerate(segments, 1):
            out += [str(i),
                    f"{_fmt_ts(s['start'], comma=False)} --> "
                    f"{_fmt_ts(s['end'], comma=False)}",
                    s["text"], ""]
        return "\n".join(out)
    # srt
    out = []
    for i, s in enumerate(segments, 1):
        out += [str(i), f"{_fmt_ts(s['start'])} --> {_fmt_ts(s['end'])}",
                s["text"], ""]
    return "\n".join(out)


def save_subtitle(segments: list[dict], out_dir: Path,
                  base: str = "subtitle") -> dict[str, str]:
    """Write srt/vtt/txt/json variants; returns {fmt: path}."""
    if any((out_dir / f"{base}.{fmt}").exists() for fmt in ("srt", "vtt", "txt", "json")):
        raise VidlensError("输出位置已有字幕或转写文件", errcode="output_exists",
                           hint="使用新的 --out 目录；已有字幕和源文件不会被覆盖。")
    paths = {}
    for fmt in ("srt", "vtt", "txt", "json"):
        p = out_dir / f"{base}.{fmt}"
        p.write_text(render(segments, fmt), encoding="utf-8")
        paths[fmt] = str(p)
    return paths
