from pytest import approx

from paf import review, simple
from paf.prep_report import PrepData


def test_busy_time_from_casts():
    # a 2 s cast, then instants every 1.1 s, then 6 s idle, then a cast
    casts = [("begincast", 1, 0.0), ("cast", 1, 2.0)] + [("cast", 2, 2.0 + 1.1 * i) for i in range(1, 5)]
    casts += [("begincast", 1, 12.0), ("cast", 1, 14.0)]
    spans = review.busy(casts)
    assert review.gcd([c[2] for c in casts if c[0] != "cast" or c[1] == 2]) == approx(1.1)
    assert [approx(s) for s in spans] == [(0.0, 2.0), (3.1, 7.5), (12.0, 14.0)]
    assert review.share(spans, 0, 14) == approx((2 + 4.4 + 2) / 14)
    assert review.idle_gaps(spans, 14) == [approx((7.5, 4.5))]


def test_card_says_what_differs():
    d = PrepData("Boss", "mythic", "Elemental", "Char", duration=400)
    d.review = review.Review("kill of 6:40", 0.79, 0.87, 0.58, 0.52,
                             [review.PhaseReview("Stage One", 0.84, 0.89, 0.47, 0.46),
                              review.PhaseReview("Intermission", 0.71, 0.85, 0.69, 0.53)], [(262.0, 7.4)])
    card = simple.review_card(d)
    assert "You cast 32 s less than the top players over the fight, above all in Intermission" in card
    assert "You move more than them in Intermission (69% of the phase, top players 53%)" in card
    assert "4:22 &middot; 7 s" in card and "bar you worse" in card
    d.review = review.Review("kill of 6:40", 0.87, 0.87, 0.5, 0.52, [], [])
    card = simple.review_card(d)
    assert "You keep casting like the top players do." in card and "You do not move more" in card
    d.review = None
    assert simple.review_card(d) == ""
