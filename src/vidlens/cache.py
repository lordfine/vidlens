"""Cache management.

Layout (base = $vidlens_CACHE or %LOCALAPPDATA%/vidlens):
  cache/<platform>/<video_id>/meta.json        — normalized metadata
  cache/<platform>/<video_id>/media/*          — downloaded video/audio
  cache/<platform>/<video_id>/jobs/<stamp>-*/  — per-command outputs (subs, frames…)
  models/                                      — ASR models
  cookies/                                     — generated netscape cookie files (gitignored)

LRU policy: `clean` trims oldest-accessed *media* dirs first, then jobs.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

DEFAULT_MAX_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB


def base_dir() -> Path:
    env = os.environ.get("vidlens_CACHE")
    if env:
        return Path(env)
    local = os.environ.get("LOCALAPPDATA")
    root = Path(local) if local else Path.home() / ".local" / "share"
    return root / "vidlens"


def cache_root() -> Path:
    p = base_dir() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def models_dir() -> Path:
    p = base_dir() / "models"
    p.mkdir(parents=True, exist_ok=True)
    return p


def cookies_dir() -> Path:
    p = base_dir() / "cookies"
    p.mkdir(parents=True, exist_ok=True)
    return p


def video_dir(platform: str, video_id: str) -> Path:
    vid = "".join(c for c in video_id if c.isalnum() or c in "-_")[:120]
    p = cache_root() / platform / vid
    p.mkdir(parents=True, exist_ok=True)
    return p


def job_dir(platform: str, video_id: str, label: str) -> Path:
    """Fresh timestamped output dir: cache/<pf>/<id>/jobs/<label>-<stamp>."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    root = video_dir(platform, video_id) / "jobs" / f"{label}-{stamp}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _dir_size(p: Path) -> int:
    total = 0
    for f in p.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def _touch(p: Path) -> None:
    try:
        os.utime(p, None)
    except OSError:
        pass


def stats() -> dict:
    root = base_dir()
    media = jobs = 0
    cache = cache_root()
    for vd in cache.glob("*/*"):
        m = vd / "media"
        if m.is_dir():
            media += _dir_size(m)
        j = vd / "jobs"
        if j.is_dir():
            jobs += _dir_size(j)
    models = _dir_size(models_dir()) if models_dir().exists() else 0
    return {
        "base_dir": str(root),
        "media_bytes": media,
        "jobs_bytes": jobs,
        "models_bytes": models,
        "total_bytes": media + jobs + models,
    }


def list_videos() -> list[dict]:
    out = []
    for vd in sorted(cache_root().glob("*/*")):
        meta_f = vd / "meta.json"
        entry = {
            "platform": vd.parent.name,
            "video_id": vd.name,
            "dir": str(vd),
            "bytes": _dir_size(vd),
            "last_used": time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(vd.stat().st_mtime)),
            "has_meta": meta_f.is_file(),
        }
        out.append(entry)
    return out


def clean(*, max_bytes: int = DEFAULT_MAX_BYTES, all_: bool = False) -> dict:
    """Trim cache to max_bytes (oldest media first). all_=True removes everything."""
    cache = cache_root()
    if all_:
        removed = _dir_size(cache)
        shutil.rmtree(cache)
        cache.mkdir(parents=True, exist_ok=True)
        return {"removed_bytes": removed, "mode": "all"}

    s = stats()
    target = max_bytes
    if s["media_bytes"] + s["jobs_bytes"] <= target:
        return {"removed_bytes": 0, "mode": "lru", "kept_bytes": s["total_bytes"]}

    # candidates: per-video media and job dirs, oldest first
    cands: list[tuple[float, Path, int]] = []
    for vd in cache.glob("*/*"):
        for sub, is_media in ((vd / "media", True), (vd / "jobs", False)):
            if sub.is_dir():
                cands.append((sub.stat().st_mtime, sub, _dir_size(sub)))
    cands.sort()
    removed = 0
    for _, sub, size in cands:
        if s["media_bytes"] + s["jobs_bytes"] - removed <= target:
            break
        shutil.rmtree(sub, ignore_errors=True)
        removed += size
    return {"removed_bytes": removed, "mode": "lru",
            "kept_bytes": s["media_bytes"] + s["jobs_bytes"] - removed}
