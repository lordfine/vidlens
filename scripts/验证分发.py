"""从构建产物隔离安装，验证真实 CLI、Skill 与离线素材包链路。"""

from __future__ import annotations

import json
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from importlib.metadata import version
from pathlib import Path


def run(command, *, cwd):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                            encoding="utf-8", timeout=300)
    if result.returncode:
        raise RuntimeError(f"分发验证命令失败: {command[0]}\n{result.stderr}")
    return result.stdout


def main():
    repository = Path(__file__).resolve().parents[1]
    release = version("vidlens")
    wheel = repository / "dist" / f"vidlens-{release}-py3-none-any.whl"
    source = repository / "dist" / f"vidlens-{release}.tar.gz"
    with zipfile.ZipFile(wheel) as archive:
        assert archive.read("vidlens/技能资源/SKILL.md") == (repository / "SKILL.md").read_bytes()
    with tarfile.open(source) as archive:
        assert any(name.endswith("/SKILL.md") for name in archive.getnames())
        assert any(name.endswith("/src/vidlens/技能.py") for name in archive.getnames())
    with tempfile.TemporaryDirectory(prefix="vidlens-分发验证-") as temporary:
        root = Path(temporary).resolve()
        environment = root / "独立环境"
        run(["uv", "venv", "--python", sys.executable, str(environment)], cwd=root)
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        run(["uv", "pip", "install", "--python", str(python), str(wheel)], cwd=root)

        def cli(*arguments):
            return json.loads(run([str(python), "-I", "-X", "utf8", "-m", "vidlens.cli", *arguments], cwd=root))

        capabilities = cli("capabilities")
        assert capabilities["version"] == release and capabilities["contract_version"] == 2
        assert {"local_media", "portable_bundle", "skill_install"}.issubset(capabilities["features"])
        information = cli("skill", "info")
        assert Path(information["source"]).is_relative_to(environment)
        skill = root / "Agent技能" / "vidlens"
        assert cli("skill", "install", "--dest", str(skill))["status"] == "installed"
        assert cli("skill", "install", "--dest", str(skill))["status"] == "unchanged"
        assert (skill / "SKILL.md").read_bytes() == (repository / "SKILL.md").read_bytes()
        ffmpeg = run([str(python), "-I", "-X", "utf8", "-c",
                      "from vidlens.ffutil import ffmpeg_path; print(ffmpeg_path())"], cwd=root).strip()
        media = root / "离线视频.mp4"
        run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
             "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=10", "-f", "lavfi", "-i",
             "sine=frequency=440:sample_rate=16000", "-t", "1", "-c:v", "mpeg4", "-c:a", "aac",
             str(media)], cwd=root)
        media.with_suffix(".srt").write_text(
            "1\n00:00:00,000 --> 00:00:00,900\n离线分发验证\n", encoding="utf-8")
        bundle = root / "素材包"
        # 子进程只使用此次验证的缓存，不读取或修改用户现有媒体。
        import os
        previous = os.environ.get("vidlens_CACHE")
        os.environ["vidlens_CACHE"] = str(root / "管理缓存")
        try:
            prepared = cli("prepare", str(media), "--no-asr", "--frames-count", "3",
                           "--max-frames", "3", "--out", str(bundle))
            assert prepared["subtitle"]["source"] == "cc"
            exported = root / "可搬运素材包"
            assert cli("export", str(bundle), "--out", str(exported))["portable"]
            bundle.rename(root / "移走的原素材包")
            (root / "管理缓存").rename(root / "移走的原缓存")
            relocated = root / "移动后的素材包"
            exported.rename(relocated)
            assert cli("verify", str(relocated))["portable"]
        finally:
            if previous is None:
                os.environ.pop("vidlens_CACHE", None)
            else:
                os.environ["vidlens_CACHE"] = previous
    print(json.dumps({"ok": True, "version": release,
                      "验证": ["源码包", "wheel", "隔离安装", "Skill安装", "本地媒体", "搬迁后校验"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
