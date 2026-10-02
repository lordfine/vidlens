"""SenseVoice via sherpa-onnx. Model auto-downloads on first use (~230MB)."""

from __future__ import annotations

import tarfile
import re
from pathlib import Path

from .. import cache as cache_mod
from ..agentio import BlockedError, DependencyError, vidlensError
from . import prepare_wav, split_wav

MODEL_DIRNAME = "sensevoice"
MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
             "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2")

_SENT_END = "。！？；!?\n"
_SENT_SOFT = "，,、"

_LATIN_TAIL = re.compile(r"[A-Za-z]{1,4}$")
_LATIN_HEAD = re.compile(r"^[A-Za-z]{1,4}(?![A-Za-z])")


def _merge_fragments(segs: list[dict]) -> list[dict]:
    """Re-join words cut at chunk/sentence boundaries ("...省 to" + "ken的...").

    Only merges when the previous tail and next head are short latin
    fragments, the gap is under a second, and the previous segment has no
    sentence-final punctuation — conservative by design.
    """
    out: list[dict] = []
    for s in segs:
        if out:
            prev = out[-1]
            tail = _LATIN_TAIL.search(prev["text"])
            head = _LATIN_HEAD.match(s["text"])
            near = 0 <= s["start"] - prev["end"] < 1.0
            clean_end = prev["text"][-1] not in "。！？；!?;，,、. "
            if tail and head and near and clean_end:
                prev["text"] += s["text"]
                prev["end"] = s["end"]
                continue
        out.append(dict(s))
    return out


def _model_dir() -> Path:
    return cache_mod.models_dir() / MODEL_DIRNAME


def model_ready() -> bool:
    d = _model_dir()
    return (d / "model.int8.onnx").is_file() and (d / "tokens.txt").is_file()


def ensure_model() -> Path:
    d = _model_dir()
    if model_ready():
        return d
    d.mkdir(parents=True, exist_ok=True)
    import httpx
    archive = d / "model.tar.bz2"
    try:
        with httpx.Client(follow_redirects=True, timeout=600) as c:
            with c.stream("GET", MODEL_URL) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                done = 0
                with open(archive, "wb") as f:
                    for chunk in resp.iter_bytes(1 << 20):
                        f.write(chunk)
                        done += len(chunk)
                if total and done < total:
                    raise IOError(f"download truncated {done}/{total}")
    except Exception as e:
        archive.unlink(missing_ok=True)
        raise BlockedError(
            f"SenseVoice 模型下载失败: {e}",
            hint="检查网络(需访问 github.com);或手动下载 "
                 f"{MODEL_URL} 解压后把 model.int8.onnx 和 tokens.txt 放到 "
                 f"{d}。") from e
    try:
        with tarfile.open(archive, "r:bz2") as tf:
            members = [m for m in tf.getmembers()
                       if Path(m.name).name in ("model.int8.onnx", "tokens.txt")]
            for m in members:
                m.name = Path(m.name).name
                tf.extract(m, d)
    except Exception as e:
        raise DependencyError(
            f"模型包解压失败: {e}",
            hint=f"手动解压 {archive} 并将 model.int8.onnx/tokens.txt 放入 {d}。"
        ) from e
    finally:
        archive.unlink(missing_ok=True)
    if not model_ready():
        raise DependencyError("模型文件不完整",
                              hint=f"期望 {d}/model.int8.onnx 与 tokens.txt。")
    return d


def ensure_ort_dll() -> None:
    """Make sure sherpa-onnx resolves the venv's onnxruntime.dll on Windows.

    Some machines carry a stale onnxruntime.dll in System32 (found before
    site-packages in the default DLL search order), which crashes sherpa-onnx
    with an ORT API-version mismatch. Copying our wheel's DLL next to
    python.exe (first directory searched) sidesteps it.
    """
    import sys
    if sys.platform != "win32":
        return
    try:
        import sysconfig
        from pathlib import Path
        import onnxruntime
        capi = Path(onnxruntime.__file__).parent / "capi"
        src = capi / "onnxruntime.dll"
        if not src.is_file():
            return
        dests = [Path(sysconfig.get_paths()["scripts"]) / "onnxruntime.dll"]
        # locate sherpa's lib dir WITHOUT importing it (importing would load
        # the stale DLL before our copies are in place)
        try:
            import importlib.util
            spec = importlib.util.find_spec("sherpa_onnx")
            if spec and spec.submodule_search_locations:
                dests.append(Path(spec.submodule_search_locations[0]) /
                             "lib" / "onnxruntime.dll")
        except Exception:
            pass
        for dst in dests:
            try:
                if not dst.is_file() or dst.stat().st_size != src.stat().st_size:
                    import shutil
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
            except OSError:
                pass
    except Exception:
        pass


def _import_sherpa():
    """Import sherpa_onnx with a correct onnxruntime available (Windows)."""
    ensure_ort_dll()
    try:
        import onnxruntime  # noqa: F401  (preload correct ORT, belt & braces)
    except Exception:
        pass
    import sherpa_onnx
    return sherpa_onnx


def _recognizer(lang: str):
    try:
        sherpa_onnx = _import_sherpa()
    except Exception as e:
        raise DependencyError(
            f"sherpa-onnx 未安装 ({e})",
            hint="在项目目录执行 `uv sync` 安装依赖后重试。") from e
    d = ensure_model()
    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(d / "model.int8.onnx"),
        tokens=str(d / "tokens.txt"),
        language=_map_lang(lang),
        use_itn=True,
        num_threads=4,
    )


def _map_lang(lang: str) -> str:
    lang = (lang or "auto").lower()
    if lang in ("zh", "zh-cn", "zh-hans", "chinese"):
        return "zh"
    if lang in ("en", "english"):
        return "en"
    if lang in ("ja", "japanese"):
        return "ja"
    if lang in ("ko", "korean"):
        return "ko"
    if lang in ("yue", "cantonese"):
        return "yue"
    return "auto"


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _sentences_from_result(result, offset: float) -> list[dict]:
    """Group token stream into sentence-ish segments using timestamps."""
    toks = list(getattr(result, "tokens", []) or [])
    ts = list(getattr(result, "timestamps", []) or [])
    raw_text = _clean(getattr(result, "text", "") or "")
    if not toks or not ts or len(toks) != len(ts):
        return [{"start": offset, "end": offset, "text": raw_text}] \
            if raw_text else []

    segs: list[dict] = []
    buf_tokens: list[str] = []
    buf_start = None
    buf_end = None

    def flush():
        nonlocal buf_tokens, buf_start, buf_end
        if buf_tokens:
            text = "".join(buf_tokens)
            text = re.sub(r"\s+", " ", text).strip(_SENT_SOFT + " ").strip()
            # SentencePiece leaves spaces between CJK tokens ("盘 点") —
            # drop spaces only *between* CJK chars, keep latin word gaps
            cjk = r"\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af"
            text = re.sub(
                rf"(?<=[{cjk}])\s+(?=[{cjk}])", "", text)
            # keep only segments with real content (not bare punctuation)
            if text and re.search(rf"[\w{cjk}]", text):
                segs.append({"start": round(offset + buf_start, 3),
                             "end": round(offset + max(buf_end, buf_start + .3), 3),
                             "text": text})
        buf_tokens, buf_start, buf_end = [], None, None

    for tok, t in zip(toks, ts):
        if buf_start is None:
            buf_start = t
        buf_end = t
        buf_tokens.append(tok)
        if any(ch in _SENT_END for ch in tok) and len(buf_tokens) > 1:
            flush()
    flush()
    # fix: drop trailing empty
    return [s for s in segs if s["text"]]


def _load_samples(wav_path: str):
    import wave
    import numpy as np
    with wave.open(wav_path, "rb") as w:
        sr = w.getframerate()
        data = w.readframes(w.getnframes())
    samples = np.frombuffer(data, dtype=np.int16).astype("float32") / 32768.0
    return sr, samples


def transcribe(media_path: str, *, lang: str = "auto",
               glossary: dict[str, str] | None = None) -> dict:
    rec = _recognizer(lang)
    wav, duration = prepare_wav(media_path)
    segments: list[dict] = []
    for chunk, offset in split_wav(wav):
        sr, samples = _load_samples(chunk)
        stream = rec.create_stream()
        stream.accept_waveform(sr, samples)
        rec.decode_stream(stream)
        segments.extend(_sentences_from_result(stream.result, offset))
    segments = _merge_fragments(segments)
    from ..lexicon import normalize_segments
    segments = normalize_segments(segments, glossary)
    if not segments:
        raise vidlensError(
            "ASR 未识别出任何语音",
            hint="视频可能没有语音(纯音乐/静音);或语言设置不对,试 --lang auto。",
            errcode="no_speech")
    return {
        "engine": "sensevoice",
        "model": "sense-voice-zh-en-ja-ko-yue-int8",
        "lang": lang,
        "duration": round(duration, 3),
        "segments": segments,
    }
