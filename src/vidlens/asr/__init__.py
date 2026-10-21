"""Local ASR: SenseVoice (sherpa-onnx) default, faster-whisper optional.

get_transcript(media_path) -> {
  engine, model, lang, duration,
  segments: [{start, end, text}],   # seconds, sentence-ish granularity
}
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .. import cache as cache_mod
from .. import ffutil
from ..agentio import VidlensError
from ..存储 import fingerprint, write_json


def get_transcript(media_path: str, *, lang: str = "auto",
                    model: str = "sensevoice",
                    glossary: dict[str, str] | None = None,
                    fresh: bool = False) -> dict:
    if model.startswith("whisper"):
        from . import whisper
        return whisper.transcribe(media_path, lang=lang, model=model,
                                  glossary=glossary, fresh=fresh)
    from . import sensevoice
    if model != "sensevoice":
        raise VidlensError("未知语音识别模型", errcode="bad_args",
                           hint="使用 sensevoice 或 whisper-small 等受支持模型。")
    return sensevoice.transcribe(media_path, lang=lang, glossary=glossary, fresh=fresh)


def get_transcript_cached(platform: str, video_id: str, media_path: str, *,
                          lang: str = "auto", model: str = "sensevoice",
                          fresh: bool = False,
                          glossary: dict[str, str] | None = None) -> dict:
    """ASR is expensive — cache per (video, engine, lang, glossary)."""
    from importlib.metadata import PackageNotFoundError, version

    from .. import __version__
    from ..lexicon import DEFAULT_GLOSSARY

    runtime = "faster-whisper" if model.startswith("whisper") else "sherpa-onnx"
    try:
        runtime_version = version(runtime)
    except PackageNotFoundError:
        runtime_version = "未安装"
    rules = {"builtin": DEFAULT_GLOSSARY, "custom": list((glossary or {}).items())}
    provenance = {
        "tool_version": __version__, "pipeline_version": 2,
        "media_sha256": fingerprint(media_path), "requested_model": model,
        "runtime": runtime, "runtime_version": runtime_version,
        "lang": lang or "auto",
        "corrections_sha256": hashlib.sha256(
            json.dumps(rules, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest(),
    }
    key = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()
    cf = cache_mod.video_dir(platform, video_id) / f"transcript-{key}.json"
    from ..locking import cache_write_lock
    with cache_write_lock(cf.parent, timeout=7200.0):
        if cf.is_file() and not fresh:
            try:
                cached = json.loads(cf.read_text(encoding="utf-8"))
                if cached.get("provenance") == provenance and isinstance(cached.get("segments"), list):
                    return cached
            except Exception:
                pass
        tr = get_transcript(media_path, lang=lang, model=model,
                            glossary=glossary, fresh=fresh)
        if fingerprint(media_path) != provenance["media_sha256"]:
            raise VidlensError("识别期间源媒体发生变化", errcode="media_changed",
                               hint="等待素材更新结束后重试原命令。")
        tr["provenance"] = provenance
        try:
            write_json(cf, tr)
        except OSError:
            pass
        return tr


def prepare_wav(media_path: str, *, fresh: bool = False) -> tuple[str, float]:
    """Transcode any media to 16k mono wav next to its cache dir."""
    src = Path(media_path)
    wav = src.with_suffix(".asr16k.wav")
    metadata = wav.with_suffix(".json")
    signature = {"source_sha256": fingerprint(src), "format_version": 1}
    if wav.is_file() and wav.stat().st_size > 44 and not fresh and metadata.is_file():
        try:
            stored = json.loads(metadata.read_text(encoding="utf-8"))
            if (isinstance(stored, dict)
                    and all(stored.get(key) == value for key, value in signature.items())
                    and stored.get("wav_sha256") == fingerprint(wav)):
                dur = ffutil.probe_duration(str(wav))
                return str(wav), dur or 0.0
        except (OSError, ValueError):
            pass
    temporary = wav.with_suffix(".tmp.wav")
    try:
        ffutil.make_wav(media_path, str(temporary))
        temporary.replace(wav)
        write_json(metadata, {**signature, "wav_sha256": fingerprint(wav)})
    finally:
        temporary.unlink(missing_ok=True)
    dur = ffutil.probe_duration(str(wav))
    return str(wav), dur or 0.0


def split_wav(wav: str, segment_secs: float = 30.0) -> list[tuple[str, float]]:
    """Split long wav into chunks; returns [(path, offset_seconds)]."""
    dur = ffutil.probe_duration(wav) or 0.0
    if dur <= segment_secs + 5:
        return [(wav, 0.0)]
    out_dir = Path(wav).parent / f"asr_chunks-{fingerprint(wav)[:16]}-{segment_secs:g}"
    out_dir.mkdir(exist_ok=True)
    for previous in out_dir.glob("chunk_*.wav"):
        previous.unlink()
    pattern = out_dir / "chunk_%04d.wav"
    r = ffutil._run(["-y", "-i", wav, "-f", "segment",
                     "-segment_time", str(segment_secs), "-c", "copy",
                     str(pattern)])
    if r.returncode != 0 or not list(out_dir.glob("chunk_*.wav")):
        raise VidlensError("长音频分块失败",
                           hint=f"ffmpeg stderr 尾部: {r.stderr[-300:]}",
                           errcode="ffmpeg_failed")
    return [(str(p), i * segment_secs)
            for i, p in enumerate(sorted(out_dir.glob("chunk_*.wav")))]
