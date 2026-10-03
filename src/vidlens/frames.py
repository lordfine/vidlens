"""Frame extraction: fps / count / scene / keyframe modes + contact sheet.

All frames are timestamped filenames (frame_0007_83.40s.jpg). extract()
returns an ExtractResult so capping at MAX_FRAMES is always visible.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import NamedTuple

from . import ffutil
from .agentio import VidlensError

MAX_FRAMES = 60


class ExtractResult(NamedTuple):
    records: list[dict]
    truncated: bool
    total_candidates: int


def _finalize(recs: list[dict]) -> ExtractResult:
    total = len(recs)
    return ExtractResult(records=recs[:MAX_FRAMES],
                         truncated=total > MAX_FRAMES,
                         total_candidates=total)


def _scale_filter(size: int | None) -> str:
    if not size:
        return ""
    return (f"scale='if(gt(iw,ih),min({size},iw),-2)':"
            f"'if(gt(iw,ih),-2,min({size},ih))'")


def _parse_pts_times(stderr: str) -> list[float]:
    return [float(m.group(1)) for m in re.finditer(
        r"pts_time:([0-9]+\.?[0-9]*)", stderr)]


def _run(args: list[str], timeout: float = 1800) -> subprocess.CompletedProcess:
    cmd = [ffutil.ffmpeg_path(), "-hide_banner", "-nostdin", "-y", *args]
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def _frame_record(p: Path, t: float | None, idx: int) -> dict:
    from PIL import Image
    with Image.open(p) as im:
        w, h = im.size
    return {"file": str(p), "t": round(t, 2) if t is not None else None,
            "index": idx, "width": w, "height": h, "bytes": p.stat().st_size}


def extract(media: str, out_dir: Path, *, mode: str, fps: float = 1.0,
            count: int = 12, threshold: float = 0.3, size: int | None = 1280,
            fmt: str = "jpg", duration: float | None = None) -> ExtractResult:
    """Extract frames into out_dir; returns ExtractResult(records, truncated,
    total_candidates) so silent capping can never happen."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob(f"frame_*.{fmt}"):
        old.unlink(missing_ok=True)

    if mode == "count":
        return _finalize(_extract_count(media, out_dir, count, size, fmt,
                                        duration))
    if mode == "fps":
        return _finalize(_extract_stream(media, out_dir, mode, fps=fps,
                                         size=size, fmt=fmt, duration=duration))
    if mode == "scene":
        # scene scores vary wildly with compression (douyin re-encodes score
        # low); auto-lower the threshold when nothing is detected
        tried = []
        for th in (threshold, threshold * 0.5, 0.1, 0.05, 0.02):
            th = round(th, 4)
            if any(abs(th - t) < 1e-4 for t in tried):
                continue
            tried.append(th)
            recs = _extract_stream(media, out_dir, mode, threshold=th,
                                   size=size, fmt=fmt)
            if recs:
                return _finalize(recs)
            for old in out_dir.glob(f"frame_*.{fmt}"):
                old.unlink(missing_ok=True)
        raise VidlensError(
            f"scene 模式没有检出镜头切换 (试过阈值 {tried})",
            hint="该视频可能没有明显镜头切换;改用 --mode count 或 --mode fps。",
            errcode="no_frames")
    if mode == "keyframe":
        return _finalize(_extract_stream(media, out_dir, mode, size=size,
                                         fmt=fmt))
    raise VidlensError(f"未知拆帧模式: {mode}",
                       hint="可选: count | fps | scene | keyframe。",
                       errcode="bad_args")


def _ext_args(fmt: str) -> list[str]:
    if fmt == "jpg":
        return ["-q:v", "2"]
    if fmt == "png":
        return ["-compression_level", "3"]
    return []


# ------------------------------------------------------------ count mode ----

def _extract_count(media: str, out_dir: Path, count: int, size: int | None,
                   fmt: str, duration: float | None) -> list[dict]:
    count = max(1, min(int(count), MAX_FRAMES))
    dur = duration or ffutil.probe_duration(media)
    if not dur:
        raise VidlensError(
            "无法确定视频时长(count 模式需要)",
            hint="元数据缺失且 ffmpeg 探测失败;先运行 `vidlens meta <url>` 刷新缓存。",
            errcode="no_duration")
    # midpoint sampling: avoids intro/outro black frames
    stamps = [dur * (i + 0.5) / count for i in range(count)]
    recs = []
    for i, t in enumerate(stamps):
        out = out_dir / f"frame_{i:04d}_{t:.2f}s.{fmt}"
        vf = _scale_filter(size)
        args = ["-ss", f"{t:.3f}", "-i", media, "-frames:v", "1"]
        if vf:
            args += ["-vf", vf]
        args += _ext_args(fmt) + [str(out)]
        r = _run(args, timeout=300)
        if r.returncode == 0 and out.is_file() and out.stat().st_size > 0:
            recs.append(_frame_record(out, t, i))
    if not recs:
        raise VidlensError(
            "拆帧失败: 一帧也没有抽出",
            hint=f"ffmpeg 最后输出: {_last_err()};运行 `vidlens doctor` 检查。",
            errcode="ffmpeg_failed")
    return recs


_ERR_TAIL = ""


def _last_err() -> str:
    return _ERR_TAIL[-300:]


# ------------------------------------------------- stream modes (fps etc) ----

def _extract_stream(media: str, out_dir: Path, mode: str, *,
                    fps: float = 1.0, threshold: float = 0.3,
                    size: int | None, fmt: str,
                    duration: float | None = None) -> list[dict]:
    interval = max(1.0 / max(fps, 0.01), 0.04)
    if mode == "fps":
        cap = MAX_FRAMES * interval  # hard cap frame count
        vf = f"fps=1/{interval:.4f}"
    elif mode == "scene":
        vf = f"select='gt(scene,{threshold:.3f})'"
    else:  # keyframe
        vf = "select='eq(pict_type,I)'"

    s = _scale_filter(size)
    vf_full = vf + (f",{s}" if s else "")
    out_pattern = str(out_dir / f"frame_%04d.{fmt}")
    args = ["-i", media, "-vf", vf_full + ",showinfo", "-vsync", "vfr"]
    if mode == "fps":
        args = ["-t", f"{cap:.3f}", *args]
    args += _ext_args(fmt) + [out_pattern]
    r = _run(args)
    global _ERR_TAIL
    _ERR_TAIL = r.stderr or ""
    # ffmpeg 7.x image2 muxer exits with EINVAL when select filtered out
    # everything — that means "0 frames", not a real failure
    empty_output = "Nothing was written into output file" in r.stderr
    if r.returncode != 0 and not empty_output:
        raise VidlensError(
            f"拆帧失败 (ffmpeg, mode={mode})",
            hint=f"ffmpeg stderr 尾部: {_last_err()}", errcode="ffmpeg_failed")

    times = _parse_pts_times(r.stderr)
    files = sorted(out_dir.glob(f"frame_*.{fmt}"),
                   key=lambda p: _idx_from_name(p.name))
    recs = []
    for i, f in enumerate(files):
        t = times[i] if i < len(times) else i * interval
        recs.append(_frame_record(f, t, i))
    if not recs:
        # scene mode may legitimately produce 0 frames at a given threshold;
        # caller (extract) retries with lower thresholds
        if mode == "scene":
            return []
        raise VidlensError("拆帧失败: 一帧也没有抽出",
                           hint=f"ffmpeg stderr 尾部: {_last_err()}",
                           errcode="ffmpeg_failed")
    return recs  # full list; extract() caps via _finalize with a visible flag


def _idx_from_name(name: str) -> int:
    m = re.match(r"frame_(\d+)", name)
    return int(m.group(1)) if m else 0


# ---------------------------------------------------------- contact sheet ----

def contact_sheet(records: list[dict], out_path: Path, *,
                  thumb_w: int = 320, cols: int | None = None) -> str:
    """Grid montage of extracted frames (ordered, timestamps in manifest)."""
    from PIL import Image, ImageDraw

    if not records:
        raise VidlensError("没有帧可用于拼图", hint="先成功拆帧再生成 contact sheet。",
                           errcode="no_frames")
    n = len(records)
    cols = cols or max(1, int(n ** 0.5 + 0.999))
    rows = (n + cols - 1) // cols
    label_h = 26
    thumbs = []
    for rec in records:
        with Image.open(rec["file"]) as im:
            im = im.convert("RGB")
            h = int(im.height * thumb_w / im.width) or 1
            thumbs.append((im.resize((thumb_w, h)), rec.get("t")))
    cell_h = max(t.height for t, _ in thumbs) + label_h
    sheet = Image.new("RGB", (cols * thumb_w, rows * cell_h), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    for i, (im, t) in enumerate(thumbs):
        x, y = (i % cols) * thumb_w, (i // cols) * cell_h
        sheet.paste(im, (x, y))
        label = f"#{i:02d}  {t:.1f}s" if t is not None else f"#{i:02d}"
        draw.text((x + 4, y + im.height + 4), label, fill=(230, 230, 230))
    sheet.save(out_path, quality=85)
    return str(out_path)
