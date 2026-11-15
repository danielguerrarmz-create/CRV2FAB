import pytest

from conftest import intent
from gnj_nudge.intent import Holds, hold_violations
from gnj_nudge.limits import check
from gnj_nudge.solver import solve


def test_2450_mm_keeps_the_curve_and_laminates_four_layers_of_9_5(cards):
    r = solve(intent(2450), Holds(), cards)
    assert r.status == "proposed"
    assert (r.form.n_lamellas, r.form.lamella_mm, r.form.radius_mm) == (4, 9.5, 2450)
    assert r.deviation_mm == 0
    assert r.sentence == "Your curve holds. Made from 4 glued layers in place of one solid piece."


def test_7600_mm_is_buildable_as_drawn_in_solid(cards):
    r = solve(intent(7600), Holds(), cards)
    assert (r.form.n_lamellas, r.form.radius_mm, r.deviation_mm) == (1, 7600, 0)
    assert r.sentence == "Buildable as drawn, in one solid piece."


def test_7599_mm_changes_the_make_up_before_the_shape(cards):
    r = solve(intent(7599), Holds(), cards)
    assert (r.form.n_lamellas, r.form.lamella_mm, r.deviation_mm) == (2, 19, 0)


def test_hold_solid_and_hold_shape_on_a_tight_radius_is_a_named_conflict(cards):
    r = solve(intent(2450), Holds(["solid", "shape"]), cards)
    assert r.status == "conflict"
    assert r.form is None
    assert r.conflict == ("solid section", "drawn radius 2.45 m")
    assert r.steps[-1]["tag"] == "Cannot resolve"


def test_hold_solid_opens_the_radius_to_the_solid_limit(cards):
    r = solve(intent(2450), Holds(["solid"]), cards)
    assert (r.form.n_lamellas, r.form.radius_mm) == (1, 7600)
    assert r.deviation_mm > 0
    assert r.sentence.startswith("Kept solid. Curve eased by ")


def test_too_tight_for_the_thinnest_layer_moves_the_shape_last(cards):
    r = solve(intent(1500), Holds(), cards)
    assert (r.form.n_lamellas, r.form.lamella_mm, r.form.radius_mm) == (4, 9.5, 1900)
    assert r.deviation_mm > 0
    assert r.governing == ["bend_ratio", "min_lamella"]


def test_hold_shape_on_a_curve_too_tight_for_any_layer_is_a_named_conflict(cards):
    r = solve(intent(1500), Holds(["shape"]), cards)
    assert r.status == "conflict"
    assert r.conflict == ("drawn radius 1.50 m", "thinnest lamella 8 mm")


def test_span_longer_than_the_member_is_a_conflict(cards):
    r = solve(intent(7600, chord_mm=2401), Holds(), cards)
    assert r.status == "conflict"
    assert r.conflict[1] == "member length 2.40 m"


@pytest.mark.parametrize("holds", [[], ["solid"], ["shape"], ["solid", "shape"]])
@pytest.mark.parametrize("radius", [1200, 1500, 1899, 1900, 1901, 2450, 2533.3333333, 3800, 5000, 7599, 7600, 20000])
def test_every_solver_proposal_passes_the_checker_and_keeps_its_holds(cards, radius, holds):
    i, h = intent(radius), Holds(holds)
    r = solve(i, h, cards)
    if r.status == "proposed":
        assert check(r.form, cards).passed
        assert hold_violations(r.form, i, h) == []
    else:
        assert r.conflict and len(r.conflict) == 2
