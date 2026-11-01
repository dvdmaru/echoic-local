from pathlib import Path

from meeting_local import glossary

SAMPLE = """# 詞彙表

說明文字不會被當成詞。

| 正確寫法 | 逐字稿常見錯寫 | 備註 |
|---|---|---|
| 晴光 | 情光、晴廣 | 產品 |
- Northwind｜諾斯溫、諾思文
- 小藍｜｜團隊暱稱
- 範例公司｜範力公司｜刪掉這行換成你的
- 晴光｜重複的會被略過
"""


def test_parse_table_and_bullets():
    terms = glossary.parse(SAMPLE)
    names = [t.canonical for t in terms]
    assert names == ["晴光", "Northwind", "小藍"]
    assert terms[0].variants == ["情光", "晴廣"] and terms[0].note == "產品"
    assert terms[1].variants == ["諾斯溫", "諾思文"]
    assert terms[2].variants == [] and terms[2].note == "團隊暱稱"


def test_whisper_prompt_respects_budget():
    terms = glossary.parse(SAMPLE)
    base = "以下是台灣的會議錄音。"
    full = glossary.whisper_prompt(base, terms, max_chars=200)
    assert full.startswith(base) and "詞彙：晴光、Northwind、小藍。" in full
    tight = glossary.whisper_prompt(base, terms, max_chars=len(base) + 1 + len("詞彙：") + 2)
    assert tight.endswith("詞彙：晴光。")
    assert glossary.whisper_prompt(base, terms, max_chars=5) == base
    assert glossary.whisper_prompt(base, [], max_chars=200) == base


def test_apply_replaces_known_variants_longest_first():
    terms = glossary.parse("- 諾斯溫上校｜諾斯溫上校在\n- Northwind｜諾斯溫、諾思文\n- 一｜乙")
    text, n = glossary.apply("諾斯溫上校在第二名，諾思文也在，乙不動", terms)
    assert text == "諾斯溫上校第二名，Northwind也在，乙不動"  # 長的先換；1 個字的錯寫不換
    assert n == 2


def test_ensure_file_and_markdown_block(tmp_path: Path):
    path = tmp_path / "詞彙表.md"
    assert glossary.ensure_file(path) is True
    assert glossary.ensure_file(path) is False
    assert glossary.load(path) == []  # 範本那行會被略過
    md = glossary.markdown_block(glossary.parse(SAMPLE))
    assert md.splitlines()[0].startswith("| 正確寫法") and "| 晴光 | 情光、晴廣 | 產品 |" in md
    assert glossary.markdown_block([]) == ""
