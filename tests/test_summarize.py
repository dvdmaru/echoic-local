from meeting_local import summarize
from meeting_local.summarize import safe_title


def test_safe_title_strips_unsafe():
    assert safe_title("官網改版週會：9/30 上線／Vercel 不搬") == "官網改版週會：930上線Vercel不搬"[:24]
    assert safe_title("   ") == "會議"
    assert len(safe_title("很長" * 40)) == 24


def test_build_summary_extracts_title(monkeypatch):
    monkeypatch.setattr(summarize, "_claude", lambda *a, **k: "# 官網改版第二次週會\n\n## 一句話\n測試\n")
    md, title = summarize.build_summary("x", "y", source="job", meeting_time="2026-09-14 10:55")
    assert title == "官網改版第二次週會"
    assert "# 官網改版第二次週會（2026-09-14 10:55）" in md
    assert md.count("# 官網改版第二次週會") == 1


def test_build_summary_without_title_line(monkeypatch):
    monkeypatch.setattr(summarize, "_claude", lambda *a, **k: "## 一句話\n測試\n")
    md, title = summarize.build_summary("x", "y", source="job")
    assert title == "會議摘要" and "## 一句話" in md
