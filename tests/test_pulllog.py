from paf import pulllog

W = "Player 'Lock'"
LOG = f"""0.000 {W} performs Action 'demonbolt' (264178) (250000)
0.000 Lock gains 2.00 (2.00) soul_shard from demonbolt (5.00/5.00)
2.297 {W} schedules execute for Action 'grimoire_imp_lord' (1276452)
2.297 {W} performs Action 'grimoire_imp_lord' (1276452) (250000)
2.297 {W} consumes 1 soul_shard for Action 'grimoire_imp_lord' (1276452) (4)
2.297 {W} summons grimoire_imp_lord for 20.000s.
3.112 {W} schedules execute for Action 'call_dreadstalkers' (104316)
3.112 {W} performs Action 'call_dreadstalkers' (104316) (250000)
3.112 {W} performs Action 'call_dreadstalkers_summon_1' (193331) (250000)
3.112 {W} summons dreadstalker for 12.264s.
3.112 Player 'Lock_dreadstalker' schedules execute for Action 'leap' (0)
4.788 {W} performs Action 'shadow_bolt' (686) (250000)
4.788 Lock gains 1.00 (1.00) soul_shard from shadow_bolt (5.00/5.00)
4.794 {W} schedules execute for Action 'summon_demonic_tyrant' (265187)
5.575 {W} performs Action 'summon_demonic_tyrant' (265187) (246265)
5.575 {W} gains Buff 'tyrant' (265187) (stacks=1) (value=1)
5.580 {W} schedules execute for Action 'hand_of_guldan' (105174)
6.330 {W} performs Action 'hand_of_guldan' (105174) (250000)
6.330 {W} consumes 3 soul_shard for Action 'hand_of_guldan' (105174) (2)
30.000 {W} schedules execute for Action 'shadow_bolt' (686)
31.000 {W} schedules execute for Action 'demonbolt' (264178)
31.000 {W} loses Buff 'tyrant' (265187)
"""
ACTIONS = {"demonbolt", "grimoire_imp_lord", "call_dreadstalkers", "shadow_bolt", "summon_demonic_tyrant",
           "hand_of_guldan"}
CDS = {1276452: (120.0,), 265187: (60.0,), 104316: (20.0,)}


def _pull(tmp_path):
    log = tmp_path / "pull.log"
    log.write_text(LOG)
    return pulllog.read(log, ACTIONS)


def test_the_tyrant_s_shards_and_what_is_up_when_it_is_cast(tmp_path):
    pull = _pull(tmp_path)
    by = {x.action: x for x in pull.presses}
    assert pull.resource == "shards"
    tyrant = by["summon_demonic_tyrant"]
    assert tyrant.res == 5 and tyrant.up == [1276452, 104316]  # the Imp Lord, the dogs (not the summon's own action)
    assert by["hand_of_guldan"].spends and by["hand_of_guldan"].res == 5 and not tyrant.spends
    assert by["hand_of_guldan"].up == [1276452, 104316, 265187]  # the Tyrant's buff until it fades


def test_a_summon_ends_with_its_duration_a_buff_when_it_fades(tmp_path):
    late = {x.t: x for x in _pull(tmp_path).presses}
    assert late[30.0].up == [265187]  # the dogs gone after 12 s, the Imp Lord after 20; the Tyrant up
    assert late[31.0].up == [265187]  # the buff fades on a later line at the same second


def test_burst_split_says_what_is_pressed_in_the_cooldowns_and_between(tmp_path):
    sp = pulllog.burst_split(_pull(tmp_path), CDS, window=20.0)
    inside = {a for _s, a, _c in sp.inside}
    outside = {a for _s, a, _c in sp.outside}
    assert "hand_of_guldan" in inside and "call_dreadstalkers" in inside
    assert "demonbolt" in outside and not inside & outside
    assert 0 < sp.share < 1


def test_no_log_no_notes(tmp_path):
    assert pulllog.notes(tmp_path / "none.log", ACTIONS, set(), 40.0) is None
