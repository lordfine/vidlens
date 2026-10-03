"""`vidlens prepare` — one-stop context bundle: meta + subs/ASR + frames.

The tool never summarizes. It prepares artifacts + manifest.json + context.md;
the calling agent (harness) does the AI part with its multimodal models.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import cache as cache_mod
from . import frames as frames_mod
from .agentio import VidlensError
from .asr import get_transcript_cached
from .platforms import media as media_mod

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
          asr_lang: str = "auto",
          glossary: dict[str, str] | None = None) -> dict:
    g = GRANULARITY[granularity]
    vdir = cache_mod.video_dir(meta["platform"], meta["video_id"])
    jdir = out_dir or (vdir / "jobs" / f"prepare-{time.strftime('%Y%m%d-%H%M%S')}")
    jdir = Path(jdir)
    jdir.mkdir(parents=True, exist_ok=True)
    (jdir / "frames").mkdir(exist_ok=True)

    manifest = {
        "tool": "vidlens",
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
        except VidlensError:
            track, segs = None, []
    if segs:
        sub_source = "cc"
        sub_files = media_mod.save_subtitle(segs, jdir, base="subtitle")
    elif not no_asr:
        audio = mod.download(target, meta, cookiefile, "audio", 1080,
                             fresh)["path"]
        tr = get_transcript_cached(meta["platform"], meta["video_id"], audio,
                                   lang=asr_lang or "auto", model=asr_model,
                                   fresh=fresh, glossary=glossary)
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
    frame_result = frames_mod.extract(
        video["path"], jdir / "frames", mode=fparams["mode"],
        fps=fparams.get("fps", 1.0), count=fparams.get("count", 12),
        threshold=fparams.get("threshold", 0.3),
        size=fparams.get("size"), fmt=fparams.get("fmt", "jpg"),
        duration=meta.get("duration"))
    recs = frame_result.records
    scene_recs = []
    scene_truncated = False
    if g["scene_pass"]:
        try:
            scene_result = frames_mod.extract(
                video["path"], jdir / "frames_scene", mode="scene",
                size=fparams.get("size"), duration=meta.get("duration"))
            scene_recs = scene_result.records
            scene_truncated = scene_result.truncated
        except VidlensError:
            scene_recs = []
    manifest["frames"] = {"params": fparams, "files": recs,
                          "truncated": frame_result.truncated,
                          "total_candidates": frame_result.total_candidates,
                          "scene_files": scene_recs,
                          "scene_truncated": scene_truncated}
    cs_path = None
    if g["contact"] and recs:
        cs = jdir / "contact_sheet.jpg"
        cs_path = frames_mod.contact_sheet(recs, cs)
        manifest["contact_sheet"] = cs_path
    manifest["files"]["video_local"] = video["path"]
    manifest["media"] = {"source_level": video["source_level"],
                         "retried": video["retried"]}
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


def _frame_index(recs: list[dict], per_line: int = 4) -> str:
    """Compact frame index: `#00 0:07  #01 0:21 ...` — file names are
    deterministic (frame_<idx>_<sec>s.jpg); absolute paths live in manifest."""
    items = []
    for r in recs:
        t = r.get("t")
        items.append(f"#{r['index']:02d} {_fmt_dur(t) if t is not None else '?'}")
    rows = [" ".join(items[i:i + per_line])
            for i in range(0, len(items), per_line)]
    return "\n".join(rows)


def _context_md(manifest: dict, segs: list[dict], recs: list[dict],
                scene_recs: list[dict], cs_path: str | None) -> str:
    from .textflow import fmt_stamp, to_paragraphs
    v = manifest["video"]
    paras = to_paragraphs(segs) if segs else []
    lines = [f"# 视频素材包: {v.get('title') or v.get('video_id')}", ""]
    lines += [
        f"- 平台 {v.get('platform')} | 作者 {v.get('uploader') or '?'} | "
        f"时长 {_fmt_dur(v.get('duration'))} | "
        f"发布 {v.get('upload_date') or '?'}",
        f"- 链接: {v.get('webpage_url')}",
        f"- 颗粒度 {manifest['granularity']} | "
        f"文字来源 {manifest['subtitle']['source'] or '无'} | "
        f"{manifest['subtitle']['segments']} 句 / {len(paras)} 段 | "
        f"生成 {manifest['generated_at']}",
        "",
    ]

    lines += [
        "## 怎么用这份素材(agent)",
        "1. **先看拼图**(如有)把握整体画面与场景节奏。",
        "2. **读下面的「语音内容」段落**——`[分:秒]` 是段落起点锚点,按段阅读;",
        "   需要精确到句的时间轴用 `transcript.srt` / `.json`。",
        "3. **看某时刻的画面**:按「关键帧索引」的时间就近取帧,图片文件在 "
        "`frames/` 目录(manifest 有绝对路径),直接按图片读取。",
        "4. **总结/分析是你的工作**,本工具只负责素材:字幕定位内容,帧补充画面,"
        "两者时间对齐即可描述\"这时画面上是什么、说了什么\"。",
        "",
    ]

    if v.get("description"):
        lines += ["## 简介", str(v["description"])[:500], ""]
    if cs_path:
        lines += ["## 整片总览(拼图)", f"![contact sheet]({_md_path(cs_path)})",
                  ""]
    if recs:
        lines += ["## 关键帧索引", "",
                  f"目录 `{_md_path(manifest['files']['frames_dir'])}` "
                  f"(共 {len(recs)} 帧,文件名 `frame_序号_秒.jpg`)", "",
                  _frame_index(recs), ""]
    if scene_recs:
        lines += ["## 镜头切换帧", "",
                  f"共 {len(scene_recs)} 帧,目录 `frames_scene/`,"
                  f"绝对路径见 manifest.frames.scene_files。", ""]
    if paras:
        lines += ["## 语音内容(段落全文)", ""]
        for p in paras:
            lines.append(f"[{fmt_stamp(p['start'])}] {p['text']}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
