"""ffmpeg resolution and small wrappers.

Order: $VIDTOOL_FFMPEG (exe or dir) -> system PATH -> static binary bundled
with the `imageio-ffmpeg` wheel. No ffprobe dependency: durations come from
yt-dlp metadata or by parsing `ffmpeg -i` stderr.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from functools import lru_cache

from .agentio import DependencyError


@lru_cache(maxsize=1)
def ffmpeg_path() -> str:
    env = os.environ.get("VIDTOOL_FFMPEG")
    if env:
        p = env if env.endswith(".exe") else os.path.join(env, "ffmpeg.exe")
        if os.path.isfile(p):
            return p
        p = env if os.path.basename(env).startswith("ffmpeg") else p
        if os.path.isfile(p):
            return p
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:  # not installed / wheel without binary
        raise DependencyError(
            f"找不到可用的 ffmpeg ({e})",
            hint="运行 `vidtool doctor` 查看详情;或 `uv sync` 安装依赖,"
                 "或设置 VIDTOOL_FFMPEG 指向本机 ffmpeg 可执行文件/目录。") from e


def _run(args: list[str], *, timeout: float = 1200.0) -> subprocess.CompletedProcess:
    cmd = [ffmpeg_path(), "-hide_banner", "-nostdin", *args]
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def version() -> str:
    out = _run(["-version"]).stdout
    m = re.search(r"ffmpeg version (\S+)", out)
    return m.group(1) if m else "unknown"


def probe_duration(media_path: str) -> float | None:
    """Duration in seconds via `ffmpeg -i` stderr parsing (no ffprobe needed)."""
    r = _run(["-i", media_path], timeout=120)
    for line in r.stderr.splitlines():
        m = re.match(r"\s*Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", line)
        if m:
            h, mi, s = m.groups()
            return int(h) * 3600 + int(mi) * 60 + float(s)
    return None


def make_wav(media_path: str, wav_path: str) -> str:
    """16 kHz mono PCM wav for ASR."""
    r = _run(["-y", "-i", media_path, "-vn", "-ac", "1", "-ar", "16000",
              "-c:a", "pcm_s16le", wav_path])
    if r.returncode != 0 or not os.path.isfile(wav_path):
        from .agentio import VidtoolError
        raise VidtoolError(
            "音频抽取失败 (ffmpeg)",
            hint=f"ffmpeg stderr 尾部: {r.stderr[-400:]};文件可能无音轨或已损坏,"
                 "可先运行 `vidtool doctor`。", errcode="ffmpeg_failed")
    return wav_path
