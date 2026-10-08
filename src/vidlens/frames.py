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

MIN_ADAPTIVE_FRAMES = 10
DEFAULT_ADAPTIVE_FRAMES = 30
MAX_FRAMES = 75
MAX_AUTO_FRAMES = 100


class ExtractResult(NamedTuple):
    records: list[dict]
    truncated: bool
    total_candidates: int


def _fmt_duration(seconds: float | None) -> str:
    return f"{seconds:.2f}" if seconds is not None else "未知"


def validate_budget(count: int, max_frames: int | None, allow_over_100: bool,
                    *, uses_count: bool) -> None:
    if max_frames is not None and max_frames < 1:
        raise VidlensError("帧预算必须大于 0", errcode="bad_args")
    if max_frames is not None and max_frames > MAX_AUTO_FRAMES and not allow_over_100:
        raise VidlensError(
            "超过 100 帧需要用户明确允许",
            hint="先向用户确认是否需要超过 100 帧;获得允许后,设置 --max-frames "
                 "并同时传入 --allow-over-100-frames。",
            errcode="frame_budget_approval_required")
    if uses_count and count > MAX_AUTO_FRAMES and not allow_over_100:
        raise VidlensError(
            "请求超过 100 帧需要用户明确允许",
            hint="先向用户确认是否需要超过 100 帧;获得允许后,设置 "
                 "--allow-over-100-frames。",
            errcode="frame_budget_approval_required")
    if uses_count and count < 1:
        raise VidlensError("取帧数量必须大于 0", errcode="bad_args")


def effective_limit(mode: str, count: int, max_frames: int | None = None,
                    allow_over_100: bool = False) -> int:
    if max_frames is not None:
        return max_frames
    if mode == "adaptive":
        limit = MAX_AUTO_FRAMES if count >= 75 else MAX_FRAMES
    elif mode == "count":
        limit = max(MAX_FRAMES, min(count, MAX_AUTO_FRAMES))
    else:
        limit = MAX_FRAMES
    if allow_over_100 and count > MAX_AUTO_FRAMES and mode in ("adaptive", "count"):
        limit = max(limit, count)
    return limit


def _finalize(recs: list[dict], max_frames: int = MAX_FRAMES) -> ExtractResult:
    total = len(recs)
    return ExtractResult(records=recs[:max_frames],
                         truncated=total > max_frames,
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


def _frame_record(p: Path, t: float | None, idx: int,
                  reason: str | None = None) -> dict:
    from PIL import Image
    with Image.open(p) as im:
        w, h = im.size
    record = {"file": str(p), "t": round(t, 2) if t is not None else None,
              "index": idx, "width": w, "height": h, "bytes": p.stat().st_size}
    if reason:
        record["selection_reason"] = reason
    return record


def extract(media: str, out_dir: Path, *, mode: str, fps: float = 1.0,
            count: int = 12, threshold: float = 0.3, size: int | None = 1280,
            fmt: str = "jpg", duration: float | None = None,
            max_frames: int | None = None, allow_over_100: bool = False,
            start: float | None = None, end: float | None = None) -> ExtractResult:
    """Extract frames into out_dir; returns ExtractResult(records, truncated,
    total_candidates) so silent capping can never happen."""
    out_dir.mkdir(parents=True, exist_ok=True)
    validate_budget(count, max_frames, allow_over_100,
                    uses_count=mode in ("adaptive", "count"))
    cap = effective_limit(mode, count, max_frames, allow_over_100)
    if (start is not None or end is not None) and mode != "count":
        raise VidlensError("按时间段补帧请使用 --mode count",
                           errcode="bad_args")
    if mode == "count":
        actual_count = min(int(count), cap)
        if (start is None) != (end is None):
            raise VidlensError("按时间段取帧必须同时提供开始与结束时间",
                               errcode="bad_args")
        if start is not None:
            dur = duration or ffutil.probe_duration(media)
            if not dur or start < 0 or end <= start or end > dur:
                raise VidlensError(
                    "帧取样时间范围无效",
                    hint=f"开始和结束时间须满足 0 <= start < end <= {_fmt_duration(dur)} 秒。",
                    errcode="bad_args")
            wanted = actual_count
            stamps = [start + (end - start) * (i + 0.5) / wanted
                      for i in range(wanted)]
            reasons = ["按指定时间段均匀取样"] * wanted
            recs = _extract_timestamps(media, out_dir, stamps, reasons,
                                       size, fmt)
            return ExtractResult(recs, int(count) > cap, int(count))
        dur = duration or ffutil.probe_duration(media)
        if not dur:
            raise VidlensError("无法确定视频时长(count 模式需要)",
                               errcode="no_duration")
        recs = _extract_count(media, out_dir, actual_count, size, fmt, dur, cap)
        return ExtractResult(recs, int(count) > cap, int(count))
    if mode == "fps":
        dur = duration or ffutil.probe_duration(media)
        if not dur:
            raise VidlensError(
                "无法确定视频时长(fps 模式需要)",
                hint="先运行 `vidlens meta <url>` 刷新缓存,再重试。",
                errcode="no_duration")
        candidates = max(1, int(dur * max(fps, 0.01) + 0.5))
        wanted = min(cap, candidates)
        recs = _extract_count(media, out_dir, wanted, size, fmt, dur, cap)
        return ExtractResult(recs, candidates > len(recs), candidates)
    if mode == "adaptive":
        dur = duration or ffutil.probe_duration(media)
        if not dur:
            raise VidlensError(
                "无法确定视频时长(自适应拆帧需要)",
                hint="先运行 `vidlens meta <url>` 刷新缓存,再重试。",
                errcode="no_duration")
        scene_times = _detect_scene_times(media, size=320, threshold=0.20)
        target = _adaptive_budget(dur, len(scene_times), count, cap,
                                  explicit_cap=(max_frames is not None or
                                                (allow_over_100 and
                                                 count > MAX_AUTO_FRAMES)))
        stamps, reasons = _adaptive_stamps(dur, scene_times, target)
        recs = _extract_timestamps(media, out_dir, stamps, reasons, size, fmt)
        if not recs:
            raise VidlensError("拆帧失败: 一帧也没有抽出",
                               hint=f"ffmpeg stderr 尾部: {_last_err()}",
                               errcode="ffmpeg_failed")
        return ExtractResult(records=recs, truncated=len(recs) < target,
                             total_candidates=target)
    if mode == "scene":
        tried = []
        for th in (threshold, threshold * 0.5, 0.1, 0.05, 0.02):
            th = round(th, 4)
            if th in tried:
                continue
            tried.append(th)
            _clear_frames(out_dir, fmt)
            recs = _extract_stream(media, out_dir, mode, threshold=th,
                                   size=size, fmt=fmt)
            if recs:
                selected = _spread_records(recs, cap)
                return ExtractResult(selected, len(recs) > len(selected),
                                     len(recs))
        raise VidlensError(
            f"scene 模式没有检出镜头切换 (试过阈值 {tried})",
            hint="该视频可能没有明显镜头切换;改用 --mode count 或 --mode fps。",
            errcode="no_frames")
    if mode == "keyframe":
        _clear_frames(out_dir, fmt)
        recs = _extract_stream(media, out_dir, mode, size=size, fmt=fmt)
        if not recs:
            raise VidlensError("没有检出视频关键帧", errcode="no_frames")
        selected = _spread_records(recs, cap)
        for record in selected:
            record["selection_reason"] = "视频关键帧"
        return ExtractResult(records=selected,
                             truncated=len(recs) > len(selected),
                             total_candidates=len(recs))
    raise VidlensError(f"未知拆帧模式: {mode}",
                       hint="可选: adaptive | count | fps | scene | keyframe。",
                       errcode="bad_args")


def _ext_args(fmt: str) -> list[str]:
    if fmt == "jpg":
        return ["-q:v", "2"]
    if fmt == "png":
        return ["-compression_level", "3"]
    return []


# ------------------------------------------------------------ count mode ----

def _extract_count(media: str, out_dir: Path, count: int, size: int | None,
                   fmt: str, duration: float | None,
                   max_frames: int = MAX_FRAMES) -> list[dict]:
    count = max(1, min(int(count), max_frames))
    dur = duration or ffutil.probe_duration(media)
    if not dur:
        raise VidlensError(
            "无法确定视频时长(count 模式需要)",
            hint="元数据缺失且 ffmpeg 探测失败;先运行 `vidlens meta <url>` 刷新缓存。",
            errcode="no_duration")
    # Midpoint sampling avoids intro/outro black frames and spans the full clip.
    stamps = [dur * (i + 0.5) / count for i in range(count)]
    recs = _extract_timestamps(media, out_dir, stamps,
                               ["全片均匀覆盖"] * len(stamps), size, fmt)
    if not recs:
        raise VidlensError(
            "拆帧失败: 一帧也没有抽出",
            hint=f"ffmpeg 最后输出: {_last_err()};运行 `vidlens doctor` 检查。",
            errcode="ffmpeg_failed")
    return recs


def _detect_times(media: str, vf: str) -> list[float]:
    args = ["-i", media, "-vf", vf, "-an", "-f", "null", "-"]
    r = _run(args, timeout=7200)
    global _ERR_TAIL
    _ERR_TAIL = r.stderr or ""
    if r.returncode != 0:
        raise VidlensError(
            "扫描视频画面失败 (ffmpeg)",
            hint=f"ffmpeg stderr 尾部: {_last_err()}",
            errcode="ffmpeg_failed")
    return sorted(set(_parse_pts_times(r.stderr)))


def _detect_scene_times(media: str, *, size: int, threshold: float) -> list[float]:
    scaled = _scale_filter(size)
    vf = f"{scaled}," if scaled else ""
    vf += f"select='gt(scene,{threshold:.3f})',showinfo"
    return _detect_times(media, vf)


def _detect_keyframe_times(media: str) -> list[float]:
    return _detect_times(media, "select='eq(pict_type,I)',showinfo")


def _adaptive_budget(duration: float, scene_count: int, base: int,
                     hard_cap: int, *, explicit_cap: bool) -> int:
    """Estimate image budget from full-video cut density, without model APIs."""
    cuts_per_minute = scene_count / max(duration / 60.0, 1.0 / 60.0)
    scale = 5.0 if base >= 75 else 3.33
    if explicit_cap:
        ceiling = hard_cap
    else:
        ceiling = min(hard_cap, MAX_AUTO_FRAMES if base >= 75 else MAX_FRAMES)
    baseline_density = 6.0
    if cuts_per_minute <= baseline_density:
        estimate = MIN_ADAPTIVE_FRAMES + round(
            (base - MIN_ADAPTIVE_FRAMES) * cuts_per_minute / baseline_density)
    else:
        estimate = base + round((cuts_per_minute - baseline_density) * scale)
    return max(MIN_ADAPTIVE_FRAMES, min(ceiling, estimate))


def _adaptive_stamps(duration: float, scene_times: list[float],
                     count: int) -> tuple[list[float], list[str]]:
    """Cover the whole duration, preferring one scene change per time bin."""
    stamps, reasons = [], []
    width = duration / count
    cursor = 0
    for i in range(count):
        start, end = i * width, (i + 1) * width
        center = (start + end) / 2
        while cursor < len(scene_times) and scene_times[cursor] < start:
            cursor += 1
        j = cursor
        candidates = []
        while j < len(scene_times) and scene_times[j] < end:
            candidates.append(scene_times[j])
            j += 1
        if candidates:
            stamps.append(min(candidates, key=lambda t: abs(t - center)))
            reasons.append("镜头变化附近")
        else:
            stamps.append(center)
            reasons.append("全片均匀覆盖")
    return stamps, reasons


def _spread_times(times: list[float], count: int) -> list[float]:
    if len(times) <= count:
        return times
    if count <= 1:
        return [times[len(times) // 2]]
    indexes = [round(i * (len(times) - 1) / (count - 1))
               for i in range(count)]
    return [times[i] for i in indexes]


def _spread_records(records: list[dict], count: int) -> list[dict]:
    if len(records) <= count:
        selected = records
    elif count <= 1:
        selected = [records[len(records) // 2]]
    else:
        indexes = [round(i * (len(records) - 1) / (count - 1))
                   for i in range(count)]
        selected = [records[i] for i in indexes]
    chosen = {record.get("file") for record in selected}
    for record in records:
        if record.get("file") not in chosen:
            Path(record["file"]).unlink(missing_ok=True)
    for index, record in enumerate(selected):
        record["index"] = index
        record["selection_reason"] = "镜头变化"
    return selected


def _extract_timestamps(media: str, out_dir: Path, stamps: list[float],
                        reasons: list[str], size: int | None,
                        fmt: str) -> list[dict]:
    if not stamps:
        return []
    _clear_frames(out_dir, fmt)
    # Select exactly the first decoded frame at or after each target timestamp.
    terms = [f"isnan(prev_selected_t)*gte(t,{stamps[0]:.5f})"]
    terms.extend(f"lt(prev_selected_t,{t:.5f})*gte(t,{t:.5f})"
                 for t in stamps[1:])
    vf = f"select='{'+'.join(terms)}'"
    scaled = _scale_filter(size)
    if scaled:
        vf += f",{scaled}"
    vf += ",showinfo"
    out_pattern = str(out_dir / f"frame_%04d.{fmt}")
    args = ["-i", media, "-vf", vf, "-vsync", "vfr", "-an"]
    args += _ext_args(fmt) + [out_pattern]
    r = _run(args, timeout=7200)
    global _ERR_TAIL
    _ERR_TAIL = r.stderr or ""
    if r.returncode != 0:
        raise VidlensError(
            "拆帧失败 (ffmpeg)", hint=f"ffmpeg stderr 尾部: {_last_err()}",
            errcode="ffmpeg_failed")
    times = _parse_pts_times(r.stderr)
    files = sorted(out_dir.glob(f"frame_*.{fmt}"),
                   key=lambda p: _idx_from_name(p.name))
    recs = []
    for i, source in enumerate(files):
        t = times[i] if i < len(times) else stamps[min(i, len(stamps) - 1)]
        dest = out_dir / f"frame_{i:04d}_{t:.2f}s.{fmt}"
        source.replace(dest)
        reason = reasons[min(i, len(reasons) - 1)] if reasons else None
        recs.append(_frame_record(dest, t, i, reason))
    return recs


def _clear_frames(out_dir: Path, fmt: str) -> None:
    for old in out_dir.glob(f"frame_*.{fmt}"):
        old.unlink(missing_ok=True)


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
