import pytest

from app.validation.gstin import check_char, is_valid_gstin, make_gstin, pan_from_gstin


def test_made_gstin_is_valid_and_embeds_pan():
    g = make_gstin("24", "ABCPX1234Q")
    assert len(g) == 15
    assert is_valid_gstin(g)
    assert pan_from_gstin(g) == "ABCPX1234Q"


def test_wrong_check_digit_is_invalid():
    g = make_gstin("27", "LMNCS4321K")
    wrong = g[:14] + ("0" if g[14] != "0" else "1")
    assert not is_valid_gstin(wrong)


@pytest.mark.parametrize("bad", ["", "24ABCPX1234Q1Z", "24abcpx1234q1z5", "2AABCPX1234Q1Z5"])
def test_bad_format_is_invalid(bad):
    assert not is_valid_gstin(bad)


def test_exactly_one_check_char_validates():
    first14 = "29QRSFD5678M2Z"  # synthetic prefix
    valid = [c for c in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ" if is_valid_gstin(first14 + c)]
    assert valid == [check_char(first14)]


def test_check_char_hand_computed():
    # 24AAAAA0000A1Z, weights 1,2,1,2...: values 2,4,10,10,10,10,10,0,0,0,0,10,1,35
    # products 2,8,10,20,10,20,10,0,0,0,0,20,1,70 -> folded 70 = 1+34 -> sum 2+8+10+20+10+20+10+20+1+35 = 136
    # check = (36 - 136 % 36) % 36 = (36 - 28) = 8
    assert check_char("24AAAAA0000A1Z") == "8"
