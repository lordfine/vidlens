"""集中字幕优先、识别兜底、音频保留和文本产物的准备规则。"""

# ruff: noqa: N999
from __future__ import annotations

from pathlib import Path

from .agentio import VidlensError
from .asr import get_transcript_cached
from .platforms.media import save_subtitle
from .存储 import write_json


def collect(target, adapter, metadata: dict, output: Path, *,
            mode: str = "prefer_subtitles", lang: str | None = None,
            model: str = "sensevoice", cookiefile: str | None = None,
            fresh: bool = False, glossary: dict | None = None,
            keep_audio: bool = False, require_text: bool = True) -> dict:
    """通过视频来源适配器取得文字及其来源，登录和风控失败原样透传。"""
    output = output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    track, records, transcript, audio = None, [], None, None
    source = None
    if mode != "asr" and target.extra.get("subtitle_file"):
        from .platforms.本地 import read_subtitles
        track, records = read_subtitles(Path(target.extra["subtitle_file"]), lang)
    elif mode != "asr" and hasattr(adapter, "fetch_subtitles"):
        try:
            track, records = adapter.fetch_subtitles(target, metadata, cookiefile, lang=lang)
        except VidlensError as error:
            if error.errcode != "no_subtitles":
                raise
    if records:
        source = "cc"
    if not records and mode == "subtitles_only" and require_text:
        raise VidlensError("该视频没有可用字幕且已禁止 ASR", errcode="no_subtitles",
                           hint="去掉 --no-asr 自动识别，或通过 --subtitle-file 提供字幕。")
    has_audio = metadata.get("has_audio") is not False
    if has_audio and (keep_audio or (not records and mode != "subtitles_only")):
        audio = adapter.download(target, metadata, cookiefile, "audio", 1080, fresh)
    if not records and mode != "subtitles_only" and not has_audio and require_text:
        raise VidlensError("媒体不含音轨，无法识别语音", errcode="no_speech",
                           hint="提供含语音的媒体，或通过 --subtitle-file 提供字幕。")
    if not records and mode != "subtitles_only" and has_audio:
        try:
            transcript = get_transcript_cached(
                metadata["platform"], metadata["video_id"], audio["path"],
                lang=lang or "auto", model=model, fresh=fresh, glossary=glossary)
            records = transcript["segments"]
            source = "asr"
            if not records:
                if require_text:
                    raise VidlensError("未识别出语音", errcode="no_speech",
                                       hint="确认媒体包含语音，或通过 --subtitle-file 提供字幕。")
                transcript, source = None, None
        except VidlensError as error:
            if error.errcode != "no_speech" or require_text:
                raise
    if transcript and (output / "asr.json").exists():
        raise VidlensError("输出位置已有识别详情", errcode="output_exists",
                           hint="使用新的 --out 目录，以保留已有识别结果。")
    files = save_subtitle(records, output, base="subtitle" if source == "cc" else "transcript") \
        if records else {}
    if transcript:
        detail = output / "asr.json"
        write_json(detail, transcript)
        files["asr_detail"] = str(detail)
        files["detail"] = str(detail)
    return {"source": source, "track": track, "records": records, "files": files,
            "engine": transcript["engine"] if transcript else None,
            "model": transcript["model"] if transcript else None,
            "lang": (track or {}).get("lang") if source == "cc" else (transcript or {}).get("lang"),
            "provenance": (transcript or {}).get("provenance"), "audio": audio,
            "duration": (transcript or {}).get("duration", metadata.get("duration"))}
