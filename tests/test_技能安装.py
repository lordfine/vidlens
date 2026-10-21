"""验证技能安装的用户文件保护、幂等性和命令输出。"""

import json

import pytest

from vidlens import 技能
from vidlens.agentio import VidlensError
from vidlens.cli import main


def test_install_and_repeat(tmp_path):
    destination = tmp_path / "中文技能目录" / "vidlens"
    first = 技能.install(str(destination))
    second = 技能.install(str(destination))
    assert first["status"] == "installed"
    assert second["status"] == "unchanged"
    assert first["entrypoint"] == str(destination.resolve() / "SKILL.md")
    assert (destination / "SKILL.md").read_bytes() == 技能.source_path().read_bytes()


def test_conflict_preserves_existing_files(tmp_path):
    entrypoint = tmp_path / "SKILL.md"
    entrypoint.write_text("用户自定义技能", encoding="utf-8")
    other = tmp_path / "用户笔记.md"
    other.write_text("用户内容", encoding="utf-8")
    with pytest.raises(VidlensError) as error:
        技能.install(str(tmp_path))
    assert error.value.errcode == "skill_exists"
    assert entrypoint.read_text(encoding="utf-8") == "用户自定义技能"
    result = 技能.install(str(tmp_path), force=True)
    assert result["status"] == "installed"
    assert entrypoint.read_bytes() == 技能.source_path().read_bytes()
    assert other.read_text(encoding="utf-8") == "用户内容"
    assert not list(tmp_path.glob(".vidlens-*.tmp"))


def test_destination_file_is_preserved(tmp_path):
    destination = tmp_path / "用户文件"
    destination.write_text("用户内容", encoding="utf-8")
    with pytest.raises(VidlensError) as error:
        技能.install(str(destination), force=True)
    assert error.value.errcode == "skill_destination_conflict"
    assert destination.read_text(encoding="utf-8") == "用户内容"


def test_entrypoint_directory_is_preserved(tmp_path):
    entrypoint = tmp_path / "SKILL.md"
    entrypoint.mkdir()
    with pytest.raises(VidlensError) as error:
        技能.install(str(tmp_path), force=True)
    assert error.value.errcode == "skill_destination_conflict"
    assert entrypoint.is_dir()


def test_cli_missing_destination_is_structured(capsys):
    assert main(["skill", "install"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)["error"]
    assert error["code"] == "bad_args"
    assert error["hint"]


def test_cli_install_and_conflict(tmp_path, capsys):
    destination = str(tmp_path / "技能")
    assert main(["skill", "install", "--dest", destination]) == 0
    installed = json.loads(capsys.readouterr().out)
    assert installed["ok"] is True
    assert installed["status"] == "installed"
    (tmp_path / "技能" / "SKILL.md").write_text("自定义", encoding="utf-8")
    assert main(["skill", "install", "--dest", destination]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "skill_exists"


def test_cli_info_is_readable(capsys):
    assert main(["skill", "info"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert result["name"] == "vidlens"
    assert result["source"] == str(技能.source_path())


def test_install_without_hardlinks(tmp_path, monkeypatch):
    def unavailable(*arguments):
        raise OSError("文件系统不支持硬链接")

    monkeypatch.setattr(技能.os, "link", unavailable)
    result = 技能.install(str(tmp_path))
    assert result["status"] == "installed"
    assert (tmp_path / "SKILL.md").read_bytes() == 技能.source_path().read_bytes()


def test_capabilities_and_skill_have_matching_identity(capsys):
    assert main(["capabilities"]) == 0
    capabilities = json.loads(capsys.readouterr().out)
    assert capabilities["contract_version"] == 2
    assert "skill" in capabilities["commands"]
    assert main(["skill", "info"]) == 0
    information = json.loads(capsys.readouterr().out)
    assert information["version"] == capabilities["version"]
    assert len(information["skill_sha256"]) == 64
