"""URL classification and short-link expansion.

Recognizes bilibili (video / b23.tv / bangumi / cheese) and douyin
(v.douyin.com share links, www.douyin.com/video/..., iesdouyin share).
Everything else is `unknown` and commands reject it with exit 1 + hint.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

import httpx

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class Platform(str, Enum):
    bilibili = "bilibili"
    douyin = "douyin"
    unknown = "unknown"


@dataclass
class Target:
    platform: Platform
    url: str                      # normalized http(s) URL (short links expanded)
    video_id: str | None = None   # BV id / aweme id when directly visible
    kind: str = "video"           # video | short | bangumi | cheese | discover
    raw: str = ""                 # original input
    extra: dict = field(default_factory=dict)


_BILI = [
    (re.compile(r"^https?://(?:(?:www|m)\.)?bilibili\.com/video/(BV[0-9A-Za-z]+)", re.I), "video"),
    (re.compile(r"^https?://(?:www\.)?b23\.tv/([0-9A-Za-z]+)", re.I), "short"),
    (re.compile(r"^https?://(?:www\.)?bilibili\.com/bangumi/play/(ep\d+|ss\d+)", re.I), "bangumi"),
    (re.compile(r"^https?://(?:www\.)?bilibili\.com/cheese/play/ep(\d+)", re.I), "cheese"),
]
_DOUYIN = [
    (re.compile(r"^https?://v\.douyin\.com/([0-9A-Za-z_-]+)", re.I), "short"),
    (re.compile(r"^https?://(?:www\.)?douyin\.com/video/(\d+)", re.I), "video"),
    (re.compile(r"^https?://(?:www\.)?iesdouyin\.com/share/video/(\d+)", re.I), "video"),
    (re.compile(r"^https?://(?:www\.)?douyin\.com/(?:note|discover)\?.*?item_id=(?:\d+)", re.I), "note"),
]


def _match(url: str) -> Target:
    for pat, kind in _BILI:
        if m := pat.match(url):
            return Target(Platform.bilibili, url, m.group(1), kind, raw=url)
    for pat, kind in _DOUYIN:
        if m := pat.match(url):
            return Target(Platform.douyin, url, m.group(1), kind, raw=url)
    return Target(Platform.unknown, url, kind="unknown", raw=url)


def normalize_input(text: str) -> str:
    """Accept raw URLs or text containing one; strip whitespace/trailing junk."""
    text = text.strip().strip("'\"")
    # text like "https://v.douyin.com/xxxx/ 复制此链接..." — keep first URL-ish token
    m = re.search(r"https?://\S+", text)
    return m.group(0).rstrip("，。,.") if m else text


def expand_short(target: Target, *, timeout: float = 15.0) -> Target:
    """Follow b23.tv / v.douyin.com redirects (incl. meta-refresh) to the real page."""
    if target.kind != "short":
        return target
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout,
                          headers={"User-Agent": UA}) as client:
            resp = client.get(target.url)
            final = str(resp.url)
            body = resp.text

            # some douyin share pages do a JS/meta redirect instead of 3xx
            if "v.douyin.com" in final:
                m = re.search(
                    r"(?:http-equiv=['\"]refresh['\"][^>]*url=|href=|url:?\s*['\"])"
                    r"(https?://[^'\"\s<>]+)", body[:6000], re.I)
                if m:
                    try:
                        resp = client.get(m.group(1))
                        final = str(resp.url)
                        body = resp.text
                    except httpx.HTTPError:
                        pass

            got = _match(final)
            if got.platform is not Platform.unknown:
                got.raw = target.raw
                return got
            # last resort: pull the aweme id out of the landing page
            for pat in (r"/video/(\d{15,})", r"video_id=(\d{15,})",
                        r"modal_id=(\d{15,})", r"item_ids?=(\d{15,})"):
                m = re.search(pat, body)
                if m:
                    return Target(Platform.douyin,
                                  f"https://www.douyin.com/video/{m.group(1)}",
                                  m.group(1), "video", raw=target.raw)
        raise _short_fail(target)
    except httpx.HTTPError:
        raise _short_fail(target)


def _short_fail(target: Target):
    from .agentio import BlockedError
    return BlockedError(
        f"无法展开短链: {target.url}",
        hint="网络或反爬拦截了短链跳转。可稍后重试,或直接提供完整链接"
             "(如 https://www.douyin.com/video/<id> 或 "
             "https://www.bilibili.com/video/BVxxxx),或用 --cookie 带登录态重试。")


def classify(url_or_text: str, *, expand: bool = True) -> Target:
    url = normalize_input(url_or_text)
    if not re.match(r"^https?://", url):
        from .agentio import vidlensError
        raise vidlensError(
            f"输入不是有效的视频链接: {url!r}",
            hint="提供抖音或B站的视频页/分享短链,例如 https://v.douyin.com/xxxx 或 "
                 "https://www.bilibili.com/video/BVxxxx。",
            errcode="bad_url")
    t = _match(url)
    if t.platform is Platform.unknown:
        from .agentio import NotSupportedError
        raise NotSupportedError(
            f"暂不支持该站点: {url}",
            hint="当前支持: bilibili.com / b23.tv、douyin.com / v.douyin.com。"
                 "其他平台(youtube、小红书等)在后续版本加入。")
    if expand and t.kind == "short":
        t = expand_short(t)
    return t
