"""Local ASR: SenseVoice (sherpa-onnx) default, faster-whisper optional.

get_transcript(media_path) -> {
  engine, model, lang, duration,
  segments: [{start, end, text}],   # seconds, sentence-ish granularity
}
"""

from __future__ import annotations

from pathlib import Path

from .. import cache as cache_mod
from .. import ffutil
from ..agentio import DependencyError, VidtoolError


def get_transcript(media_path: str, *, lang: str = "auto",
                    model: str = "sensevoice") -> dict:
    if model.startswith("whisper"):
        from . import whisper
        return whisper.transcribe(media_path, lang=lang, model=model)
    from . import sensevoice
    return sensevoice.transcribe(media_path, lang=lang)


def get_transcript_cached(platform: str, video_id: str, media_path: str, *,
                          lang: str = "auto", model: str = "sensevoice",
                          fresh: bool = False) -> dict:
    """ASR is expensive — cache transcripts per (video, engine, lang)."""
    import json as _json
    from pathlib import Path as _Path
    cf = cache_mod.video_dir(platform, video_id) / (
        f"transcript-{model}-{(lang or 'auto')}.json")
    if cf.is_file() and not fresh:
        try:
            return _json.loads(cf.read_text(encoding="utf-8"))
        except Exception:
            pass
    tr = get_transcript(media_path, lang=lang, model=model)
    try:
        cf.write_text(_json.dumps(tr, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return tr


def prepare_wav(media_path: str, *, fresh: bool = False) -> tuple[str, float]:
    """Transcode any media to 16k mono wav next to its cache dir."""
    src = Path(media_path)
    wav = src.with_suffix(".asr16k.wav")
    if wav.is_file() and wav.stat().st_size > 44 and not fresh:
        dur = ffutil.probe_duration(str(wav))
        return str(wav), dur or 0.0
    ffutil.make_wav(media_path, str(wav))
    dur = ffutil.probe_duration(str(wav))
    return str(wav), dur or 0.0


def split_wav(wav: str, segment_secs: float = 30.0) -> list[tuple[str, float]]:
    """Split long wav into chunks; returns [(path, offset_seconds)]."""
    dur = ffutil.probe_duration(wav) or 0.0
    if dur <= segment_secs + 5:
        return [(wav, 0.0)]
    out_dir = Path(wav).parent / "asr_chunks"
    out_dir.mkdir(exist_ok=True)
    pattern = out_dir / "chunk_%04d.wav"
    r = ffutil._run(["-y", "-i", wav, "-f", "segment",
                     "-segment_time", str(segment_secs), "-c", "copy",
                     str(pattern)])
    if r.returncode != 0 or not list(out_dir.glob("chunk_*.wav")):
        raise VidtoolError("长音频分块失败",
                           hint=f"ffmpeg stderr 尾部: {r.stderr[-300:]}",
                           errcode="ffmpeg_failed")
    return [(str(p), i * segment_secs)
            for i, p in enumerate(sorted(out_dir.glob("chunk_*.wav")))]
