"""Platform registry + shared yt-dlp plumbing."""

from __future__ import annotations

import json
from pathlib import Path

from .. import cache as cache_mod
from ..agentio import AuthNeededError, BlockedError, VidlensError


def write_cookie_file(platform: str, cookie: str) -> Path:
    """Turn a raw `k=v; k2=v2` string into a netscape cookie file."""
    lines = ["# Netscape HTTP Cookie File", ""]
    domain = ".bilibili.com" if platform == "bilibili" else ".douyin.com"
    for part in cookie.split(";"):
        if "=" not in part:
            continue
        k, v = part.strip().split("=", 1)
        lines.append(f"{domain}\tTRUE\t/\tTRUE\t0\t{k.strip()}\t{v.strip()}")
    p = cache_mod.cookies_dir() / f"{platform}.txt"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def cookie_from_args(platform: str, cookie: str | None,
                      cookie_file: str | None) -> str | None:
    """Resolve --cookie / --cookie-file into a yt-dlp cookiefile path."""
    if cookie_file:
        p = Path(cookie_file)
        if not p.is_file():
            raise VidlensError(f"cookie 文件不存在: {cookie_file}",
                               hint="检查 --cookie-file 路径,或改用 --cookie 直接传 "
                                    "SESSDATA=xxx / 抖音 cookie 字符串。",
                               errcode="bad_cookie")
        return str(p)
    if cookie:
        return str(write_cookie_file(platform, cookie))
    return None


def ytdlp_opts(*, cookiefile: str | None, ffmpeg: str | None = None) -> dict:
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "socket_timeout": 20,
        "nocheckcertificate": True,
        "retries": 3,
        "extractor_retries": 2,
        "windowsfilenames": True,
        "restrictfilenames": False,
    }
    if cookiefile:
        opts["cookiefile"] = cookiefile
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    return opts


def _cookie_hint(platform: str) -> str:
    """ADR-0004: the hint is an executable instruction for the agent."""
    how = ("B站: 浏览器 F12 → Network → 任意请求 → Request Headers → cookie "
           "整段(核心是 SESSDATA)" if platform == "bilibili" else
           "抖音: 浏览器 F12 → Network → 任意请求 → Request Headers → cookie 整段")
    return (f"两条路任选:(1) 你(agent)用浏览器自动化(CDP)直接从用户浏览器读取 "
            f"{platform} 的 cookie,整段传给 --cookie 重试;(2) 请用户按此法手动复制"
            f"提供——{how}。cookie 只在本机缓存目录暂存。")


def interpret_ytdlp_error(platform: str, e: Exception) -> VidlensError:
    """Map yt-dlp DownloadError to agent-friendly codes/hints."""
    msg = str(getattr(e, "msg", e))
    low = msg.lower()
    if "login" in low or "sessdata" in low or "cookie" in low and (
            "required" in low or "provide" in low or "log in" in low):
        return AuthNeededError(
            f"该内容需要登录态: {msg[:200]}",
            hint=_cookie_hint(platform))
    if any(k in low for k in ("403", "429", "captcha", "verify", "blocked",
                              "risk", "forbidden", "unavailable")):
        return BlockedError(
            f"被平台拦截或网络不可达: {msg[:200]}",
            hint="稍后重试;或用 --cookie 带登录态;抖音风控常见,换个链接或稍后再试。")
    if "private" in low or "removed" in low or "404" in low or "not found" in low:
        return VidlensError(
            f"内容不存在或不可访问: {msg[:200]}",
            hint="确认链接是否有效、视频是否被删除/设为私密。",
            errcode="content_gone")
    return BlockedError(
        f"yt-dlp 提取失败: {msg[:300]}",
        hint="可重试一次;若持续失败,用 --cookie 提供登录态,或运行 "
             "`vidlens doctor` 检查网络。")


def load_meta(platform: str, video_id: str) -> dict | None:
    f = cache_mod.video_dir(platform, video_id) / "meta.json"
    if f.is_file():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def save_meta(platform: str, video_id: str, meta: dict) -> None:
    f = cache_mod.video_dir(platform, video_id) / "meta.json"
    f.write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                 encoding="utf-8")
