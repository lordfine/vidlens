"""Douyin platform.

Primary extractor: the iesdouyin mobile share page (`_ROUTER_DATA`), which
works anonymously with an auto-registered ttwid cookie. Fallback: yt-dlp
(useful with a real user cookie). Play URLs are volatile, so media download
always re-fetches fresh page data instead of persisting URLs.
"""

from __future__ import annotations

import json
import re
import time

import yt_dlp

from .. import cache as cache_mod
from .. import ffutil
from ..agentio import (BlockedError, NotSupportedError, vidlensError)
from ..urls import Target
from . import interpret_ytdlp_error, load_meta, save_meta, ytdlp_opts
from . import media as media_mod

MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 "
             "Safari/604.1")
SHARE_PAGE = "https://www.iesdouyin.com/share/video/{vid}"

TTWID_URL = "https://ttwid.bytedance.com/ttwid/union/register/"
TTWID_PAYLOADS = [
    {"region": "cn", "aid": 1768, "needFid": False,
     "service": "www.ixigua.com",
     "migrate_info": {"ticket": "", "source": "node"},
     "cbUrlProtocol": "https", "union": True},
    {"region": "cn", "aid": 6383, "needFid": False,
     "service": "douyin.com",
     "migrate_info": {"ticket": "", "source": "node"},
     "cbUrlProtocol": "https", "union": True},
]
TTWID_MAX_AGE = 24 * 3600


# ------------------------------------------------------------- cookies ----

def ensure_ttwid_cookie() -> str | None:
    """Auto-register an anonymous ttwid cookie; cached ~24h."""
    cookie_file = cache_mod.cookies_dir() / "douyin-auto.txt"
    if cookie_file.is_file():
        age = time.time() - cookie_file.stat().st_mtime
        txt = cookie_file.read_text(encoding="utf-8")
        if age < TTWID_MAX_AGE and "ttwid=" in txt:
            return str(cookie_file)
    import httpx
    for payload in TTWID_PAYLOADS:
        try:
            with httpx.Client(timeout=15) as c:
                r = c.post(TTWID_URL, json=payload, headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                  "AppleWebKit/537.36 Chrome/131.0.0.0 "
                                  "Safari/537.36"})
            m = re.search(r"ttwid=([^;]+)", r.headers.get("set-cookie", ""))
            if m:
                cookie_file.write_text(
                    "# Netscape HTTP Cookie File\n"
                    ".douyin.com\tTRUE\t/\tTRUE\t0\tttwid\t" + m.group(1) + "\n"
                    ".iesdouyin.com\tTRUE\t/\tTRUE\t0\tttwid\t" + m.group(1) + "\n"
                    ".snssdk.com\tTRUE\t/\tTRUE\t0\tttwid\t" + m.group(1) + "\n",
                    encoding="utf-8")
                return str(cookie_file)
        except Exception:
            continue
    return None


def _cookie_jar(cookiefile: str | None) -> dict[str, str]:
    jar: dict[str, str] = {}
    cf = cookiefile or ensure_ttwid_cookie()
    if not cf:
        return jar
    p = _resolve_cookie_path(cf)
    if not p:
        return jar
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or "\t" not in line:
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            jar[parts[5]] = parts[6]
    return jar


def _resolve_cookie_path(cf: str):
    from pathlib import Path
    p = Path(cf)
    return p if p.is_file() else None


# --------------------------------------------------------- share page ----

def _fetch_item(vid: str, cookiefile: str | None) -> dict | None:
    """Fetch the iesdouyin share page and return item_list[0] (or None)."""
    import httpx
    vid = vid or ""
    if not vid.isdigit():
        return None
    jar = _cookie_jar(cookiefile)
    try:
        with httpx.Client(timeout=25, follow_redirects=True, cookies=jar,
                          headers={"User-Agent": MOBILE_UA}) as c:
            r = c.get(SHARE_PAGE.format(vid=vid))
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    m = re.search(r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*</script>",
                  r.text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
        page = data.get("loaderData", {}).get("video_(id)/page", {})
        info = page.get("videoInfoRes", {})
        items = info.get("item_list") or []
        return items[0] if items else None
    except Exception:
        return None


def _normalize_item(item: dict) -> dict:
    video = item.get("video") or {}
    author = item.get("author") or {}
    stats = item.get("statistics") or {}
    dur = video.get("duration")
    if isinstance(dur, (int, float)) and dur > 1000:  # ms -> s
        dur = dur / 1000
    cover = (video.get("cover") or {}).get("url_list") or []
    ct = item.get("create_time")
    upload = time.strftime("%Y%m%d", time.localtime(ct)) if ct else None
    return {
        "platform": "douyin",
        "video_id": str(item.get("aweme_id") or item.get("item_id") or ""),
        "webpage_url": (f"https://www.douyin.com/video/"
                        f"{item.get('aweme_id') or item.get('item_id')}"),
        "title": (item.get("desc") or "")[:300] or None,
        "uploader": author.get("nickname") or author.get("unique_id"),
        "duration": dur,
        "description": (item.get("desc") or "")[:2000],
        "thumbnail": cover[0] if cover else None,
        "upload_date": upload,
        "view_count": stats.get("play_count"),
        "like_count": stats.get("digg_count"),
        "page": 1,
        "pages": [],
        "subtitle_tracks": [],
        "aweme_type": item.get("aweme_type"),
    }


# -------------------------------------------------------------- public ----

def fetch_meta(target: Target, cookiefile: str | None,
               fresh: bool = False) -> dict:
    vid = target.video_id or ""
    cached = None if fresh else load_meta("douyin", vid)
    if cached:
        return cached

    item = _fetch_item(vid, cookiefile)
    if item:
        if item.get("images"):
            raise NotSupportedError(
                "该抖音内容是图集(不是视频)",
                hint="图集解析在后续版本支持;请提供视频类抖音链接。")
        meta = _normalize_item(item)
        if meta["video_id"]:
            save_meta("douyin", meta["video_id"], meta)
            return meta

    # fallback: yt-dlp (mostly useful with a real user cookie)
    opts = ytdlp_opts(cookiefile=cookiefile)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(target.url, download=False)
        if info and info.get("id"):
            meta = _ytdlp_normalize(info, target)
            save_meta("douyin", meta["video_id"], meta)
            return meta
    except Exception as e:
        err = interpret_ytdlp_error("douyin", e)
        if err.errcode == "content_gone":
            raise err
        # else: fall through to the blocked error below

    raise BlockedError(
        f"抖音解析失败(匿名被风控): {target.url}",
        hint="抖音对匿名请求风控较严。请让用户提供浏览器里的抖音 cookie"
             "(--cookie 'k=v; ...' 整段)后重试;或稍后再试/换个链接。")


def _ytdlp_normalize(info: dict, target: Target) -> dict:
    return {
        "platform": "douyin",
        "video_id": str(info.get("id") or target.video_id or ""),
        "webpage_url": info.get("webpage_url") or target.url,
        "title": info.get("title"),
        "uploader": info.get("uploader") or info.get("channel"),
        "duration": info.get("duration"),
        "description": (info.get("description") or "")[:2000],
        "thumbnail": info.get("thumbnail"),
        "upload_date": info.get("upload_date"),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "page": 1, "pages": [],
        "subtitle_tracks": [
            {"lang": lang, "name": (lst or [{}])[0].get("name", lang),
             "auto": False}
            for lang, lst in (info.get("subtitles") or {}).items() if lst],
    }


def _play_urls(item: dict) -> list[str]:
    """Candidate direct-play URLs: no-watermark first, then watermark."""
    video = item.get("video") or {}
    urls: list[str] = []
    pa = (video.get("play_addr") or {}).get("url_list") or []
    for u in pa:
        if "playwm" in u:
            urls.append(u.replace("playwm", "play"))
    urls.extend(pa)
    return urls


def download(target: Target, meta: dict, cookiefile: str | None, kind: str,
             max_height: int, fresh: bool) -> str:
    """Download media. Douyin videos are short mp4s; audio-kind callers get
    the same mp4 (ffmpeg extracts the wav for ASR downstream)."""
    import httpx

    dest = cache_mod.video_dir("douyin", meta["video_id"]) / "media" / "video.mp4"
    if dest.is_file() and dest.stat().st_size > 1024 and not fresh:
        try:
            dest.touch()
        except OSError:
            pass
        return str(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    vid = meta.get("video_id") or target.video_id
    item = _fetch_item(vid, cookiefile)
    if not item:
        # last resort: yt-dlp download (works with user cookie sometimes)
        try:
            ff = ffutil.ffmpeg_path()
        except Exception:
            ff = None
        try:
            return str(media_mod.download_media(
                meta, kind=kind, cookiefile=cookiefile, max_height=max_height,
                fresh=fresh, ffmpeg_location=ff))
        except Exception as e:
            raise interpret_ytdlp_error("douyin", e)

    jar = _cookie_jar(cookiefile)
    last_err = None
    for url in _play_urls(item):
        try:
            with httpx.Client(timeout=60, follow_redirects=True, cookies=jar,
                              headers={"User-Agent": MOBILE_UA,
                                       "Referer": "https://www.douyin.com/"}) as c:
                with c.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        last_err = f"HTTP {resp.status_code}"
                        continue
                    with open(dest, "wb") as f:
                        for chunk in resp.iter_bytes(1 << 20):
                            f.write(chunk)
            if dest.is_file() and dest.stat().st_size > 1024:
                return str(dest)
            last_err = "empty file"
        except Exception as e:
            last_err = str(e)[:200]
    raise BlockedError(
        f"抖音视频下载失败 ({last_err})",
        hint="播放直链可能过期/被风控。重试一次;仍失败则用 --cookie 提供"
             "浏览器抖音 cookie 后重试。")
