import pytest

from vidlens import urls
from vidlens.agentio import NotSupportedError, vidlensError


class TestClassify:
    def test_bilibili_bv(self):
        t = urls.classify("https://www.bilibili.com/video/BV1GJ411x7h7",
                          expand=False)
        assert t.platform is urls.Platform.bilibili
        assert t.video_id == "BV1GJ411x7h7"
        assert t.kind == "video"

    def test_bilibili_mobile(self):
        t = urls.classify("https://m.bilibili.com/video/BV1xx411c7mD",
                          expand=False)
        assert t.platform is urls.Platform.bilibili

    def test_bilibili_bangumi(self):
        t = urls.classify("https://www.bilibili.com/bangumi/play/ep123",
                          expand=False)
        assert t.platform is urls.Platform.bilibili
        assert t.kind == "bangumi"

    def test_douyin_full(self):
        t = urls.classify(
            "https://www.douyin.com/video/7607060532303169189", expand=False)
        assert t.platform is urls.Platform.douyin
        assert t.video_id == "7607060532303169189"

    def test_douyin_short(self):
        t = urls.classify("https://v.douyin.com/iRNBho5/", expand=False)
        assert t.platform is urls.Platform.douyin
        assert t.kind == "short"

    def test_douyin_ies(self):
        t = urls.classify(
            "https://www.iesdouyin.com/share/video/7123456789012345678",
            expand=False)
        assert t.platform is urls.Platform.douyin

    def test_unsupported(self):
        with pytest.raises(NotSupportedError):
            urls.classify("https://www.youtube.com/watch?v=abc", expand=False)

    def test_not_url(self):
        with pytest.raises(vidlensError) as e:
            urls.classify("随便一段文字")
        assert e.value.errcode == "bad_url"


class TestNormalize:
    def test_text_with_share_message(self):
        s = urls.normalize_input(
            "7…师父说今天必须跳完 https://v.douyin.com/AbCdEf/ 复制此链接…")
        assert s == "https://v.douyin.com/AbCdEf/"

    def test_strips_punctuation(self):
        assert urls.normalize_input("https://b23.tv/xyz。") == "https://b23.tv/xyz"
