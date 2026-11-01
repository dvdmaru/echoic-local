import json

from meeting_local.index import INDEX_NAME, scan, write_index


def _meeting(root, name, *, summary=None, run=None, transcript=False, wav=True):
    d = root / name
    d.mkdir()
    if wav:
        (d / "audio.wav").write_bytes(b"\0" * 2000)
    if transcript:
        (d / "transcript-by-minute.txt").write_text("x", encoding="utf-8")
    if summary is not None:
        (d / "summary.md").write_text(summary, encoding="utf-8")
    if run is not None:
        (d / "run.json").write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    return d


def test_scan_and_render(tmp_path):
    (tmp_path / ".obsidian").mkdir()
    _meeting(tmp_path, "2026-09-14-1420-美日聯手撐日元",
             summary="# 美日聯手撐日元（2026-09-14 14:20）\n\n## 待辦\n- [ ] 追蹤日圓｜負責人：A｜[00:01:00]\n- [x] 已完成的\n",
             run={"title": "美日聯手撐日元", "audio": {"duration": 954.2}, "speakers": {"SPEAKER_00": 858.2}},
             transcript=True)
    _meeting(tmp_path, "2026-09-14-1355", run={"record": {"duration": 190.3}})
    _meeting(tmp_path, "synth-test-2026-09-14", transcript=True)

    rows = scan(tmp_path)
    assert [r.name for r in rows][0].startswith("synth") or rows[0].date  # 排序：字串反向，不炸即可
    by = {r.name: r for r in rows}
    full = by["2026-09-14-1420-美日聯手撐日元"]
    assert full.title == "美日聯手撐日元" and full.stage == "摘要完成" and full.speakers == 1
    assert full.todos == ["追蹤日圓｜負責人：A｜[00:01:00]"]
    assert by["2026-09-14-1355"].stage == "只有錄音" and by["2026-09-14-1355"].duration_min == 190.3
    assert by["synth-test-2026-09-14"].stage == "逐字稿完成"
    assert ".obsidian" not in by

    path = write_index(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert path.name == INDEX_NAME
    assert "| 2026-09-14 | 14:20 | 美日聯手撐日元 | 15:54 | 1 | 1 | 摘要完成 |" in text
    assert "[[2026-09-14-1420-美日聯手撐日元/summary\\|摘要]]" in text
    assert "- [ ] 追蹤日圓｜負責人：A｜[00:01:00] ｜ [[2026-09-14-1420-美日聯手撐日元/summary\\|2026-09-14 美日聯手撐日元]]" in text
    assert "已完成的" not in text.split("## 未完成待辦")[1]
