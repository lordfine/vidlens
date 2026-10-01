"""vidtool CLI — every command speaks JSON to stdout, errors to stderr."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from . import cache as cache_mod
from . import doctor as doctor_mod
from . import frames as frames_mod
from . import prepare as prepare_mod
from . import urls
from .platforms import media as media_mod
from .agentio import (DependencyError, NotSupportedError, VidtoolError,
                      emit, emit_error)
from .platforms import cookie_from_args

PLATFORMS = {"bilibili": "vidtool.platforms.bilibili",
             "douyin": "vidtool.platforms.douyin"}


def _platform_mod(target: urls.Target):
    import importlib
    name = target.platform.value
    if name not in PLATFORMS:
        raise NotSupportedError(f"暂不支持平台: {name}",
                                hint="当前支持 bilibili、douyin。")
    return importlib.import_module(PLATFORMS[name])


def _prep_url(url: str, cookie: str | None, cookie_file: str | None,
              fresh: bool):
    target = urls.classify(url)
    mod = _platform_mod(target)
    cookiefile = cookie_from_args(target.platform.value, cookie, cookie_file)
    return target, mod, cookiefile


def _out_dir(ns, platform: str, video_id: str, label: str) -> Path:
    if getattr(ns, "out", None):
        p = Path(ns.out)
        p.mkdir(parents=True, exist_ok=True)
        return p
    return cache_mod.job_dir(platform, video_id, label)


# ------------------------------------------------------------- commands ----

def cmd_meta(ns) -> int:
    target, mod, cookiefile = _prep_url(ns.url, ns.cookie, ns.cookie_file,
                                        ns.fresh)
    meta = mod.fetch_meta(target, cookiefile, fresh=ns.fresh)
    emit({
        "platform": meta["platform"],
        "video_id": meta["video_id"],
        "title": meta.get("title"),
        "uploader": meta.get("uploader"),
        "duration": meta.get("duration"),
        "webpage_url": meta.get("webpage_url"),
        "description": meta.get("description"),
        "subtitle_tracks": meta.get("subtitle_tracks") or [],
        "pages": meta.get("pages") or [],
        "cache_dir": str(cache_mod.video_dir(meta["platform"],
                                              meta["video_id"])),
        "hint": ("有字幕轨时优先 `vidtool subs`,无则 `vidtool transcribe`;"
                 "综合分析用 `vidtool prepare`。"),
    }, pretty=ns.pretty)
    return 0


def cmd_subs(ns) -> int:
    target, mod, cookiefile = _prep_url(ns.url, ns.cookie, ns.cookie_file,
                                        ns.fresh)
    meta = mod.fetch_meta(target, cookiefile, fresh=ns.fresh)
    out_dir = _out_dir(ns, meta["platform"], meta["video_id"], "subs")

    track, segs = None, []
    if hasattr(mod, "fetch_subtitles"):
        try:
            track, segs = mod.fetch_subtitles(target, meta, cookiefile,
                                              lang=ns.lang)
        except VidtoolError as e:
            if e.errcode in ("auth_needed", "blocked"):
                raise
            track, segs = None, []

    source = "cc"
    asr = None
    if not segs:
        if ns.no_asr:
            raise VidtoolError(
                "该视频没有可用字幕(CC)且 --no-asr 已指定",
                hint="去掉 --no-asr 自动语音转文字,或运行 "
                     "`vidtool transcribe`。", errcode="no_subtitles")
        audio = mod.download(target, meta, cookiefile, "audio", 1080, ns.fresh)
        from .asr import get_transcript_cached
        asr = get_transcript_cached(meta["platform"], meta["video_id"], audio,
                                    lang=ns.lang or "auto",
                                    model=ns.asr_model, fresh=ns.fresh)
        segs = asr["segments"]
        source = "asr"

    base = "subtitle" if source == "cc" else "transcript"
    files = media_mod.save_subtitle(segs, out_dir, base=base)
    fmt = ns.format
    emit({
        "source": source,
        "track": track,
        "engine": asr["engine"] if asr else None,
        "model": asr["model"] if asr else None,
        "lang": (track or {}).get("lang") if track else (asr or {}).get("lang"),
        "segments": len(segs),
        "files": files,
        "primary_file": files.get(fmt) or files.get("srt") or files.get("txt"),
        "out_dir": str(out_dir),
        "hint": "primary_file 是所请求格式的路径;json 含精确时间段,txt 适合直接阅读。",
    }, pretty=ns.pretty)
    return 0


def cmd_transcribe(ns) -> int:
    target, mod, cookiefile = _prep_url(ns.url, ns.cookie, ns.cookie_file,
                                        ns.fresh)
    meta = mod.fetch_meta(target, cookiefile, fresh=ns.fresh)
    out_dir = _out_dir(ns, meta["platform"], meta["video_id"], "asr")
    audio = mod.download(target, meta, cookiefile, "audio", 1080, ns.fresh)
    from .asr import get_transcript_cached
    tr = get_transcript_cached(meta["platform"], meta["video_id"], audio,
                               lang=ns.lang or "auto", model=ns.model,
                               fresh=ns.fresh)
    files = media_mod.save_subtitle(tr["segments"], out_dir, base="transcript")
    detail = out_dir / "asr.json"
    import json
    detail.write_text(json.dumps(tr, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    files["detail"] = str(detail)
    emit({
        "engine": tr["engine"],
        "model": tr["model"],
        "lang": tr["lang"],
        "duration": tr["duration"],
        "segments": len(tr["segments"]),
        "files": files,
        "primary_file": files.get(ns.format) or files.get("txt"),
        "out_dir": str(out_dir),
        "audio": audio,
    }, pretty=ns.pretty)
    return 0


def cmd_frames(ns) -> int:
    target, mod, cookiefile = _prep_url(ns.url, ns.cookie, ns.cookie_file,
                                        ns.fresh)
    meta = mod.fetch_meta(target, cookiefile, fresh=ns.fresh)
    out_dir = _out_dir(ns, meta["platform"], meta["video_id"], "frames")
    video = mod.download(target, meta, cookiefile, "video", ns.max_height,
                         ns.fresh)
    recs = frames_mod.extract(
        str(video), out_dir, mode=ns.mode, fps=ns.fps, count=ns.count,
        threshold=ns.threshold, size=ns.size, fmt=ns.format,
        duration=meta.get("duration"))
    cs = None
    if ns.contact_sheet:
        cs = frames_mod.contact_sheet(recs, out_dir / "contact_sheet.jpg")
    emit({
        "mode": ns.mode,
        "count": len(recs),
        "video": str(video),
        "frames": recs,
        "contact_sheet": cs,
        "out_dir": str(out_dir),
        "hint": "frames[].file 是图片绝对路径,agent 可直接按图片读取;时间戳在 t 字段(秒)。",
    }, pretty=ns.pretty)
    return 0


def cmd_prepare(ns) -> int:
    target, mod, cookiefile = _prep_url(ns.url, ns.cookie, ns.cookie_file,
                                        ns.fresh)
    meta = mod.fetch_meta(target, cookiefile, fresh=ns.fresh)
    overrides = {"mode": ns.frames_mode, "count": ns.frames_count,
                 "fps": ns.frames_fps, "size": ns.frames_size}
    out = Path(ns.out) if ns.out else None
    m = prepare_mod.build(
        target, mod, meta, granularity=ns.granularity,
        frames_overrides=overrides, no_asr=ns.no_asr, cookiefile=cookiefile,
        out_dir=out, fresh=ns.fresh, asr_model=ns.asr_model,
        asr_lang=ns.lang)
    emit({
        "granularity": m["granularity"],
        "video": m["video"],
        "subtitle": m["subtitle"],
        "frames_count": len(m["frames"]["files"]) if m["frames"] else 0,
        "scene_frames_count": len(m["frames"]["scene_files"]) if m["frames"] else 0,
        "files": m["files"],
        "hint": "先读 context.md(给 agent 的素材导读);帧图片可直接按图片读取;"
                "总结/分析由 agent 完成。",
    }, pretty=ns.pretty)
    return 0


def cmd_cache(ns) -> int:
    if ns.cache_cmd == "clean":
        r = cache_mod.clean(all_=ns.all)
        emit(r, pretty=ns.pretty)
        return 0
    if ns.cache_cmd == "stats" or ns.cache_cmd is None:
        emit(cache_mod.stats(), pretty=ns.pretty)
        return 0
    emit({"videos": cache_mod.list_videos(), "stats": cache_mod.stats()},
         pretty=ns.pretty)
    return 0


def cmd_doctor(ns) -> int:
    r = doctor_mod.run_checks()
    emit(r, pretty=ns.pretty)
    return 0 if r["ok"] else 4


# ------------------------------------------------------------------ argp ----

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vidtool",
        description="面向 agent 的视频解析工具(抖音/B站):字幕、语音转文字、"
                    "拆帧、综合素材包。所有输出为 JSON。")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, need_url=True):
        sp.add_argument("--pretty", action="store_true",
                        help="美化 JSON 输出(默认紧凑单行)")
        sp.add_argument("--cookie", help="平台 cookie 字符串(k=v; k2=v2)")
        sp.add_argument("--cookie-file", help="netscape 格式 cookie 文件路径")
        sp.add_argument("--fresh", action="store_true",
                        help="忽略缓存重新抓取/下载")
        if need_url:
            sp.add_argument("url", help="视频页或分享短链 URL")

    sp = sub.add_parser("meta", help="获取视频元信息(不下载)")
    common(sp)
    sp.set_defaults(fn=cmd_meta)

    sp = sub.add_parser("subs", help="字幕:平台CC优先,无则ASR兜底")
    common(sp)
    sp.add_argument("--lang", default=None, help="字幕语言(如 zh-Hans / zh / en)")
    sp.add_argument("--format", default="srt",
                    choices=["srt", "vtt", "txt", "json"], help="主输出格式")
    sp.add_argument("--no-asr", action="store_true", help="无CC时报错而不做ASR")
    sp.add_argument("--asr-model", default="sensevoice",
                    help="ASR 引擎: sensevoice | whisper-small | whisper-large-v3")
    sp.set_defaults(fn=cmd_subs)

    sp = sub.add_parser("transcribe", help="语音转文字(本地ASR)")
    common(sp)
    sp.add_argument("--lang", default="auto", help="auto/zh/en/ja/ko/yue")
    sp.add_argument("--model", default="sensevoice",
                    help="sensevoice | whisper-small | whisper-large-v3")
    sp.add_argument("--format", default="txt",
                    choices=["txt", "srt", "vtt", "json"])
    sp.set_defaults(fn=cmd_transcribe)

    sp = sub.add_parser("frames", help="拆帧(count/fps/scene/keyframe)")
    common(sp)
    sp.add_argument("--mode", default="count",
                    choices=["count", "fps", "scene", "keyframe"])
    sp.add_argument("--count", type=int, default=12, help="count 模式帧数")
    sp.add_argument("--fps", type=float, default=1.0,
                    help="fps 模式:每秒帧数(0.5=每2秒一帧)")
    sp.add_argument("--threshold", type=float, default=0.3,
                    help="scene 模式切换阈值")
    sp.add_argument("--size", type=int, default=1280, help="最长边像素(0=原尺寸)")
    sp.add_argument("--format", default="jpg", choices=["jpg", "png"])
    sp.add_argument("--max-height", type=int, default=1080,
                    help="下载视频最高清晰度")
    sp.add_argument("--contact-sheet", action="store_true", help="额外输出拼图")
    sp.set_defaults(fn=cmd_frames)

    sp = sub.add_parser("prepare", help="一站式素材包(字幕+拆帧+manifest+context.md)")
    common(sp)
    sp.add_argument("--granularity", default="medium",
                    choices=["coarse", "medium", "fine"])
    sp.add_argument("--frames-mode", default=None,
                    choices=["count", "fps", "scene", "keyframe"])
    sp.add_argument("--frames-count", type=int, default=None)
    sp.add_argument("--frames-fps", type=float, default=None)
    sp.add_argument("--frames-size", type=int, default=None)
    sp.add_argument("--lang", default="auto")
    sp.add_argument("--no-asr", action="store_true")
    sp.add_argument("--asr-model", default="sensevoice")
    sp.set_defaults(fn=cmd_prepare)

    sp = sub.add_parser("cache", help="缓存管理")
    common(sp, need_url=False)
    sp.add_argument("cache_cmd", nargs="?", default=None,
                    choices=["list", "clean", "stats"])
    sp.add_argument("--all", action="store_true", help="clean: 清空全部")
    sp.set_defaults(fn=cmd_cache)

    sp = sub.add_parser("doctor", help="自检依赖/网络/模型")
    common(sp, need_url=False)
    sp.set_defaults(fn=cmd_doctor)

    for spx in sub.choices.values():
        if "out" not in spx._option_string_actions:
            spx.add_argument("--out", default=None,
                             help="输出目录(默认:缓存内 job 目录)")
    return p


def main(argv: list[str] | None = None) -> int:
    # deterministic UTF-8 on Windows pipes/console — the agent contract
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ns = build_parser().parse_args(argv)
    try:
        return ns.fn(ns)
    except VidtoolError as e:
        return emit_error(e, pretty=ns.pretty)
    except KeyboardInterrupt:
        sys.stderr.write('{"ok": false, "error": {"code": "interrupted", '
                         '"message": "用户中断"}}\n')
        return 130
    except Exception as e:  # never break the JSON contract
        return emit_error(
            VidtoolError(f"内部错误: {type(e).__name__}: {e}",
                         hint="这是 bug,可带完整命令重试;运行 `vidtool doctor` "
                              "排查环境;持续失败请反馈。",
                         errcode="internal_error"),
            pretty=ns.pretty)


if __name__ == "__main__":
    raise SystemExit(main())
