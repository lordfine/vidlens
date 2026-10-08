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
        "frames": {"mode": "adaptive", "count": 10, "size": 960},
        "contact": True,
        "sub_formats": ("txt", "srt"), "max_height": 720,
    },
    "medium": {
        "frames": {"mode": "adaptive", "count": 30, "size": 1280},
        "contact": True,
        "sub_formats": ("srt", "txt", "json"), "max_height": 1080,
    },
    "fine": {
        "frames": {"mode": "adaptive", "count": 75, "size": 1280},
        "contact": False,
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
          glossary: dict[str, str] | None = None,
          max_frames: int | None = None,
          allow_over_100_frames: bool = False) -> dict:
    g = GRANULARITY[granularity]
    jdir = out_dir or cache_mod.job_dir(meta["platform"], meta["video_id"],
                                        "prepare")
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
    # Keep the original audio available to the calling agent even when CC exists.
    audio = mod.download(target, meta, cookiefile, "audio", 1080, fresh)
    if not segs and not no_asr:
        tr = get_transcript_cached(meta["platform"], meta["video_id"],
                                   audio["path"],
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
        duration=meta.get("duration"), max_frames=max_frames,
        allow_over_100=allow_over_100_frames)
    recs = frame_result.records
    scene_recs = []
    scene_truncated = False
    manifest["frames"] = {"params": fparams, "files": recs,
                          "truncated": frame_result.truncated,
                          "total_candidates": frame_result.total_candidates,
                          "scene_files": scene_recs,
                          "scene_truncated": scene_truncated,
                          "budget": {
                              "minimum": frames_mod.MIN_ADAPTIVE_FRAMES,
                              "baseline": fparams.get("count", 30),
                              "normal_max": frames_mod.MAX_FRAMES,
                              "automatic_max": frames_mod.MAX_AUTO_FRAMES,
                              "limit": frames_mod.effective_limit(
                                  fparams["mode"], fparams.get("count", 30),
                                  max_frames, allow_over_100_frames),
                              "selected": len(recs),
                              "target": frame_result.total_candidates,
                              "truncated": frame_result.truncated,
                          }}
    cs_path = None
    if g["contact"] and recs:
        cs = jdir / "contact_sheet.jpg"
        cs_path = frames_mod.contact_sheet(recs, cs)
        manifest["contact_sheet"] = cs_path
    manifest["files"]["video_local"] = video["path"]
    manifest["files"]["audio_local"] = audio["path"]
    manifest["media"] = {
        # Preserve the original flat fields for existing consumers.
        "source_level": video["source_level"],
        "retried": video["retried"],
        "video": {"source_level": video["source_level"],
                  "retried": video["retried"]},
        "audio": {"source_level": audio["source_level"],
                  "retried": audio["retried"]},
        "cache_lifetime": "有效到用户清理对应缓存",
    }
    manifest["files"]["frames_dir"] = str(jdir / "frames")

    timeline = _build_timeline(segs, recs, sub_source, manifest["files"],
                               video["path"], audio["path"],
                               meta.get("duration"))
    timeline_path = jdir / "evidence-timeline.json"
    timeline_path.write_text(json.dumps(timeline, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    manifest["timeline"] = {"timebase": "video_seconds",
                            "events": len(timeline["events"]),
                            "file": str(timeline_path)}
    manifest["files"]["evidence_timeline"] = str(timeline_path)

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


def _build_timeline(segs: list[dict], recs: list[dict], source: str | None,
                    files: dict, video_path: str, audio_path: str,
                    duration: float | None) -> dict:
    events = []
    text_path = files.get("json") or files.get("srt")
    for index, seg in enumerate(segs):
        events.append({
            "start": round(float(seg.get("start", 0)), 3),
            "end": round(float(seg.get("end", 0)), 3),
            "kind": "caption" if source == "cc" else "speech",
            "source": source,
            "text": seg.get("text", ""),
            "reference": text_path,
            "segment_index": index,
        })
    for rec in recs:
        timestamp = float(rec.get("t") or 0)
        events.append({
            "start": timestamp,
            "end": timestamp,
            "kind": "frame",
            "source": "video",
            "reference": rec["file"],
            "selection_reason": rec.get("selection_reason"),
        })
    events.sort(key=lambda event: (event["start"],
                                  0 if event["kind"] != "frame" else 1,
                                  event.get("end", 0)))
    return {
        "version": 1,
        "timebase": "video_seconds",
        "duration": duration,
        "assets": {"video": video_path, "audio": audio_path},
        "events": events,
    }


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
        "1. 先读 manifest 中的 `timeline.file`,按时间对齐语音/字幕与帧图。",
        "2. 原视频和原音频位于 manifest 的 `files.video_local` / `files.audio_local`;"
        "路径在用户清理缓存前有效。",
        "3. 帧图为全片自适应抽样;需要查看局部细节时,调用 `vidlens frames` "
        "并用 `--start` / `--end` 按视频秒数补帧。",
        "4. 画面含义、画面文字与音乐/音效由你读取原媒体后分析;"
        "vidlens 只提供带时间戳证据,综合结论由你完成。",
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
