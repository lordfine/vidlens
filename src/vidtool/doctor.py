"""Self-diagnosis: `vidtool doctor` — JSON status of every dependency."""

from __future__ import annotations

import os
import sys

from . import __version__


def _check(name: str):
    def deco(fn):
        fn._name = name
        return fn
    return deco


def run_checks() -> dict:
    checks = []

    # python
    ok = sys.version_info >= (3, 11)
    checks.append({"name": "python", "ok": ok,
                   "detail": sys.version.split()[0]})

    # ffmpeg
    try:
        from . import ffutil
        v = ffutil.version()
        checks.append({"name": "ffmpeg", "ok": True,
                       "detail": f"{v} @ {ffutil.ffmpeg_path()}"})
    except Exception as e:
        checks.append({"name": "ffmpeg", "ok": False, "detail": str(e)})

    # yt-dlp
    try:
        import yt_dlp
        checks.append({"name": "yt-dlp", "ok": True,
                       "detail": yt_dlp.version.__version__})
    except Exception as e:
        checks.append({"name": "yt-dlp", "ok": False, "detail": str(e)})

    # sherpa-onnx + model (preload onnxruntime to dodge stale System32 dll)
    try:
        from .asr.sensevoice import _import_sherpa
        _import_sherpa()
        from .asr import sensevoice
        ready = sensevoice.model_ready()
        checks.append({"name": "sherpa-onnx", "ok": True,
                       "detail": f"installed; model {'ready' if ready else 'NOT downloaded (auto on first transcribe)'}"
                                 f" @ {sensevoice._model_dir()}"})
    except Exception as e:
        checks.append({"name": "sherpa-onnx", "ok": False,
                       "detail": f"{e} (run `uv sync`)"})

    # network reachability
    import httpx
    for host in ("https://www.bilibili.com", "https://www.douyin.com"):
        try:
            with httpx.Client(follow_redirects=True, timeout=8,
                              headers={"User-Agent": "Mozilla/5.0"}) as c:
                r = c.get(host)
            checks.append({"name": f"net:{host.split('//')[1]}",
                           "ok": r.status_code < 500, "detail": f"HTTP {r.status_code}"})
        except Exception as e:
            checks.append({"name": f"net:{host.split('//')[1]}",
                           "ok": False, "detail": str(e)[:120]})

    # cache writable
    from . import cache as cache_mod
    try:
        p = cache_mod.base_dir() / ".write_test"
        p.write_text("ok", encoding="utf-8")
        p.unlink()
        checks.append({"name": "cache", "ok": True,
                       "detail": str(cache_mod.base_dir())})
    except Exception as e:
        checks.append({"name": "cache", "ok": False, "detail": str(e)})

    hard_fail = [c for c in checks if not c["ok"] and
                 c["name"] in ("python", "ffmpeg", "yt-dlp", "cache")]
    status = "degraded" if any(not c["ok"] for c in checks) else "ok"
    return {
        "ok": not hard_fail,
        "status": status,
        "version": __version__,
        "checks": checks,
        "hint": None if not hard_fail else
        "修复失败的必选项(ffmpeg/yt-dlp/cache)后重试;网络项失败只影响对应平台。",
    }
