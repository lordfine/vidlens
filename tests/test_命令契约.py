"""通过公开命令验证 Agent 契约。"""

import json

import pytest

from vidlens.cli import main


@pytest.mark.parametrize("arguments", [[], ["不存在"], ["frames", "链接", "--count", "错误"]])
def test_bad_arguments_are_json(arguments, capsys):
    assert main(arguments) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)["error"]
    assert error["code"] == "bad_args"
    assert error["hint"]


def test_explicit_frame_limit_is_honored(local_video, tmp_path):
    from vidlens.frames import extract

    result = extract(str(local_video), tmp_path / "帧图", mode="adaptive",
                     count=30, max_frames=5)
    assert len(result.records) == 5
    assert result.total_candidates == 5
