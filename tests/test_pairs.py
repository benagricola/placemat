"""Differential pairs, named as the router pairs them (a port of
KiCadRoutingTools' net_queries.extract_diff_pair_base): the cases its
comments cite."""
from placemat.board_geometry import NetClass
from placemat.pairs import board_pair_list, board_pairs, pair_key, pairs_of


def _cls(name, nets, width=0.1, gap=0.1):
    return {n: NetClass(name, 0.2, 0.2, 0.6, 0.3, width, gap) for n in nets}


def test_a_two_net_class_pairs_whatever_they_are_called():
    assert board_pairs(_cls("Tank", ["LX", "LY"])) == {"LX": "LY", "LY": "LX"}


def test_a_four_net_class_pairs_by_pair_key():
    classes = _cls("HighSpeed", ["CLK_P", "CLK_N", "DAT_P", "DAT_N"])
    assert board_pairs(classes) == {"CLK_P": "CLK_N", "CLK_N": "CLK_P", "DAT_P": "DAT_N", "DAT_N": "DAT_P"}


def test_the_default_class_never_makes_pairs():
    classes = {"A": NetClass("Default", 0.2, 0.2, 0.6, 0.3, 0.2, 0.2),
              "B": NetClass("Default", 0.2, 0.2, 0.6, 0.3, 0.2, 0.2)}
    assert board_pairs(classes) == {}


def test_a_board_with_no_pair_class_has_none():
    classes = {"A": NetClass("Default", 0.2, 0.2, 0.6, 0.3), "B": NetClass("Power", 0.3, 0.2, 0.6, 0.3)}
    assert board_pairs(classes) == {}


def test_board_pair_list_gives_each_pair_once_p_first():
    assert board_pair_list(_cls("HighSpeed", ["CLK_P", "CLK_N"])) == [("CLK_P", "CLK_N")]
    assert board_pair_list(_cls("Tank", ["LX", "LY"])) == [("LX", "LY")]   # no suffix meaning: alphabetically first is P


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


def test_patterns_select_which_pairs_count():
    """As the router selects pairs (net_queries.matches_diff_pair_patterns): a
    pattern matching either half, its leaf, or the pair's base selects it."""
    nets = ["USB_D_P", "USB_D_N", "XTAL_P", "XTAL_N"]
    assert pairs_of(nets, patterns=("USB_D*",)) == {"USB_D_P": "USB_D_N", "USB_D_N": "USB_D_P"}
    assert pairs_of(nets, patterns=("*_N",)) == pairs_of(nets)          # one half selects the pair
    assert pairs_of(nets, patterns=("XTAL",)) == {"XTAL_P": "XTAL_N", "XTAL_N": "XTAL_P"}   # the base
    assert pairs_of(["/usb/D_P", "/usb/D_N"], patterns=("D_P",)) == {"/usb/D_P": "/usb/D_N", "/usb/D_N": "/usb/D_P"}
    assert pairs_of(nets, patterns=()) == {}


def test_a_two_net_class_pairs_outright_whatever_its_names():
    from placemat.board_geometry import NetClass
    from placemat.pairs import board_pairs
    classes = {"CLK_MAIN": NetClass("Fast", 0.2, 0.15, 0.45, 0.2, 0.1, 0.1),
               "CLK_RETURN": NetClass("Fast", 0.2, 0.15, 0.45, 0.2, 0.1, 0.1)}
    assert board_pairs(classes) == {"CLK_MAIN": "CLK_RETURN", "CLK_RETURN": "CLK_MAIN"}


def test_a_four_net_class_pairs_by_pair_key():
    from placemat.board_geometry import NetClass
    from placemat.pairs import board_pairs
    cls = NetClass("Fast", 0.2, 0.15, 0.45, 0.2, 0.1, 0.1)
    classes = {n: cls for n in ("USB_D_P", "USB_D_N", "SPARE_P", "SPARE_N")}
    assert board_pairs(classes) == {
        "USB_D_P": "USB_D_N", "USB_D_N": "USB_D_P", "SPARE_P": "SPARE_N", "SPARE_N": "SPARE_P"}


def test_the_default_class_never_makes_pairs():
    from placemat.board_geometry import NetClass
    from placemat.pairs import board_pairs
    classes = {"A": NetClass("Default", 0.16, 0.16, 0.45, 0.2, 0.2, 0.2),
               "B": NetClass("Default", 0.16, 0.16, 0.45, 0.2, 0.2, 0.2)}
    assert board_pairs(classes) == {}


def test_a_class_with_no_diff_pair_values_makes_no_pairs():
    from placemat.board_geometry import NetClass
    from placemat.pairs import board_pairs
    classes = {"A": NetClass("50Ohm SE", 0.14, 0.2, 0.45, 0.2), "B": NetClass("50Ohm SE", 0.14, 0.2, 0.45, 0.2)}
    assert board_pairs(classes) == {}


def test_no_pair_class_at_all_makes_no_pairs():
    from placemat.pairs import board_pairs
    assert board_pairs({}) == {}


def test_board_pair_list_gives_each_pair_once_p_first():
    from placemat.board_geometry import NetClass
    from placemat.pairs import board_pair_list
    classes = {n: NetClass("Fast", 0.2, 0.15, 0.45, 0.2, 0.1, 0.1) for n in ("CLK_P", "CLK_N")}
    assert board_pair_list(classes) == [("CLK_P", "CLK_N")]
    classes2 = {n: NetClass("Tank", 0.2, 0.15, 0.45, 0.2, 0.1, 0.1) for n in ("LY", "LX")}
    assert board_pair_list(classes2) == [("LX", "LY")]   # no suffix meaning: alphabetically first
