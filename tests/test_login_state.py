"""login-state handling per ADR-0004.

- stale auto-ttwid is silently re-registered once and the fetch retried
- real-cookie failures exit 2 with a hint that is an *executable instruction*
  for the agent (CDP route or ask the user)
"""
from vidlens.platforms import douyin, interpret_ytdlp_error
from vidlens.platforms.__init__ import AuthNeededError


def test_stale_ttwid_refreshes_once(monkeypatch, tmp_path):
    """First fetch fails with an auto-cookie present => cookie file removed,
    ttwid re-registered, second fetch wins. All silent."""
    auto = tmp_path / "douyin-auto.txt"
    auto.write_text("# Netscape HTTP Cookie File\n.douyin.com\tTRUE\t/\t"
                    "TRUE\t0\tttwid\tstale\n", encoding="utf-8")
    monkeypatch.setattr(douyin.cache_mod, "cookies_dir",
                        staticmethod(lambda: tmp_path))
    calls = {"fetch": 0, "regen": 0}

    def fake_fetch(vid, cf):
        calls["fetch"] += 1
        return {"aweme_id": vid} if calls["fetch"] == 2 else None

    def fake_regen():
        calls["regen"] += 1
        auto.write_text("# fresh\n.douyin.com\tTRUE\t/\tTRUE\t0\tttwid\tnew\n",
                        encoding="utf-8")
        return str(auto)

    monkeypatch.setattr(douyin, "_fetch_item", fake_fetch)
    monkeypatch.setattr(douyin, "ensure_ttwid_cookie", fake_regen)
    item = douyin._fetch_item_with_refresh("123", None)
    assert item == {"aweme_id": "123"}
    assert calls == {"fetch": 2, "regen": 1}


def test_no_refresh_loop_when_regist_fails(monkeypatch, tmp_path):
    """Refresh happens at most once even if the second fetch also fails."""
    monkeypatch.setattr(douyin.cache_mod, "cookies_dir",
                        staticmethod(lambda: tmp_path))
    (tmp_path / "douyin-auto.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(douyin, "_fetch_item", lambda v, cf: None)
    regen = {"n": 0}

    def fake_regen():
        regen["n"] += 1
        return None

    monkeypatch.setattr(douyin, "ensure_ttwid_cookie", fake_regen)
    assert douyin._fetch_item_with_refresh("123", None) is None
    assert regen["n"] == 1


def test_no_refresh_when_user_cookie_given(monkeypatch, tmp_path):
    """A real user cookie must never be silently deleted."""
    monkeypatch.setattr(douyin.cache_mod, "cookies_dir",
                        staticmethod(lambda: tmp_path))
    (tmp_path / "douyin-auto.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(douyin, "_fetch_item", lambda v, cf: None)
    regen = {"n": 0}
    monkeypatch.setattr(douyin, "ensure_ttwid_cookie",
                        lambda: regen.__setitem__("n", regen["n"] + 1) or None)
    douyin._fetch_item_with_refresh("123", "user-cookie.txt")
    assert regen["n"] == 0


def test_auth_hint_is_agent_executable():
    """exit 2 hint must contain the CDP route AND the --cookie flag."""
    class FakeErr(Exception):
        msg = "Login needed to access this"

    err = interpret_ytdlp_error("bilibili", FakeErr())
    assert isinstance(err, AuthNeededError)
    assert err.exit_code == 2
    assert "CDP" in err.hint or "浏览器自动化" in err.hint
    assert "--cookie" in err.hint
