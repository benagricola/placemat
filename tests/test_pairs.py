"""Differential pairs, named as the router pairs them (a port of
KiCadRoutingTools' net_queries.extract_diff_pair_base): the cases its
comments cite."""
from placemat.pairs import pair_key, pairs_of


def test_the_common_conventions_pair():
    assert pairs_of(["USB_P", "USB_N"]) == {"USB_P": "USB_N", "USB_N": "USB_P"}
    assert pairs_of(["CLK+", "CLK-"]) == {"CLK+": "CLK-", "CLK-": "CLK+"}
    assert pairs_of(["TXP", "TXN"]) == {"TXP": "TXN", "TXN": "TXP"}
    assert pairs_of(["USB_DP", "USB_DM"]) == {"USB_DP": "USB_DM", "USB_DM": "USB_DP"}
    assert pairs_of(["USB_DP", "USB_DN"]) == {"USB_DP": "USB_DN", "USB_DN": "USB_DP"}
    assert pairs_of(["CK_t", "CK_c"]) == {"CK_t": "CK_c", "CK_c": "CK_t"}
    assert pairs_of(["DQS0_t_A", "DQS0_c_A"]) == {"DQS0_t_A": "DQS0_c_A", "DQS0_c_A": "DQS0_t_A"}


def test_conventions_do_not_mix():
    assert pairs_of(["CLK+", "CLK_N"]) == {}


def test_kiCads_auto_names_pair_by_their_leaf():
    a, b = "Net-(U12-GPIO19/U1RTS/USB_D-)", "Net-(U12-GPIO20/U1CTS/USB_D+)"
    assert pairs_of([a, b]) == {a: b, b: a}


def test_indexed_pairs_pair_only_with_their_own_index():
    assert pairs_of(["CLK_P0", "CLK_N0", "CLK_P1"]) == {"CLK_P0": "CLK_N0", "CLK_N0": "CLK_P0"}


def test_what_is_not_a_pair():
    assert pair_key("GND") is None
    assert pair_key("WAKEn") is None            # a lowercase letter before the N
    assert pair_key("Net-(BZ1--)") is None       # a passive's '-' terminal
    assert pairs_of(["USB_P"]) == {}             # no partner
    assert pairs_of(["3V3-MCU", "VCC"]) == {}
