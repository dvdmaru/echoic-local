from pathlib import Path

import pytest

from meeting_local import index, library

SUMMARY = """<!-- 來源：x｜產生時間：2026-11-01 10:00 -->

# {title}（{date} 10:00）

## 一句話
{one}

## 決議
- 官網 12 月上線 [00:03:10]
- 預算維持 30 萬 [00:10:00]

## 待辦
- [ ] 寄報價單｜負責人：Charlie｜時間：週五｜[00:12:30]
- [x] 確認網域｜負責人：小王｜時間：未指定｜[00:20:01]

## 數字表
| 數字 | 指什麼 | 誰說的 | 時間戳 |
|---|---|---|---|
| 30 萬 | 預算 | SPEAKER_00 | [00:10:00] |

## 未確認專名
- 無

## 品質註記
- 無
"""

TRANSCRIPT = """# 逐分鐘逐字稿（來源：audio.wav）

## 00:03
[00:03:10] SPEAKER_00：我們官網就抓十二月上線
## 00:10
[00:10:00] SPEAKER_01：預算維持三十萬，報價單週五前寄
"""


def make(root: Path, name: str, title: str, one: str = "討論官網改版", labels: dict | None = None,
         summary: bool = True) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "transcript-by-minute.txt").write_text(TRANSCRIPT, encoding="utf-8")
    if summary:
        (d / "summary.md").write_text(SUMMARY.format(title=title, date=name[:10], one=one), encoding="utf-8")
    if labels:
        library.write_meta(d, labels=labels)
    return d


@pytest.fixture
def root(tmp_path: Path) -> Path:
    make(tmp_path, "2026-10-01-1000-官網啟動", "官網啟動會", labels={"客戶": "甲公司", "專案": "官網"})
    make(tmp_path, "2026-10-15-1400-官網進度", "官網進度會", one="確認設計稿", labels={"客戶": "甲公司", "專案": "官網"})
    make(tmp_path, "2026-10-20-0900-乙公司提案", "乙公司提案", one="提案廣告投放", labels={"客戶": "乙公司"})
    make(tmp_path, "2026-11-01-1100", "未分類會議", summary=False)
    return tmp_path


def test_meta_roundtrip_and_partial_update(tmp_path: Path):
    d = tmp_path / "m"
    d.mkdir()
    assert library.read_meta(d) == {"labels": {}, "private": False}
    library.write_meta(d, labels={"客戶": "甲", "專案": "官網"})
    library.write_meta(d, labels={"專案": ""}, private=True)  # 清掉專案，客戶不動
    assert library.read_meta(d) == {"labels": {"客戶": "甲"}, "private": True}
    assert not list(d.glob(".*.tmp"))


def test_load_parses_sections_and_todos(root: Path):
    ms = library.load_meetings(root)
    assert [m.id for m in ms][0] == "2026-11-01-1100"  # 最新在前
    m = library.find(ms, "2026-10-01-1000-官網啟動")
    assert m.title == "官網啟動會"
    assert m.one_liner == "討論官網改版"
    assert m.decisions == ["官網 12 月上線 [00:03:10]", "預算維持 30 萬 [00:10:00]"]
    assert [(t.text, t.done, t.owner, t.due, t.timestamp) for t in m.todos] == [
        ("寄報價單", False, "Charlie", "週五", "00:12:30"),
        ("確認網域", True, "小王", "未指定", "00:20:01"),
    ]
    assert m.labels == {"客戶": "甲公司", "專案": "官網"}


def test_load_skips_underscore_folders(root: Path):
    (root / library.THREADS_DIR).mkdir()
    (root / library.THREADS_DIR / "summary.md").write_text("# x", encoding="utf-8")
    assert all(not m.id.startswith("_") for m in library.load_meetings(root))


def test_filter_by_labels_dates_and_unlabeled(root: Path):
    ms = library.load_meetings(root)
    assert len(library.filter_meetings(ms, {"客戶": "甲公司"})) == 2
    assert len(library.filter_meetings(ms, {"客戶": "甲公司", "專案": "官網"})) == 2
    assert [m.id for m in library.filter_meetings(ms, {"客戶": library.UNLABELED})] == ["2026-11-01-1100"]
    assert len(library.filter_meetings(ms, date_from="2026-10-15", date_to="2026-10-20")) == 2
    vals = library.label_values(ms, ["客戶", "專案"])
    assert vals["客戶"] == {"甲公司": 2, "乙公司": 1}


def test_search_requires_all_terms_and_ranks_title(root: Path):
    ms = library.load_meetings(root)
    res = library.search(ms, "預算 報價單")
    assert len(res) == 4  # 逐字稿每場都有
    res = library.search(ms, "提案")
    assert res[0]["meeting"].id == "2026-10-20-0900-乙公司提案"  # 標題命中排最前
    hit = library.search(ms, "十二月")[0]["hits"][0]
    assert hit == {"source": "逐字稿", "timestamp": "00:03:10", "text": "SPEAKER_00：我們官網就抓**十二月**上線"}
    assert library.search(ms, "十二月", include_transcript=False) == []
    assert library.search(ms, "   ") == []


def test_search_case_insensitive(tmp_path: Path):
    make(tmp_path, "2026-10-01-1000", "SEO 週會")
    assert len(library.search(library.load_meetings(tmp_path), "seo")) == 1


def test_thread_render_and_refresh(root: Path):
    labels = {"客戶": "甲公司", "專案": "官網"}
    ms = library.filter_meetings(library.load_meetings(root), labels)
    path = library.write_thread(root, labels, ms)
    text = path.read_text(encoding="utf-8")
    assert path.parent.name == library.THREADS_DIR
    assert "# 專案追蹤：客戶：甲公司／專案：官網" in text
    assert text.index("2026-10-01 10:00｜官網啟動會") < text.index("2026-10-15 14:00｜官網進度會")  # 舊到新
    assert "## 未完成待辦（2）" in text and "## 已完成待辦（2）" in text
    assert library.existing_threads(root) == [labels]

    # 新會議進來：refresh 會更新涵蓋它的追蹤檔，也會替它自己的分類建一份
    new = make(root, "2026-11-05-1000-官網驗收", "官網驗收", labels={"客戶": "甲公司", "專案": "官網"})
    written = library.refresh_threads(root, new)
    assert written == [path]
    assert "官網驗收" in path.read_text(encoding="utf-8")


def test_thread_keeps_ai_report_and_marks_stale(root: Path):
    labels = {"客戶": "甲公司"}
    ms = library.filter_meetings(library.load_meetings(root), labels)
    library.write_thread(root, labels, ms, ai_report="### 目前進度\n- 進行中（10/15 官網進度會）", ai_meta="Claude 整理")
    report, ids = library.read_thread_report(root, labels)
    assert "進行中" in report and len(ids) == 2
    make(root, "2026-11-05-1000-甲追加", "甲追加", labels={"客戶": "甲公司"})
    ms2 = library.filter_meetings(library.load_meetings(root), labels)
    text = library.write_thread(root, labels, ms2).read_text(encoding="utf-8")  # ai_report=None＝沿用
    assert "進行中（10/15 官網進度會）" in text
    assert "可能過期" in text


def test_project_report_input_reads_summaries_only(root: Path):
    ms = library.filter_meetings(library.load_meetings(root), {"客戶": "甲公司"})
    text = library.project_report_input({"客戶": "甲公司"}, ms)
    assert "### 決議" in text and "### 待辦" in text
    assert "SPEAKER_00：我們官網" not in text  # 不送逐字稿
    assert text.index("官網啟動會") < text.index("官網進度會")


def test_export_markdown_and_html(root: Path, tmp_path: Path):
    ms = library.load_meetings(root)
    one = library.find(ms, "2026-10-01-1000-官網啟動")
    md = library.meeting_markdown(one)
    assert md.startswith("# 官網啟動會（2026-10-01 10:00）")
    assert "客戶：甲公司" in md and "## 逐字稿" in md and "<!--" not in md

    out = library.export(tmp_path / "x.html", "甲公司 會議彙整", library.filter_meetings(ms, {"客戶": "甲公司"}),
                         fmt="html", include_transcript=False)
    page = out.read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>")
    assert "<h1>甲公司 會議彙整</h1>" in page
    assert '<input type="checkbox" disabled checked> 確認網域' in page
    assert "<table>" in page and "<th>數字</th>" in page
    assert "SPEAKER_01" not in page  # 多場預設不附逐字稿時沒帶到


def test_markdown_to_html_escapes():
    page = library.markdown_to_html("# a<b>\n\n- <script>x</script> **粗** [[f/summary\\|摘要]]")
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "<strong>粗</strong>" in page and "摘要" in page and "[[" not in page


def test_export_name():
    assert library.export_name("官網/週會: 確認", "2026-10-01", "html") == "官網週會確認 2026-10-01.html"


def test_index_shows_labels_and_threads(root: Path):
    library.refresh_threads(root, root / "2026-10-01-1000-官網啟動")
    text = index.render(index.scan(root), root)
    assert "| 分類 |" in text and "甲公司／官網" in text
    assert "## 專案追蹤" in text and "客戶：甲公司／專案：官網" in text
