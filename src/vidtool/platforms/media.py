"""Shared media download (yt-dlp wrapper) + subtitle parsing helpers."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import httpx

from .. import cache as cache_mod
from ..agentio import BlockedError, VidtoolError
from . import interpret_ytdlp_error, ytdlp_opts


# ---------------------------------------------------------------- media ----

def media_cache_path(platform: str, video_id: str, kind: str) -> Path:
    name = "video.mp4" if kind == "video" else "audio.m4a"
    return cache_mod.video_dir(platform, video_id) / "media" / name


def download_media(meta: dict, *, kind: str, cookiefile: str | None,
                   max_height: int = 1080, fresh: bool = False,
                   ffmpeg_location: str | None = None) -> Path:
    """Download video or best-audio into the cache; returns local path."""
    platform, vid = meta["platform"], meta["video_id"]
    dest = media_cache_path(platform, vid, kind)
    if dest.is_file() and dest.stat().st_size > 1024 and not fresh:
        try:
            dest.touch()
        except OSError:
            pass
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)

    import yt_dlp

    if kind == "video":
        fmt = (f"bv*[height<=?{max_height}][ext=mp4]+ba[ext=m4a]"
               f"/b[height<=?{max_height}]/bv*+ba/b")
    else:
        fmt = "ba[ext=m4a]/ba/b"
    opts = ytdlp_opts(cookiefile=cookiefile, ffmpeg=ffmpeg_location)
    opts.update({
        "format": fmt,
        "outtmpl": str(dest.with_suffix("")),
        "merge_output_format": "mp4",
        "overwrites": True,
        "continuedl": True,
    })
    # outtmpl without ext lets yt-dlp pick its own extension; normalize after
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([meta["webpage_url"]])
    except Exception as e:
        raise interpret_ytdlp_error(platform, e)

    # find what yt-dlp actually produced
    if not dest.is_file():
        produced = [p for p in dest.parent.glob("*")
                    if p.is_file() and p.stat().st_size > 1024]
        if not produced:
            raise BlockedError(
                "下载未产生任何文件",
                hint="平台可能拦截了媒体下载。带 --cookie 重试,或运行 "
                     "`vidtool doctor` 检查网络。")
        produced.sort(key=lambda p: p.stat().st_size, reverse=True)
        produced[0].replace(dest)
    return dest


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
        ts = re.match(r"(\d+:\d+:\d+[.,]\d+)\s*-->\s*(\d+:\d+:\d+[.,]\d+)", line)
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
    with httpx.Client(timeout=30, follow_redirects=True,
                      headers=headers, cookies=cookies) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.text


def parse_any_subtitle(text: str, fmt_hint: str = "") -> list[dict]:
    t = text.strip()
    if t.startswith("{"):
        return parse_bili_json(t)
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
    if fmt == "json":
        return json.dumps(
            {"segments": [
                {"start": round(s["start"], 3), "end": round(s["end"], 3),
                 "text": s["text"]} for s in segments]},
            ensure_ascii=False, indent=1)
    if fmt == "txt":
        lines, last = [], ""
        for s in segments:
            if s["text"] and s["text"] != last:
                lines.append(s["text"])
                last = s["text"]
        return "\n".join(lines) + "\n"
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
    paths = {}
    for fmt in ("srt", "vtt", "txt", "json"):
        p = out_dir / f"{base}.{fmt}"
        p.write_text(render(segments, fmt), encoding="utf-8")
        paths[fmt] = str(p)
    return paths
