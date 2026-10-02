"""Bilibili platform: metadata, CC/AI subtitles, media download via yt-dlp."""

from __future__ import annotations

import yt_dlp

from .. import ffutil
from ..agentio import NotSupportedError, vidlensError
from ..urls import Target
from . import interpret_ytdlp_error, load_meta, save_meta, ytdlp_opts
from . import media as media_mod


def _info(target: Target, cookiefile: str | None, download: bool = False) -> dict:
    opts = ytdlp_opts(cookiefile=cookiefile)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(target.url, download=download)
    except Exception as e:
        raise interpret_ytdlp_error("bilibili", e)


def fetch_meta(target: Target, cookiefile: str | None,
               fresh: bool = False) -> dict:
    if target.kind in ("bangumi", "cheese"):
        raise NotSupportedError(
            f"暂不支持番剧/课程类内容: {target.url}",
            hint="v1 聚焦普通视频(BV)。番剧与课程请在"
                 "https://github.com/ 提需求,或先改用普通视频链接。")
    vid = target.video_id or ""
    cached = None if fresh else load_meta("bilibili", vid)
    if cached:
        return cached
    info = _info(target, cookiefile)
    vid = info.get("id") or vid
    meta = {
        "platform": "bilibili",
        "video_id": vid,
        "webpage_url": info.get("webpage_url") or target.url,
        "title": info.get("title"),
        "uploader": info.get("uploader") or info.get("channel"),
        "duration": info.get("duration"),
        "description": (info.get("description") or "")[:2000],
        "thumbnail": info.get("thumbnail"),
        "upload_date": info.get("upload_date"),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "page": _pick_page(info),
        "pages": [
            {"id": p.get("id"), "title": p.get("title"),
             "duration": p.get("duration")}
            for p in (info.get("entries") or [])[:50]
        ] if info.get("_type") == "playlist" else [],
        "subtitle_tracks": _tracks(info),
    }
    save_meta("bilibili", vid, meta)
    return meta


def _pick_page(info: dict) -> int:
    # single BV with multiple pages: yt-dlp exposes entries via playlist
    if info.get("_type") == "playlist":
        idx = info.get("playlist_index") or 1
        return int(idx)
    return 1


def _tracks(info: dict) -> list[dict]:
    out = []
    for lang, lst in (info.get("subtitles") or {}).items():
        if lst:
            out.append({"lang": lang, "name": lst[0].get("name", lang),
                        "auto": False})
    for lang, lst in (info.get("automatic_captions") or {}).items():
        if lst and not any(t["lang"] == lang for t in out):
            out.append({"lang": lang, "name": lst[0].get("name", f"{lang} (AI)"),
                        "auto": True})
    return out


LANG_PREF = ["zh-Hans", "zh-CN", "zh", "zh-Hant", "zh-TW", "en", "en-US"]


def pick_lang(tracks: list[dict], want: str | None) -> dict | None:
    if want:
        for t in tracks:
            if t["lang"] == want:
                return t
        low = want.lower()
        for t in tracks:
            if low in t["lang"].lower():
                return t
        return None
    for pref in LANG_PREF:
        for t in tracks:
            if t["lang"] == pref and not t["auto"]:
                return t
    for pref in LANG_PREF:
        for t in tracks:
            if t["lang"] == pref:
                return t
    return tracks[0] if tracks else None


def fetch_subtitles(target: Target, meta: dict, cookiefile: str | None,
                    lang: str | None = None) -> tuple[dict | None, list[dict]]:
    """Returns (track, segments). track None => no CC available."""
    info = _info(target, cookiefile)
    tracks = _tracks(info)
    track = pick_lang(tracks, lang)
    if not track:
        return None, []
    pool = (info.get("subtitles") or {}) if not track["auto"] else \
        (info.get("automatic_captions") or {})
    entries = pool.get(track["lang"]) or []
    if not entries:
        return track, []
    # prefer a text format we can parse
    order = {"json": 0, "srt": 1, "vtt": 2}
    entry = sorted(entries, key=lambda e: order.get(e.get("ext"), 9))[0]
    text = media_mod.fetch_url_text(
        entry["url"], cookiefile=cookiefile,
        referer="https://www.bilibili.com/")
    segs = media_mod.parse_any_subtitle(text, entry.get("ext", ""))
    if not segs:
        # try another available format (e.g. json3)
        for e in entries[1:]:
            t2 = media_mod.fetch_url_text(e["url"], cookiefile=cookiefile,
                                          referer="https://www.bilibili.com/")
            segs = media_mod.parse_any_subtitle(t2, e.get("ext", ""))
            if segs:
                break
    return track, segs


def download(target: Target, meta: dict, cookiefile: str | None, kind: str,
             max_height: int, fresh: bool) -> str:
    try:
        ff = ffutil.ffmpeg_path()
    except Exception:
        ff = None
    return str(media_mod.download_media(
        meta, kind=kind, cookiefile=cookiefile, max_height=max_height,
        fresh=fresh, ffmpeg_location=ff))
