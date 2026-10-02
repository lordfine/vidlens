from vidlens import frames


def test_scale_filter_none():
    assert frames._scale_filter(None) == ""
    assert frames._scale_filter(0) == ""


def test_scale_filter_covers_both_orientations():
    f = frames._scale_filter(1280)
    assert "if(gt(iw,ih)" in f and "1280" in f


def test_parse_pts_times():
    err = ("n:0 pts:12345 pts_time:1.234 ... pos:1\n"
           "n:1 pts:24690 pts_time:2.469")
    assert frames._parse_pts_times(err) == [1.234, 2.469]


def test_idx_from_name():
    assert frames._idx_from_name("frame_0007_83.40s.jpg") == 7
    assert frames._idx_from_name("weird.jpg") == 0


def test_extract_unknown_mode(tmp_path):
    import pytest
    from vidlens.agentio import vidlensError
    with pytest.raises(vidlensError):
        frames.extract("x.mp4", tmp_path, mode="nope")
