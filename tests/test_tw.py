from meeting_local.tw import fix_punct


def test_half_to_full_next_to_cjk():
    assert fix_punct("好,那就記一下,Eddy負責,9月18號前完成?") == "好，那就記一下，Eddy負責，9月18號前完成？"


def test_english_untouched():
    assert fix_punct("Vercel, GA4: ok? yes!") == "Vercel, GA4: ok? yes!"


def test_space_after_fullwidth_removed():
    assert fix_punct("第三, 繼續用Verso, 不搬主機。") == "第三，繼續用Verso，不搬主機。"


# ── s2twp 保護詞（2026-11-05：廣告會議「腳本」21 處全被改成「指令碼」）──
import pytest  # noqa: E402

from meeting_local.tw import to_tw  # noqa: E402


@pytest.mark.parametrize("src, want", [
    ("腳本", "腳本"),                    # 繁體輸入 s2twp 也會轉成「指令碼」
    ("这支视频脚本", "這支影片腳本"),
    ("这份文件", "這份文件"),
    ("法律程序", "法律程序"),
    ("点击率", "點擊率"),
    ("看数据", "看數據"),
    ("素材优化", "素材優化"),
])
def test_keep_words(src, want):
    assert to_tw(src) == want


@pytest.mark.parametrize("src, want", [
    ("程序员", "程式設計師"),             # 複合詞照常轉
    ("文件夹", "資料夾"),
    ("数据库", "資料庫"),
    ("视频", "影片"),                     # 其他大陸用語照常轉（s2tw 會漏的）
    ("软件", "軟體"),
    ("默认", "預設"),
])
def test_other_terms_still_converted(src, want):
    assert to_tw(src) == want
