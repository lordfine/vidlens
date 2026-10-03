"""S4: frames.extract() reports truncation instead of silently dropping."""

from vidlens import frames


def test_extract_result_shape_and_truncation(monkeypatch, tmp_path):
    """80 candidates => truncated flag, total kept, records capped."""
    many = [{"file": f"frame_{i:04d}_{float(i)}s.jpg", "t": float(i),
             "index": i, "width": 1, "height": 1, "bytes": 1}
            for i in range(80)]
    monkeypatch.setattr(frames, "_extract_stream", lambda *a, **k: list(many))
    res = frames.extract("x.mp4", tmp_path, mode="scene", duration=100)
    assert res.truncated is True
    assert res.total_candidates == 80
    assert len(res.records) == frames.MAX_FRAMES


def test_extract_result_no_truncation_when_under(monkeypatch, tmp_path):
    few = [{"file": f"f{i}.jpg", "t": float(i), "index": i,
            "width": 1, "height": 1, "bytes": 1} for i in range(5)]
    monkeypatch.setattr(frames, "_extract_stream", lambda *a, **k: list(few))
    res = frames.extract("x.mp4", tmp_path, mode="keyframe", duration=10)
    assert res.truncated is False
    assert res.total_candidates == 5
    assert len(res.records) == 5


def test_extract_count_mode_never_truncates(tmp_path, monkeypatch):
    """count mode is capped at input (<=MAX_FRAMES), never truncated."""
    recs = [{"file": "f.jpg", "t": 1.0, "index": 0, "width": 1,
             "height": 1, "bytes": 1}]
    monkeypatch.setattr(frames, "_extract_count",
                        lambda *a, **k: list(recs))
    res = frames.extract("x.mp4", tmp_path, mode="count", duration=10)
    assert res.truncated is False and len(res.records) == 1
