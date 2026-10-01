"""Network E2E — opt-in only: set VIDTOOL_E2E=1 to run.

Uses live bilibili/douyin links. Anonymous douyin relies on the auto ttwid.
"""
import json
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("VIDTOOL_E2E") != "1", reason="set VIDTOOL_E2E=1 to run")

BILI = "https://www.bilibili.com/video/BV1NNh86gEMM"      # 2.8min, no CC
DOUYIN = "https://www.douyin.com/video/7607060532303169189"  # 3.8min dance


def run(*args):
    r = subprocess.run([sys.executable, "-m", "vidtool.cli", *args],
                       capture_output=True, text=True, encoding="utf-8",
                       timeout=900)
    return r


def test_bili_meta():
    r = run("meta", BILI)
    assert r.returncode == 0, r.stderr
    obj = json.loads(r.stdout)
    assert obj["platform"] == "bilibili" and obj["video_id"].startswith("BV")


def test_bili_subs_asr_fallback():
    r = run("subs", BILI, "--format", "txt")
    assert r.returncode == 0, r.stderr
    obj = json.loads(r.stdout)
    assert obj["source"] == "asr" and obj["segments"] > 0
    assert os.path.isfile(obj["primary_file"])


def test_bili_subs_no_asr_error():
    r = run("subs", BILI, "--no-asr")
    assert r.returncode == 1
    obj = json.loads(r.stderr)
    assert obj["error"]["code"] == "no_subtitles"


def test_douyin_meta():
    r = run("meta", DOUYIN, "--fresh")
    assert r.returncode == 0, r.stderr
    obj = json.loads(r.stdout)
    assert obj["platform"] == "douyin" and obj["title"]


def test_douyin_frames_scene():
    r = run("frames", DOUYIN, "--mode", "scene")
    assert r.returncode == 0, r.stderr
    obj = json.loads(r.stdout)
    assert obj["count"] > 0


def test_douyin_prepare_medium():
    r = run("prepare", DOUYIN, "--granularity", "medium")
    assert r.returncode == 0, r.stderr
    obj = json.loads(r.stdout)
    files = obj["files"]
    for key in ("context_md", "manifest", "frames_dir"):
        assert os.path.exists(files[key])
    assert obj["frames_count"] >= 8
