"""按清单导出独立素材包，并校验相对引用和内容指纹。"""

# ruff: noqa: N999
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from .agentio import VidlensError
from .存储 import fingerprint, write_json


def _invalid(message):
    return VidlensError(message, errcode="bundle_invalid",
                        hint="检查 manifest.json 和引用文件；缺失缓存时重新 prepare，再重新导出。")


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("需要 JSON 对象")
        return value
    except (OSError, ValueError) as error:
        raise _invalid(f"无法读取素材包清单或证据: {path.name}") from error


def _resolve(root: Path, value: str, *, external=False) -> Path:
    if not isinstance(value, str) or not value:
        raise _invalid("素材包文件引用无效")
    path = Path(value)
    resolved = (path if path.is_absolute() else root / path).resolve()
    if not external and (path.is_absolute() or not resolved.is_relative_to(root)):
        raise _invalid(f"独立素材包引用越出自身目录: {value}")
    if not resolved.is_file():
        raise _invalid(f"素材包引用文件缺失: {value}")
    return resolved


def _references(manifest: dict) -> list[tuple[str, str]]:
    files = manifest.get("files")
    frames = manifest.get("frames")
    subtitle = manifest.get("subtitle")
    if not isinstance(files, dict) or not isinstance(frames, dict) or not isinstance(subtitle, dict):
        raise _invalid("素材包缺少文件、帧图或字幕清单")
    for key in ("manifest", "context_md", "evidence_timeline", "frames_dir"):
        if not isinstance(files.get(key), str):
            raise _invalid(f"素材包缺少必要文件引用: {key}")
    if not files.get("video_local") and not files.get("audio_local"):
        raise _invalid("素材包缺少媒体引用")
    result = [(value, key) for key, value in files.items() if key != "frames_dir" and value]
    subtitle_files = subtitle.get("files", {})
    if not isinstance(subtitle_files, dict):
        raise _invalid("字幕文件清单无效")
    result.extend((value, key) for key, value in subtitle_files.items() if value)
    for key in ("files", "scene_files"):
        records = frames.get(key, [])
        if not isinstance(records, list):
            raise _invalid("帧图记录无效")
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("file"), str):
                raise _invalid("帧图缺少文件引用")
            result.append((record["file"], "frame"))
    if manifest.get("contact_sheet"):
        result.append((manifest["contact_sheet"], "contact_sheet"))
    if isinstance(manifest.get("timeline"), dict) and manifest["timeline"].get("file"):
        result.append((manifest["timeline"]["file"], "evidence_timeline"))
    return result


def verify_bundle(directory: str | Path) -> dict:
    root = Path(directory).expanduser().resolve()
    manifest = _read(root / "manifest.json")
    portable = manifest.get("portable") is True
    references = _references(manifest)
    frame_value = manifest.get("files", {}).get("frames_dir")
    if not isinstance(frame_value, str):
        raise _invalid("帧图目录引用无效")
    frame_path = Path(frame_value)
    frame_directory = (frame_path if frame_path.is_absolute() else root / frame_path).resolve()
    if ((portable and frame_path.is_absolute()) or not frame_directory.is_relative_to(root)
            or not frame_directory.is_dir()):
        raise _invalid("帧图目录缺失或越出素材包")
    referenced = set()
    for value, role in references:
        path = _resolve(root, value, external=not portable)
        if not portable and role not in ("video_local", "audio_local") and not path.is_relative_to(root):
            raise _invalid("证据引用越出原素材包目录")
        if role == "frame" and not path.is_relative_to(frame_directory):
            raise _invalid("帧图文件不在登记的帧图目录内")
        if role == "manifest" and path != root / "manifest.json":
            raise _invalid("素材包清单没有引用自身入口")
        referenced.add(path)
    timeline = _read(_resolve(root, manifest["files"]["evidence_timeline"], external=not portable))
    if not isinstance(timeline.get("events"), list) or not isinstance(timeline.get("assets"), dict):
        raise _invalid("证据时间线格式无效")
    timeline_refs = [value for value in timeline["assets"].values() if value is not None]
    for event in timeline["events"]:
        if not isinstance(event, dict):
            raise _invalid("证据时间线事件无效")
        if event.get("reference"):
            timeline_refs.append(event["reference"])
    for value in timeline_refs:
        resolved = _resolve(root, value, external=not portable)
        if resolved not in referenced:
            raise _invalid("时间线引用了未登记的素材")
    if portable:
        checksums = manifest.get("checksums")
        if not isinstance(checksums, dict) or not checksums:
            raise _invalid("独立素材包缺少内容指纹")
        for value, digest in checksums.items():
            path = _resolve(root, value)
            if fingerprint(path) != digest:
                raise _invalid(f"素材内容校验失败: {value}")
        expected = {path.relative_to(root).as_posix() for path in referenced
                    if path != root / "manifest.json"}
        if not expected.issubset(checksums):
            raise _invalid("部分证据没有内容指纹")
    return {"directory": str(root), "portable": portable,
            "files_checked": len(referenced), "events_checked": len(timeline["events"])}


def export_bundle(source: str | Path, destination: str | Path) -> dict:
    root = Path(source).expanduser().resolve()
    target = Path(destination).expanduser().resolve()
    if target.exists() or target.is_relative_to(root):
        raise VidlensError("导出目录必须是素材包之外的新目录", errcode="export_conflict",
                           hint="通过 --out 指定尚不存在的目录；已有文件不会被覆盖。")
    verify_bundle(root)
    manifest = _read(root / "manifest.json")
    portable = manifest.get("portable") is True
    mapping = {}
    source_files = {}
    directory_alias = manifest["files"]["frames_dir"]
    mapping[directory_alias] = "frames"
    mapping[directory_alias.replace("\\", "/")] = "frames"
    for value, role in _references(manifest):
        path = _resolve(root, value, external=not portable)
        if path in source_files:
            relative = source_files[path]
        else:
            if role == "manifest":
                relative = "manifest.json"
            elif role == "frame":
                relative = f"frames/{path.name}"
            elif role in ("video_local", "audio_local"):
                relative = f"媒体/{role.removesuffix('_local')}{path.suffix}"
            else:
                relative = path.name
            if relative in source_files.values():
                raise _invalid("不同证据文件存在同名冲突")
            source_files[path] = relative
        for spelling in (value, value.replace("\\", "/"), str(path), path.as_posix()):
            mapping[spelling] = relative
    if manifest.get("video", {}).get("platform") == "local":
        original = manifest["video"].get("webpage_url")
        if isinstance(original, str):
            media = manifest["files"].get("video_local") or manifest["files"]["audio_local"]
            relative = mapping[media]
            mapping[original] = relative
            mapping[original.replace("\\", "/")] = relative

    def rewrite(value):
        if isinstance(value, dict):
            return {key: rewrite(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        return mapping.get(value, value) if isinstance(value, str) else value

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=".vidlens-export-") as temporary:
        output = Path(temporary) / "素材包"
        output.mkdir()
        (output / "frames").mkdir()
        for path, relative in source_files.items():
            if relative == "manifest.json":
                continue
            dest = output / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix.lower() == ".json":
                write_json(dest, rewrite(_read(path)))
            elif relative == "context.md":
                text = path.read_text(encoding="utf-8")
                for original in sorted(mapping, key=len, reverse=True):
                    text = text.replace(original, mapping[original])
                dest.write_text(text, encoding="utf-8")
            else:
                original_digest = fingerprint(path)
                shutil.copyfile(path, dest)
                if fingerprint(dest) != original_digest:
                    raise _invalid("复制期间素材发生变化，请重试")
        result = rewrite(manifest)
        result["portable"] = True
        result["schema_version"] = 2
        result["media"]["cache_lifetime"] = "媒体随素材包保留"
        result["checksums"] = {path.relative_to(output).as_posix(): fingerprint(path)
                               for path in output.rglob("*") if path.is_file()}
        write_json(output / "manifest.json", result)
        verify_bundle(output)
        output.rename(target)
    return {"directory": str(target), "manifest": str(target / "manifest.json"),
            "portable": True, "files": len(result["checksums"])}
