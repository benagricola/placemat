"""The pin map study's constraints: pins named by number, by name or by a range of either; allow, deny, fixed and
groups; an entry naming a pin or a net the part lacks left out as a problem; which nets may move."""
from placemat.pinmap_rules import PinRules, Problem, part_pins, pin_numbers, read_rules

PADS = [(str(n), "N%d" % n) for n in range(1, 9)] + [("9", ""), ("10", "logic.SDA")]
NAMES = {str(n): "GPIO%d" % (n - 1) for n in range(1, 11)}         # pad 1 is GPIO0 ... pad 10 is GPIO9


def test_a_pin_is_named_by_number_by_name_or_by_a_range_of_either():
    numbers = {n for n, _ in PADS}
    assert pin_numbers(numbers, NAMES, "3") == (["3"], [])
    assert pin_numbers(numbers, NAMES, "GPIO4") == (["5"], [])
    assert pin_numbers(numbers, NAMES, "gpio4") == (["5"], [])
    assert pin_numbers(numbers, NAMES, "3-5") == (["3", "4", "5"], [])
    assert pin_numbers(numbers, NAMES, "GPIO1-GPIO3") == (["2", "3", "4"], [])
    assert pin_numbers(numbers, NAMES, "GPIO3-GPIO1") == (["4", "3", "2"], [])
    assert pin_numbers(numbers, NAMES, "GPIO8-GPIO11") == (["9", "10"], ["GPIO10", "GPIO11"])
    assert pin_numbers(numbers, NAMES, "SPI_CS") == ([], ["SPI_CS"])


def test_the_annotations_are_read_whatever_case_kicad_gave_the_key():
    rules, problems = read_rules("U1", {"Pm.Pinpool": "1-6", "Pm.Pinfixed": "GPIO0"}, PADS, NAMES)
    assert rules.pool == ("1", "2", "3", "4", "5", "6") and rules.fixed == {"1"} and problems == []


def test_a_part_without_a_pool_is_not_studied():
    assert read_rules("U1", {"Pm.PinFixed": "1"}, PADS, NAMES) == (None, [])


def test_a_pin_the_part_does_not_have_is_a_problem_and_the_rest_of_the_entry_stands():
    rules, problems = read_rules("U1", {"Pm.PinPool": "1-3, GPIO42"}, PADS, NAMES)
    assert rules.pool == ("1", "2", "3")
    assert problems == [Problem("U1", "Pm.PinPool", "GPIO42", "no_pin", "GPIO42")]


def test_allow_and_deny_name_nets_as_the_capture_does_and_a_net_the_part_lacks_is_a_problem():
    rules, problems = read_rules("U1", {"Pm.PinPool": "1-10", "Pm.PinAllow": "SDA:GPIO1-GPIO3; N4:4",
                                        "Pm.PinDeny": "N5:1,2; NOPE:3"}, PADS, NAMES)
    assert rules.allow == {"logic.SDA": frozenset({"2", "3", "4"}), "N4": frozenset({"4"})}
    assert rules.deny == {"N5": frozenset({"1", "2"})}
    assert problems == [Problem("U1", "Pm.PinDeny", "NOPE:3", "no_net", "NOPE")]


def test_a_group_must_lie_in_the_pool_off_the_fixed_pins_and_in_one_group_only():
    rules, problems = read_rules("U1", {"Pm.PinPool": "1-8", "Pm.PinFixed": "8", "Pm.PinGroup":
                                        "bus:2-4; late:4,5; out:9; strap:7-8; bad entry"}, PADS, NAMES)
    assert rules.groups == (("bus", ("2", "3", "4")),)
    assert [(p.entry, p.code, p.name) for p in problems] == [
        ("late:4,5", "two_groups", "4"), ("out:9", "not_in_pool", "9"), ("strap:7-8", "not_in_pool", "8"),
        ("bad entry", "unreadable", "bad entry")]


def test_pins_with_no_net_or_a_net_that_reaches_nothing_are_free_and_fixed_or_outside_nets_stay():
    rules = PinRules("U1", ("1", "2", "3", "4", "5", "6"), frozenset({"2"}))
    pads = [("1", "A", False), ("2", "B", False), ("3", "LONE", False), ("4", "", False), ("5", "C", True),
            ("6", "D", False), ("7", "E", False), ("8", "GND", False)]
    slots, problems = part_pins(rules, pads, connected={"A", "B", "C", "D", "E", "GND"}, quiet={"GND"})
    assert problems == [] and slots.movable == ("A", "D")
    assert slots.free == ("3", "4", "5")
    assert [(h.net, h.pin, h.why) for h in slots.held] == [("B", "2", "fixed")]
    assert slots.allowed == {"A": ("1", "3", "4", "5", "6"), "D": ("1", "3", "4", "5", "6")}


def test_a_net_allowed_only_its_own_pin_is_held_and_one_allowed_none_stops_the_part():
    rules = PinRules("U1", ("1", "2", "3"), allow={"A": frozenset({"1"})}, deny={"B": frozenset({"1", "2", "3"})})
    slots, problems = part_pins(rules, [("1", "A", False), ("2", "B", False)], {"A", "B"}, set())
    assert slots is None and problems == [Problem("U1", "Pm.PinDeny", "", "no_legal_pin", "B")]
    rules = PinRules("U1", ("1", "2", "3"), allow={"A": frozenset({"1"})})
    slots, _ = part_pins(rules, [("1", "A", False), ("2", "B", False)], {"A", "B"}, set())
    assert slots.movable == ("B",) and [(h.net, h.why) for h in slots.held] == [("A", "allow")]


def test_a_group_moves_to_runs_of_consecutive_pool_pins_its_nets_may_take():
    rules = PinRules("U1", ("1", "2", "3", "4", "5", "6"), frozenset({"4"}), allow={"Y": frozenset({"2", "3", "6"})},
                     groups=(("pair", ("1", "2")),))
    pads = [("1", "X", False), ("2", "Y", False), ("3", "Z", False)]
    slots, _ = part_pins(rules, pads, {"X", "Y", "Z"}, set())
    assert slots.groups == (("pair", ("X", "Y")),)
    assert slots.windows["pair"] == (("1", "2"), ("2", "3"), ("5", "6"))


def test_names_on_a_part_whose_pin_names_were_not_read_are_one_problem_per_entry_and_numbers_still_read():
    rules, problems = read_rules("U1", {"Pm.PinPool": "GPIO0-GPIO47, 3-4"}, PADS, {})
    assert rules.pool == ("3", "4")
    assert problems == [Problem("U1", "Pm.PinPool", "GPIO0-GPIO47", "no_names", "GPIO0-GPIO47")]


def test_a_net_on_two_pins_of_the_pool_stays_where_it_is():
    rules = PinRules("U1", ("1", "2", "3", "4"))
    slots, _ = part_pins(rules, [("1", "TIED", False), ("2", "TIED", False), ("3", "A", False)], {"TIED", "A"}, set())
    assert slots.movable == ("A",) and slots.free == ("4",)


def test_a_fixed_pin_with_no_net_is_neither_free_nor_allowed():
    rules = PinRules("U1", ("1", "2", "3"), frozenset({"2"}))
    slots, problems = part_pins(rules, [("1", "A", False), ("3", "B", False)], {"A", "B"}, set())
    assert problems == [] and slots.free == () and slots.allowed == {"A": ("1", "3"), "B": ("1", "3")}


def test_a_range_whose_ends_have_different_prefixes_is_no_pin():
    rules, problems = read_rules("U1", {"Pm.PinPool": "1-3, GPIO1-FOO3"}, PADS, NAMES)
    assert rules.pool == ("1", "2", "3")
    assert problems == [Problem("U1", "Pm.PinPool", "GPIO1-FOO3", "no_pin", "GPIO1-FOO3")]


def test_a_net_left_no_pin_by_another_held_on_its_only_one_names_that_net_and_pin():
    rules = PinRules("U1", ("1", "2"), allow={"A": frozenset({"1"}), "B": frozenset({"1"})})
    slots, problems = part_pins(rules, [("1", "A", False), ("2", "B", False)], {"A", "B"}, set())
    assert slots is None and len(problems) == 1
    assert problems[0] == Problem("U1", "", "", "no_legal_pin", "B", "A", "1")
    assert problems[0].facts() == {"ref": "U1", "key": "", "entry": "", "code": "no_legal_pin", "name": "B",
                                   "held_net": "A", "held_pin": "1"}
