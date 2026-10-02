"""Optional faster-whisper backend (extra: `uv sync --extra whisper`)."""

from __future__ import annotations

import re

from ..agentio import DependencyError
from . import prepare_wav

_MODEL_MAP = {
    "whisper-tiny": "tiny", "whisper-base": "base", "whisper-small": "small",
    "whisper-medium": "medium", "whisper-large": "large-v3",
    "whisper-large-v3": "large-v3", "whisper": "small",
}


def transcribe(media_path: str, *, lang: str = "auto",
               model: str = "whisper",
               glossary: dict[str, str] | None = None) -> dict:
    try:
        from faster_whisper import WhisperModel
    except Exception as e:
        raise DependencyError(
            f"faster-whisper 未安装 ({e})",
            hint="运行 `uv sync --extra whisper` 安装;或用默认引擎 "
                 "--model sensevoice。") from e
    size = _MODEL_MAP.get(model, "small")
    compute = "auto"
    try:
        wm = WhisperModel(size, device="auto", compute_type=compute)
    except Exception:
        wm = WhisperModel(size, device="cpu", compute_type="int8")
    wav, duration = prepare_wav(media_path)
    lang_arg = None if lang in ("auto", "") else lang[:2]
    gen, info = wm.transcribe(wav, language=lang_arg, vad_filter=True,
                              beam_size=5)
    segments = []
    for s in gen:
        text = re.sub(r"\s+", " ", (s.text or "")).strip()
        if text:
            segments.append({"start": round(s.start, 3), "end": round(s.end, 3),
                             "text": text})
    from ..lexicon import normalize_segments
    segments = normalize_segments(segments, glossary)
    return {
        "engine": "faster-whisper",
        "model": size,
        "lang": lang_arg or info.language or "auto",
        "duration": round(duration, 3),
        "segments": segments,
    }
