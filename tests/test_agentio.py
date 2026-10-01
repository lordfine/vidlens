import json

from vidtool import agentio
from vidtool.agentio import (AuthNeededError, BlockedError, DependencyError,
                             VidtoolError, emit, emit_error)


def test_emit_json_stdout(capsys):
    emit({"platform": "douyin", "title": "中文标题"})
    out = capsys.readouterr().out
    obj = json.loads(out)
    assert obj["ok"] is True
    assert obj["title"] == "中文标题"   # ensure_ascii=False


def test_emit_error_stderr_and_code(capsys):
    err = AuthNeededError("需要登录", hint="让用户提供 --cookie")
    code = emit_error(err)
    errout = capsys.readouterr().err
    obj = json.loads(errout)
    assert obj["ok"] is False
    assert obj["error"]["code"] == "auth_needed"
    assert obj["error"]["hint"] == "让用户提供 --cookie"
    assert code == agentio.EXIT_AUTH


def test_exit_codes_distinct():
    assert VidtoolError("x").exit_code == 1
    assert AuthNeededError("x").exit_code == 2
    assert BlockedError("x").exit_code == 3
    assert DependencyError("x").exit_code == 4


def test_custom_errcode():
    e = VidtoolError("x", errcode="no_subtitles", hint="h")
    assert e.errcode == "no_subtitles"
