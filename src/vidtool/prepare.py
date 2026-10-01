"""`vidtool prepare` — one-stop context bundle: meta + subs/ASR + frames.

The tool never summarizes. It prepares artifacts + manifest.json + context.md;
the calling agent (harness) does the AI part with its multimodal models.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import cache as cache_mod
from . import frames as frames_mod
from .platforms import media as media_mod
from .agentio import VidtoolError
from .asr import get_transcript_cached

GRANULARITY = {
    "coarse": {
        "frames": {"mode": "count", "count": 8, "size": 960},
        "scene_pass": False, "contact": True,
        "sub_formats": ("txt", "srt"), "max_height": 720,
    },
    "medium": {
        "frames": {"mode": "count", "count": 16, "size": 1280},
        "scene_pass": False, "contact": True,
        "sub_formats": ("srt", "txt", "json"), "max_height": 1080,
    },
    "fine": {
        "frames": {"mode": "fps", "fps": 0.5, "size": 1280},
        "scene_pass": True, "contact": False,
        "sub_formats": ("srt", "json"), "max_height": 1080,
    },
}


def _fmt_dur(sec) -> str:
    if not sec:
        return "?"
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def build(target, mod, meta, *, granularity: str = "medium",
          frames_overrides: dict | None = None, no_asr: bool = False,
          cookiefile: str | None = None, out_dir: Path | None = None,
          fresh: bool = False, asr_model: str = "sensevoice",
          asr_lang: str = "auto") -> dict:
    g = GRANULARITY[granularity]
    vdir = cache_mod.video_dir(meta["platform"], meta["video_id"])
    jdir = out_dir or (vdir / "jobs" / f"prepare-{time.strftime('%Y%m%d-%H%M%S')}")
    jdir = Path(jdir)
    jdir.mkdir(parents=True, exist_ok=True)
    (jdir / "frames").mkdir(exist_ok=True)

    manifest = {
        "tool": "vidtool",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "granularity": granularity,
        "video": {k: meta.get(k) for k in (
            "platform", "video_id", "webpage_url", "title", "uploader",
            "duration", "description", "upload_date", "view_count",
            "like_count")},
        "subtitle": None,
        "frames": None,
        "contact_sheet": None,
        "files": {},
    }

    # ---- 1. subtitles (CC first, ASR fallback) ----
    sub_files = {}
    sub_source = None
    track = None
    segs: list[dict] = []
    if hasattr(mod, "fetch_subtitles"):
        try:
            track, segs = mod.fetch_subtitles(target, meta, cookiefile)
        except VidtoolError:
            track, segs = None, []
    if segs:
        sub_source = "cc"
        sub_files = media_mod.save_subtitle(segs, jdir, base="subtitle")
    elif not no_asr:
        audio = mod.download(target, meta, cookiefile, "audio", 1080, fresh)
        tr = get_transcript_cached(meta["platform"], meta["video_id"], audio,
                                   lang=asr_lang or "auto", model=asr_model,
                                   fresh=fresh)
        segs = tr["segments"]
        sub_source = "asr"
        sub_files = media_mod.save_subtitle(segs, jdir, base="transcript")
        (jdir / "asr.json").write_text(
            json.dumps(tr, ensure_ascii=False, indent=1), encoding="utf-8")
        sub_files["asr_detail"] = str(jdir / "asr.json")
    manifest["subtitle"] = {
        "source": sub_source,
        "track": track,
        "segments": len(segs),
        "files": sub_files,
    }
    manifest["files"].update(sub_files)

    # ---- 2. frames ----
    fparams = dict(g["frames"])
    if frames_overrides:
        fparams.update({k: v for k, v in frames_overrides.items()
                        if v is not None})
    video = mod.download(target, meta, cookiefile, "video",
                         g["max_height"], fresh)
    recs = frames_mod.extract(
        video, jdir / "frames", mode=fparams["mode"],
        fps=fparams.get("fps", 1.0), count=fparams.get("count", 12),
        threshold=fparams.get("threshold", 0.3),
        size=fparams.get("size"), fmt=fparams.get("fmt", "jpg"),
        duration=meta.get("duration"))
    scene_recs = []
    if g["scene_pass"]:
        try:
            scene_recs = frames_mod.extract(
                video, jdir / "frames_scene", mode="scene", size=fparams.get("size"),
                duration=meta.get("duration"))
        except VidtoolError:
            scene_recs = []
    manifest["frames"] = {"params": fparams, "files": recs,
                          "scene_files": scene_recs}
    cs_path = None
    if g["contact"] and recs:
        cs = jdir / "contact_sheet.jpg"
        cs_path = frames_mod.contact_sheet(recs, cs)
        manifest["contact_sheet"] = cs_path
    manifest["files"]["video_local"] = str(video)
    manifest["files"]["frames_dir"] = str(jdir / "frames")

    # ---- 3. context.md ----
    cmd = _context_md(manifest, segs, recs, scene_recs, cs_path)
    ctx_path = jdir / "context.md"
    ctx_path.write_text(cmd, encoding="utf-8")
    manifest["files"]["context_md"] = str(ctx_path)

    mpath = jdir / "manifest.json"
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    manifest["files"]["manifest"] = str(mpath)
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    return manifest


def _md_path(p) -> str:
    """Markdown-safe absolute path (forward slashes)."""
    return str(p).replace("\\", "/")


def _context_md(manifest: dict, segs: list[dict], recs: list[dict],
                scene_recs: list[dict], cs_path: str | None) -> str:
    v = manifest["video"]
    lines = [f"# 视频素材包: {v.get('title') or v.get('video_id')}", ""]
    lines += [
        f"- 平台: {v.get('platform')} | 作者: {v.get('uploader') or '?'} | "
        f"时长: {_fmt_dur(v.get('duration'))}",
        f"- 链接: {v.get('webpage_url')}",
        f"- 颗粒度: {manifest['granularity']}",
        f"- 生成时间: {manifest['generated_at']}",
        f"- 字幕来源: {manifest['subtitle']['source'] or '无'} "
        f"({manifest['subtitle']['segments']} 段)",
        "",
    ]
    if v.get("description"):
        lines += ["## 简介", str(v["description"])[:800], ""]
    if cs_path:
        lines += ["## 整片总览(拼图)", f"![contact sheet]({_md_path(cs_path)})", ""]
    if recs:
        lines += ["## 关键帧清单", "",
                  "| # | 时间点 | 文件 |", "|---|--------|------|"]
        for r in recs:
            t = r.get("t")
            lines.append(f"| {r['index']:02d} | "
                         f"{_fmt_dur(t) if t is not None else '?'} | "
                         f"`{_md_path(r['file'])}` |")
        lines.append("")
    if scene_recs:
        lines += ["## 镜头切换帧(scene)",
                  f"共 {len(scene_recs)} 帧,见 manifest.frames.scene_files。", ""]
    if segs:
        lines += ["## 字幕/语音全文(带时间轴)", ""]
        for s in segs:
            lines.append(f"[{_fmt_dur(s['start'])} --> {_fmt_dur(s['end'])}] "
                         f"{s['text']}")
        lines.append("")

    lines += [
        "---",
        "## 给 Agent 的使用指引",
        "1. 先看拼图(若有)把握整体,再按需读取关键帧图片文件(多模态)。",
        "2. 用字幕时间轴定位内容;把时间点和帧对齐可以得到画面-台词的对应关系。",
        "3. 综合以上素材后,由你(agent)完成内容总结/分析 —— 本工具只提供素材。",
        "4. 所有文件的绝对路径见 manifest.json 的 files 字段。",
    ]
    return "\n".join(lines) + "\n"
