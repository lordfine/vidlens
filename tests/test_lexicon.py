from vidlens.lexicon import (
    DEFAULT_GLOSSARY,
    glossary_hash,
    normalize_segments,
    normalize_text,
    parse_glossary_arg,
)


def test_squash_fixes_fragmented_terms():
    assert normalize_text("cha t g P T") == "ChatGPT"
    assert normalize_text("code ex") == "Codex"
    assert normalize_text("to ken") == "token"
    assert normalize_text("盘点codedex发布") == "盘点Codex发布"
    assert normalize_text("deepsick的官网") == "DeepSeek的官网"
    assert normalize_text("用CC sw itch切换") == "用CC sw itch切换"  # unknown stays


def test_normal_words_untouched():
    assert normalize_text("hello world foo") == "hello world foo"
    assert normalize_text("i have an idea") == "i have an idea"


def test_extra_glossary_inline():
    # GBT6 also hits the built-in gbt6 -> GPT-6 entry
    assert normalize_text("用GBT6露娜模型") == "用GPT-6露娜模型"
    assert normalize_text("用 GBT six lu na 模型",
                          extra={"gbtsixluna": "GPT-6 Luna"}) == \
        "用 GPT-6 Luna 模型"


def test_extra_glossary_cjk_substring():
    # CJK mis-hearings are fixed via plain substring replace
    assert normalize_text("省token的携修技巧", extra={"携修": "邪修"}) == \
        "省token的邪修技巧"
    assert normalize_text("用派agent接入模型", extra={"派agent": "pi-agent"}) == \
        "用pi-agent接入模型"


def test_case_only_normalization():
    assert normalize_text("openai 的 api") == "OpenAI 的 API"


def test_normalize_segments():
    segs = [{"start": 0, "end": 1, "text": "code ex 很好用"}]
    normalize_segments(segs)
    assert segs[0]["text"] == "Codex 很好用"


def test_parse_glossary_arg():
    assert parse_glossary_arg(None) is None
    d = parse_glossary_arg("to ken=token; code ex=Codex")
    assert d == {"to ken": "token", "code ex": "Codex"}


def test_parse_glossary_json_file(tmp_path):
    f = tmp_path / "g.json"
    f.write_text('{"x y": "Z"}', encoding="utf-8")
    assert parse_glossary_arg(str(f)) == {"x y": "Z"}


def test_glossary_hash_stable_and_short():
    a = glossary_hash({"k": "v"})
    assert a == glossary_hash({"k": "v"})
    assert glossary_hash(None) == ""
    assert len(a) == 8


def test_default_glossary_sane():
    assert DEFAULT_GLOSSARY["chatgpt"] == "ChatGPT"
    assert "token" in DEFAULT_GLOSSARY.values()
