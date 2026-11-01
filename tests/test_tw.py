from meeting_local.tw import fix_punct


def test_half_to_full_next_to_cjk():
    assert fix_punct("好,那就記一下,Eddy負責,9月18號前完成?") == "好，那就記一下，Eddy負責，9月18號前完成？"


def test_english_untouched():
    assert fix_punct("Vercel, GA4: ok? yes!") == "Vercel, GA4: ok? yes!"


def test_space_after_fullwidth_removed():
    assert fix_punct("第三, 繼續用Verso, 不搬主機。") == "第三，繼續用Verso，不搬主機。"
