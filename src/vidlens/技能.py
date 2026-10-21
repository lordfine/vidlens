"""提供随 CLI 分发的 Skill，并将入口安装到指定目录。"""

# 中文模块名遵循项目的中文文件命名要求。
# ruff: noqa: N999

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from . import __version__
from .agentio import DependencyError, VidlensError
from .存储 import fingerprint


def source_path() -> Path:
    """源码树和安装包共享仓库根目录的同一份技能定义。"""
    repository = Path(__file__).resolve().parents[2]
    source = repository / "SKILL.md"
    if (repository / "pyproject.toml").is_file() and source.is_file():
        return source
    bundled = Path(__file__).resolve().parent / "技能资源" / "SKILL.md"
    if bundled.is_file():
        return bundled
    raise DependencyError(
        "安装包中缺少 vidlens Skill",
        hint="重新安装当前版本的 vidlens CLI 后重试。",
    )


def info() -> dict:
    source = source_path()
    return {"name": "vidlens", "version": __version__, "source": str(source),
            "skill_sha256": fingerprint(source), "contract_version": 2}


def install(destination: str, *, force: bool = False) -> dict:
    """安装一个技能目录；重复安装无副作用，覆盖已有改动需显式指定。"""
    content = source_path().read_bytes()
    directory = Path(destination).expanduser().resolve()
    entrypoint = directory / "SKILL.md"
    result = {"name": "vidlens", "version": __version__,
              "directory": str(directory), "entrypoint": str(entrypoint)}
    if directory.exists() and not directory.is_dir():
        raise VidlensError(
            f"技能目录已被文件占用: {directory}",
            hint="通过 --dest 指定技能目录，例如用户技能目录下的 vidlens 子目录。",
            errcode="skill_destination_conflict",
        )
    if entrypoint.is_symlink() or (entrypoint.exists() and not entrypoint.is_file()):
        raise VidlensError(
            f"技能入口不是普通文件: {entrypoint}",
            hint="通过 --dest 选择另一个技能目录，或先自行处理该入口。",
            errcode="skill_destination_conflict",
        )
    if entrypoint.is_file():
        if entrypoint.read_bytes() == content:
            return {**result, "status": "unchanged"}
        if not force:
            raise VidlensError(
                f"技能入口已存在且内容不同: {entrypoint}",
                hint="先备份已有 SKILL.md；确认替换后，在原安装命令中添加 --force。"
                     "同目录中的其他文件会保留。",
                errcode="skill_exists",
            )
    temporary = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".vidlens-",
                                         suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        # 优先发布完整临时文件；无硬链接的文件系统使用独占创建。
        if force:
            temporary.replace(entrypoint)
        else:
            # 独占创建防止并发安装覆盖刚刚写入的用户文件。
            try:
                try:
                    os.link(temporary, entrypoint)
                except FileExistsError:
                    raise
                except OSError:
                    with entrypoint.open("xb") as output:
                        try:
                            output.write(content)
                        except OSError:
                            output.close()
                            entrypoint.unlink(missing_ok=True)
                            raise
            except FileExistsError as e:
                if entrypoint.is_file() and entrypoint.read_bytes() == content:
                    return {**result, "status": "unchanged"}
                raise VidlensError(
                    f"技能入口在安装期间已被创建: {entrypoint}",
                    hint="检查该文件后重试；确认替换时使用 --force。",
                    errcode="skill_exists",
                ) from e
    except OSError as e:
        raise VidlensError(
            f"无法写入技能目录: {directory}: {e}",
            hint="检查目标路径、目录权限与磁盘空间，或通过 --dest 选择其他目录。",
            errcode="skill_install_failed",
        ) from e
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {**result, "status": "installed"}
