import pytest

from gnj_nudge.limits import Form, check


def test_every_placeholder_card_says_it_is_a_placeholder(cards):
    assert set(cards) == {"bend_ratio", "min_lamella", "stock_thickness", "stock_width", "length"}
    assert {c.source for c in cards.values()} == {"placeholder"}


def test_solid_at_exactly_7600_mm_passes(cards):
    # 38 mm x 200 = 7600 mm: the boundary itself is buildable.
    assert check(Form(7600, 1, 38, 2400), cards).passed


def test_solid_at_7599_mm_fails_the_bend_ratio_and_says_by_how_much(cards):
    r = check(Form(7599, 1, 38, 2400), cards)
    assert not r.passed
    [fail] = r.failures
    assert fail.id == "bend_ratio"
    assert fail.measured == pytest.approx(7599 / 38)
    assert fail.by == pytest.approx(200 - 7599 / 38)
    assert fail.by > 0


def test_lamella_of_exactly_8_mm_passes_the_thinnest_lamella_card(cards):
    # 8 mm layers cannot fill 38 mm stock evenly, so judge this card on its own.
    assert check(Form(1600, 4, 8, 2400), cards).card("min_lamella").passed


def test_lamella_just_under_8_mm_fails_the_thinnest_lamella_card(cards):
    r = check(Form(7600, 5, 7.6, 2400), cards)  # 5 x 7.6 = 38 and ratio 1000: only the lamella is wrong
    assert [f.id for f in r.failures] == ["min_lamella"]
    assert r.card("min_lamella").by == pytest.approx(0.4)


def test_make_up_that_does_not_fill_the_stock_fails(cards):
    r = check(Form(2450, 3, 9.5, 2400), cards)
    assert [f.id for f in r.failures] == ["stock_thickness"]
    assert r.card("stock_thickness").measured == pytest.approx(28.5)


def test_span_at_member_length_passes_and_one_mm_over_fails(cards):
    assert check(Form(7600, 1, 38, 2400), cards).passed
    r = check(Form(7600, 1, 38, 2401), cards)
    assert [f.id for f in r.failures] == ["length"]


@pytest.mark.parametrize("kw", [
    dict(radius_mm=0, n_lamellas=1, lamella_mm=38, chord_mm=2400),
    dict(radius_mm=2450, n_lamellas=0, lamella_mm=38, chord_mm=2400),
    dict(radius_mm=2450, n_lamellas=2.0, lamella_mm=19, chord_mm=2400),
    dict(radius_mm=1000, n_lamellas=1, lamella_mm=38, chord_mm=2400),  # tighter than half the span
    dict(radius_mm=float("nan"), n_lamellas=1, lamella_mm=38, chord_mm=2400),
])
def test_impossible_forms_are_refused_at_construction(kw):
    with pytest.raises(ValueError):
        Form(**kw)
