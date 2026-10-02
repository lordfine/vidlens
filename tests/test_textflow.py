from vidlens.textflow import (fmt_stamp, join_sentences, render_paragraphs,
                              to_paragraphs)


def test_join_cjk_no_space_latin_space():
    assert join_sentences(["你好", "世界"]) == "你好世界"
    assert join_sentences(["hello", "world"]) == "hello world"
    assert join_sentences(["说hello", "世界"]) == "说hello世界"
    assert join_sentences(["hello", "说"]) == "hello说"


def test_short_fragments_folded():
    segs = [
        {"start": 0.0, "end": 2.0, "text": "如果对于基础使用不熟悉的。"},
        {"start": 2.1, "end": 3.0, "text": "朋友们推荐去看一下那期。"},  # short, folded
    ]
    paras = to_paragraphs(segs)
    # folded into the flow; single paragraph (or one merged block)
    assert all("去看一下那期" in p["text"] for p in paras)


def test_break_on_long_pause():
    segs = [
        {"start": 0.0, "end": 2.0, "text": "第一段内容说完。"},
        {"start": 10.0, "end": 12.0, "text": "第二段开始。"},  # gap 8s
    ]
    paras = to_paragraphs(segs)
    assert len(paras) == 2


def test_break_on_window():
    segs = [
        {"start": i * 4.0, "end": i * 4.0 + 3.5,
         "text": f"第{i}句话,内容再长一点点。"} for i in range(20)
    ]
    paras = to_paragraphs(segs)
    assert len(paras) >= 2
    assert all(p["end"] - p["start"] <= 60.0 for p in paras)


def test_fmt_stamp():
    assert fmt_stamp(0) == "0:00"
    assert fmt_stamp(65) == "1:05"
    assert fmt_stamp(3671) == "1:01:11"


def test_render_paragraphs_anchor():
    paras = [{"start": 12, "end": 40, "text": "一个段落。"}]
    out = render_paragraphs(paras)
    assert out == "[   0:12] 一个段落。\n"
