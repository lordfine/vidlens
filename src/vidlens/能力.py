"""供 Agent 核对所调用 CLI 的能力与兼容版本。"""

# ruff: noqa: N999
from . import __version__


def describe() -> dict:
    return {"version": __version__, "contract_version": 2, "bundle_schema_version": 2,
            "skill_format_version": 1,
            "commands": ["meta", "subs", "transcribe", "frames", "prepare",
                         "cache", "doctor", "skill", "capabilities", "export", "verify"],
            "features": ["adaptive_frames", "evidence_timeline", "content_cache",
                         "skill_install", "local_media", "subtitle_file", "portable_bundle"],
            "inputs": ["douyin", "bilibili", "local_file"]}
