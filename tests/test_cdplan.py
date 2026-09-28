from paf.cdplan import Plan, apl_lines, parse_apl, plan_lines, split_if, standard_plans, windows_condition

APL = """actions.precombat=snapshot_stats
actions=potion,if=buff.bloodlust.up
actions+=/call_action_list,name=single_target
actions.single_target=stormkeeper,if=cooldown.ascendance.remains>10
actions.single_target+=/ascendance,if=set_bonus.mid2_4pc|fight_remains<20
actions.single_target+=/lightning_bolt
"""


def test_parse_and_roundtrip():
    apl = parse_apl(APL)
    assert list(apl) == ["precombat", "", "single_target"]
    assert apl["single_target"][1].startswith("ascendance,")
    assert apl_lines(apl)[1] == "actions=potion,if=buff.bloodlust.up"


def test_split_if():
    assert split_if("ascendance,if=a|b") == ("ascendance", "a|b")
    assert split_if("lightning_bolt") == ("lightning_bolt", None)


def test_plan_lines_only_redefines_changed_lists():
    apl = parse_apl(APL)
    lines = plan_lines(apl, Plan("x", "", {"ascendance": lambda old: f"({old})&raid_event.adds.in>25"}))
    assert lines[0] == "actions.single_target=stormkeeper,if=cooldown.ascendance.remains>10"
    assert lines[1] == ("actions.single_target+=/ascendance,"
                        "if=(set_bonus.mid2_4pc|fight_remains<20)&raid_event.adds.in>25")
    assert not any(line.startswith("actions=") for line in lines)


def test_standard_plans_time_only_long_cooldowns():
    plans = {p.name for p in standard_plans({"ascendance": [5, 130], "stormkeeper": [3, 60]}, {"ascendance"})}
    assert {"default", "on_cooldown", "hold_for_adds", "top_timings", "top_timing_ascendance"} <= plans
    assert "top_timing_stormkeeper" not in plans
    assert windows_condition([130]) == "time>=127&time<=142"
