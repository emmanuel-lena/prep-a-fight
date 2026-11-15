"""The tool result pages (paf.workshop_views): what each one says and how it draws it."""

from paf import theme
from paf import workshop_views as wv


def test_a_list_with_no_loss_draws_its_bars_from_the_left_edge():
    assert "class='gbar u'" in wv._bar(1.0, 2.0, signed=False) and "width:50.0%" in wv._bar(1.0, 2.0, signed=False)
    assert "class='gbar'" in wv._bar(-1.0, 2.0) and "width:25.0%" in wv._bar(-1.0, 2.0)
    page = wv.render({"kind": "loot", "error": 0.1, "ilvl": 300, "bosses": ["A", "B"], "rows": [
        {"name": "Ring", "slot": "finger1", "boss": "A", "gain": 1.0, "item_id": 0}], "ev": [
        {"boss": "A", "ev": 0.2, "n": 1}, {"boss": "B", "ev": 0.1, "n": 1}]})
    assert "class='gbar'>" not in page and page.count("gbar u") == 3  # the farm list and "which boss is worth it"
    assert "Ring 1" in page  # a slot as the game says it, not "finger1"


def test_the_class_colour_never_encodes_a_state():
    css = theme.style("workshop-views")
    assert "var(--accent)" not in css  # the Class Signs Rule: covered, ready, put on it... are neutral


def test_enchants_read_slot_by_slot_what_to_put_on():
    # a fresh review (2026-11-15): a check mark on 2 rows of 21 said neither what you wear nor what to put
    page = wv.enchant_table({"error": 0.2, "rows": [
        {"kind": "enchant", "slot": "feet", "name": "Small", "id": 1, "share": 0.2, "gain": 0.1, "pick": False},
        {"kind": "enchant", "slot": "finger1", "name": "Mine", "id": 4, "share": 0.5, "gain": 0, "pick": False},
        {"kind": "enchant", "slot": "finger1", "name": "Real", "id": 2, "share": 0.2, "gain": 0.9, "pick": True},
        {"kind": "gem", "slot": "", "name": "Pick", "id": 3, "share": 0.6, "gain": 0.6, "pick": True}]})
    assert page.index("Real") < page.index("Pick")  # the biggest gain first
    assert "<s>Mine</s> &rarr; " in page and "Ring 1" in page and "finger1" not in page
    assert "Keep yours: Feet" in page and "Small" not in page  # within the noise: kept, not listed


def test_rotation_leaves_out_a_cooldown_pressed_as_often_as_the_top_players_press_it():
    d = {"kind": "rotation", "player": "P", "spec": "", "boss": "B", "pull": "pull 1", "duration": 200,
         "highlights": ["Sprint: you pressed it 1 time, it was ready 3 times in the pull.",
                        "Burst: you pressed it 1 time, it was ready 3 times in the pull."],
         "cooldowns": [{"name": n, "casts": 1, "possible": 3, "cooldown": 60, "times": [5]}
                       for n in ("Sprint", "Burst")],
         "findings": [{"kind": "cooldown", "name": "Sprint", "tops": "the top players of your spec press it 0.8 times "
                                                                     "in a pull this long"},
                      {"kind": "cooldown", "name": "Burst", "tops": "the top players of your spec press it 2.9 times "
                                                                    "in a pull this long"}],
         "buffs": [{"name": "Proc", "player": 0.59, "tops": 0.37}]}
    page = wv.render(d)
    assert "Sprint: you pressed" not in page and "Burst: you pressed" in page  # the tops press Sprint as rarely
    assert "class='verdict ok'" in page and "<small>you</small> 59%" in page and "your spec:</span> 37%" in page


def _pull(boss, kill, deaths):
    players = {n: {"deaths": [t] if t is not None else [], "healthstone": [], "health": [], "damage": [1.0],
                   "bare": t is not None} for n, t in deaths.items()}
    return {"boss": boss, "kill": kill, "duration": 120.0, "left": None if kill else 0.84, "players": players}


def _night(pulls):
    names = {n for p in pulls for n in p["players"]}
    summary = {n: {"deaths": 1, "bare": 1, "healthstone": 0, "health": 0, "damage": 2,
                   "pulls_damage_potion": len(pulls)} for n in names}
    return wv.render({"kind": "night", "pulls": pulls, "summary": summary, "icons": {}})


def test_night_cards_are_numbered_pulls_with_their_first_death_marked():
    page = _night([_pull("Boss", False, {"Aa": 40.0, "Bb": 40.5, "Cc": 70.0}), _pull("Boss", True, {"Aa": None})])
    assert "<b>Pull 1</b>" in page and "<b>Pull 2</b>" in page and "&middot; Boss" not in page  # one boss
    assert "wipe at</span> <span class='num'>84%" in page and "class='kill'>Kill<" in page
    assert page.count("who-chip bare first") == 2 and "who-chip bare'>" in page  # Aa and Bb in the same second
    assert "class='pill'" not in page and "who-c bad" not in page and "<h3>Pull by pull (2)</h3>" in page
    assert "died without a healthstone or a health potion first" in page  # the red chip said in sight
    page = _night([_pull("Boss", False, {"Aa": 40.0}), _pull("Other", True, {"Aa": None})])
    assert "Pull 2 &middot; Other" in page  # two bosses in the night: each card names its boss


def _diff(abilities):
    pl = {"name": "Me", "icon": "", "boss_a": 100e3, "boss_b": 120e3, "dps_a": 100e3, "dps_b": 120e3,
          "active_a": 0.9, "active_b": 0.95, "abilities": abilities, "consumables": {}, "deaths": [[], []],
          "casts": [{"name": "Burst", "a": 0.4, "b": 0.8, "cooldown": True, "times_a": [104.0], "times_b": []},
                    {"name": "Dash", "a": 0.4, "b": 0.0, "cooldown": True, "times_a": [5.0], "times_b": []}],
          "buffs": [{"name": "Proc", "a": 0.8, "b": 0.1}]}
    return wv.render({"kind": "diff", "boss": "Boss", "a": {"label": "wipe A", "duration": 150.0},
                      "b": {"label": "wipe B", "duration": 150.0}, "highlights": [],
                      "curves": {"a": [1.0, 0.9, 0.8], "b": [1.0, 0.85, 0.66]}, "player": pl})


def test_two_pulls_with_other_talents_lead_with_the_build():
    page = _diff([{"name": "New Strike", "a": 0, "b": 20e3}, {"name": "Old Strike", "a": 15e3, "b": 0},
                  {"name": "Tiny", "a": 0, "b": 1e3}, {"name": "Both", "a": 50e3, "b": 60e3}])
    assert "Me: other talents in pull B" in page and "New Strike</b> <span>instead of</span> <s>Old Strike</s>" in page
    assert "Tiny</b>" not in page and "the gap is gameplay" not in page and "not only gameplay" in page
    assert "class='verdict ok'" in page and "On the bosses" not in page  # all of it on the boss: one tile
    assert "<span class='pab-s a'>A</span> 1:44 &middot; <span class='pab-s b'>B</span> 2&times;" in page
    assert "<span class='pab-s b'>B</span> &ndash;" in page and ">&minus;70 pts</td>" in page
    assert ">60%</text>" in page and ">50%</text>" not in page  # the y axis from the 10% under the lowest point
    assert ">0:30</text>" in page  # 30 s ticks under 5 min
    page = _diff([{"name": "Both", "a": 50e3, "b": 60e3}])
    assert "pull B next to pull A" in page and "the gap is gameplay" in page


def test_review_names_the_players_with_nothing_to_do_in_sight():
    def player(name, verdict):
        return {"name": name, "spec": "Rogue-Subtlety", "verdict": verdict, "target": "Boss",
                "shares": {"Boss": 0.9}, "habit": {"Boss": 0.9}}
    page = wv.render({"kind": "review", "fight": "Boss, kill of 5:00", "targets": [
        {"name": "Boss", "main": True, "covered": True, "raid": 0.9, "tops": 0.9}],
        "players": [player("Aa", "ok"), player("Bb", "unknown")]})
    assert "<details" not in page and "Play like the top players of their spec (1)" in page
    assert "<b>Aa</b>" in page and "Not measured (1)" in page


def test_specgear_shows_your_sim_your_kill_and_the_tops_and_points_to_the_gear_tool():
    rows = [{"spec": "Sub", "label": "Subtlety", "sim": 180e3, "tops": 232e3, "error": 0.1},
            {"spec": "Out", "label": "Outlaw", "sim": 170e3, "tops": 218e3, "error": 0.1}]
    page = wv.render({"kind": "specgear", "mine": "Sub", "verdict": "ok", "title": "Stay Subtlety", "rows": rows,
                      "now": 160e3, "kills": {"best": 162e3, "median": 150e3, "n": 1},
                      "gear_sentence": "The top players' gear is worth +12.5%."})
    assert "Stay Subtlety" in page and "<b>160k</b>" in page and "<b>162k</b>" in page and "<b>232k</b>" in page
    assert "href='/tool/gear'" in page and "101% of your sim" in page


def _talents_row(code, gain, swaps, players=3):
    return {"code": code, "gain": gain, "players": players, "swaps": swaps}


def test_a_build_within_the_noise_says_same_without_a_copy_button():
    a, b = ["Ethereal Cloak", 0], ["Bait and Switch", 0]
    page = wv.render({"kind": "talents", "error": 0.1, "boss": "X", "rows": [
        _talents_row("MINE", 0, []), _talents_row("NOISE", 0.1, [[a, b], [a, b]]),
        _talents_row("WORSE", -2.0, [[b, a]])]})
    assert "l-val same'>same<" in page and "data-copy='NOISE'" not in page
    assert "data-copy='WORSE'" not in page  # a build that loses: nothing to copy
    assert page.count("Ethereal Cloak") == 2  # a pair listed twice is said once (and once in the worse build)


def test_the_best_build_is_said_once_in_the_verdict():
    swap = [["Dark Shadow", 0], ["Potent Powder", 0]]
    page = wv.render({"kind": "talents", "error": 0.1, "boss": "X", "rows": [
        _talents_row("MINE", 0, []), _talents_row("BEST", 3.0, [swap])]})
    assert "Change 1 talent" in page and page.count("data-copy='BEST'") == 1 and "other builds" not in page


def test_gear_by_target_count_says_nothing_to_change_and_gives_a_long_build_the_width():
    many = [[[f"Old {i}", 0], [f"New {i}", 0]] for i in range(8)]
    page = wv.by_targets({"length": 120, "counts": [
        {"label": "1 target", "talents": None, "gear": {"error": 0.2, "rows": []}},
        {"label": "3+ targets", "gear": {"error": 0.2, "rows": []}, "talents": {
            "label": "top players on Some Boss", "players": 5, "code": "AOE", "gain": 2.8, "hero": None,
            "swaps": many}}]})
    assert "Nothing to change at 1 target." in page and "Talents</b><span class='bt-keep'>" not in page
    assert "Copy this build, +2.8%" in page and "a build the top players play on Some Boss" in page
    assert "bt-card wide" in page and "has-wide" in page
    assert page.index(">Take<") < page.index("New 0") < page.index(">Drop<") < page.index("Old 0")
