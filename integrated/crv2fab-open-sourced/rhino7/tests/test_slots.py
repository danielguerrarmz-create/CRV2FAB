# -*- coding: utf-8 -*-
"""SPEC_V9_CARD_SLOTS: the fixed-slot card's words, mapped client side from the core's sentences.

Pure, no Rhino. IronPython 2.7 and CPython. Every mapped answer obeys the slot limits and carries
no number in its Reason; an unknown sentence falls back to the core's own words."""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import gnj_core as core  # noqa: E402
import gnj_slots as slots  # noqa: E402

with open(os.path.join(HERE, "fixtures", "plate_bodies.json")) as _fh:
    BODIES = json.load(_fh)["bodies"]


def res(sentence, status="proposed", dev=0.0, waste=33.0, form=None):
    return {"status": status, "sentence": sentence, "deviation_mm": dev, "waste_pct": waste,
            "form": {} if status == "proposed" else None,
            "sent": {"status": status, "sentence": sentence, "form": form, "deviation_mm": dev}}


def lim(t, what):
    assert len(t) <= what, (t, len(t), what)


PLATE_FORM = {"kind": "plate_member", "n_lamellas": 3, "lamella_mm": 38.0}
PIECES_FORM = {"kind": "plate_member", "n_lamellas": 3, "pieces": [{}, {}]}


class Proposed(unittest.TestCase):
    def one(self, sentence, kind="plate", dev=0.0, waste=33.0, form=PLATE_FORM, word="shape"):
        return slots.map_proposal(res(sentence, dev=dev, waste=waste, form=form), kind, word, [])

    def test_kept_as_drawn(self):
        cases = [
            ("Your shape holds. Pressed in one curve from 3 layers, then milled to shape.", "Pressed in one curve, then milled."),
            ("Your shape holds. Glued straight from 3 layers, then milled to shape.", "Glued straight from layers, then milled."),
            ("Your shape holds. Milled from one straight piece, no bending.", "Milled from one straight piece."),
            ("Your shape holds, in 2 pieces joined end to end. Each pressed from layers, then milled.",
             "Made in pieces joined end to end."),
            ("Your shape holds. One stock 2x4, no pressing.", "One piece as it comes, no pressing."),
            ("Buildable as drawn. One piece as it comes, no pressing.", "One piece as it comes, no pressing."),
        ]
        for sentence, reason in cases:
            m = self.one(sentence)
            self.assertEqual((m["verdict"], m["reason"], m["mapped"]), (slots.AS_DRAWN, reason, True), sentence)

    def test_a_surface_line_and_a_part(self):
        m = self.one("Your line holds. Pressed in one curve from 3 layers, then milled to shape.", "surface", word="line")
        self.assertEqual((m["verdict"], m["reason"]), ("Buildable as drawn.", "Pressed in one curve, then milled."))
        m = self.one("Buildable as modelled. Pressed in one curve from 3 layers, then milled to shape.", "part", form={})
        self.assertEqual((m["verdict"], m["reason"]), ("Buildable as modelled.", "Pressed in one curve, then milled."))
        m = self.one("Buildable as modelled, in 2 pieces joined end to end. Each pressed from layers, then milled.", "part",
                     form={"kind": "part_plan", "pieces": [{}, {}]})
        self.assertEqual((m["verdict"], m["reason"]), ("Buildable as modelled.", "Made in pieces joined end to end."))

    def test_eased_plate_names_what_and_why_and_the_number_goes_to_facts(self):
        m = self.one("Path straightened so the layers can bend, moving the plate at most 331 mm.", dev=330.8)
        self.assertEqual((m["verdict"], m["reason"]), ("Buildable, eased.", "Path straightened so the layers can bend."))
        self.assertEqual(m["facts"], "Waste 33%  Moved 331 mm  Needs 3 layers")
        m = self.one("Twist and profiles eased so the billet fits the machine, moving the plate at most 215 mm.", dev=215.2)
        self.assertEqual(m["reason"], "Twist and profiles eased so it fits the machine.")
        m = self.one("Twist, profiles and path drift eased so the billet runs along the grain, moving the member at most 90 mm.",
                     dev=90.0)
        self.assertEqual(m["reason"], "Twist, profiles and path drift eased so it runs along the grain.")
        self.assertEqual(m["verdict"], "Buildable, eased.")

    def test_eased_surface_line(self):
        for sentence, reason in (
                ("Line straightened by 120 mm so it mills from one straight piece.", "Line straightened so it mills from one straight piece."),
                ("Line straightened by 120 mm so the layers can bend, 3 layers, then milled.", "Line straightened so the layers can bend."),
                ("Line straightened by 120 mm so the billet fits the machine.", "Line straightened so the billet fits the machine.")):
            m = self.one(sentence, "surface", dev=120.0, word="line")
            self.assertEqual((m["verdict"], m["reason"], m["mapped"]), ("Buildable, eased.", reason, True))
            self.assertIn("Moved 120 mm", m["facts"])

    def test_over_target_and_trim(self):
        m = self.one("Your shape holds, in 2 pieces joined end to end. Each pressed from layers, then milled. "
                     "Waste 52%, over your 40% target.", form=PIECES_FORM, waste=52.0)
        self.assertEqual((m["verdict"], m["reason"]), (slots.AS_DRAWN, "Made in pieces joined end to end."))
        self.assertEqual(m["facts"], "Waste 52%, over target  Needs 2 pieces")
        m = self.one("Your line holds. Milled from one straight piece, no bending. Kept to the 2.4 m stock length.", "surface",
                     word="line")
        self.assertEqual((m["reason"], m["echo"]), ("Milled from one straight piece.", "Kept to the timber length."))

    def test_facts_order_and_what_is_hidden(self):
        m = self.one("Your shape holds. One stock 2x4, no pressing.", waste=0.0, form={"kind": "plate_member", "n_lamellas": 1,
                                                                                    "billet": {"mode": "stock"}})
        self.assertEqual(m["facts"], "Waste 0%  Needs 1 piece")   # Moved hidden at 0
        m = self.one("Your shape holds. Milled from one straight piece, no bending.", waste=12.4,
                     form={"kind": "plate_member", "straight_billet": True, "n_lamellas": 1})
        self.assertEqual(m["facts"], "Waste 12%  Needs 1 piece")
        m = self.one("Your shape holds. Pressed in one curve from 3 layers, then milled to shape.", waste=None)
        self.assertEqual(m["facts"], "Needs 3 layers")

    def test_the_slot_limits_hold_for_every_mapped_answer(self):
        sentences = [
            "Your shape holds. Pressed in one curve from 38 layers, then milled to shape.",
            "Twist, profiles and path drift eased so the billet runs along the grain, moving the plate at most 1234 mm.",
            "Path straightened so the layers can bend, moving the plate at most 331 mm.",
            "Your line holds, in 12 pieces joined end to end. Each pressed from layers, then milled.",
        ]
        for s in sentences:
            m = self.one(s, dev=1234.0, waste=100.0)
            lim(m["verdict"], 28)
            lim(m["reason"], 68)
            lim(m["facts"], 42)
            self.assertFalse(re.search(r"\d", m["reason"]), m["reason"])


class Conflicts(unittest.TestCase):
    def one(self, sentence, kind="plate", holds=(), word="shape"):
        return slots.map_proposal(res(sentence, "conflict", waste=None), kind, word, list(holds))

    def test_each_conflict_has_a_reason_and_one_action(self):
        cases = [
            ("plate", "This bends too tightly for the thinnest layer.", "It bends too tightly for the thinnest layer.", "redraw"),
            ("plate", "This billet will not fit through the machine.", "The billet is too big for the machine.", "redraw"),
            ("plate", "The billet cannot run along the grain at this width.", "The billet cannot run along the grain at this width.", "redraw"),
            ("plate", "This will not mill from one straight piece on this machine.", "One straight piece will not fit the machine.", "release"),
            ("plate", "This shape could not be fitted with a billet.", "No billet fits this shape.", "redraw"),
            ("part", "This part bends too tightly for the thinnest layer.", "Your part bends too tightly for the thinnest layer.", "other_part"),
            ("part", "This part will not fit through the machine, even in 3 pieces.", "Even in pieces your part is too big for the machine.", "other_part"),
            ("part", "This part will not fit through the machine.", "Your part is too big for the machine.", "other_part"),
            ("part", "This part will not mill from one straight piece on this machine.", "Your part will not mill from one straight piece.", "other_part"),
            ("part", "This part could not be fitted with a billet.", "No billet fits your part.", "other_part"),
            ("surface", "This bends too tightly for the thinnest layer.", "It bends too tightly for the thinnest layer.", "redraw"),
        ]
        for kind, sentence, reason, action in cases:
            m = self.one(sentence, kind)
            self.assertEqual((m["verdict"], m["reason"], m["action"], m["facts"], m["mapped"]),
                             ("Not buildable.", reason, action, "", True), sentence)
            lim(m["reason"], 68)
            self.assertFalse(re.search(r"\d", m["reason"]))

    def test_a_shape_hold_makes_release_the_one_action_for_a_plate_or_a_line(self):
        for kind in ("plate", "surface"):
            m = self.one("This billet will not fit through the machine.", kind, holds=["shape"])
            self.assertEqual(m["action"], "release")
        m = self.one("This part will not fit through the machine.", "part", holds=["shape"])
        self.assertEqual(m["action"], "other_part")   # a part is never moved: nothing to release

    def test_trim_note_goes_to_the_echo(self):
        m = self.one("This billet will not fit through the machine. Kept to the 2.4 m stock length.", "surface")
        self.assertEqual((m["reason"], m["echo"]), ("The billet is too big for the machine.", "Kept to the timber length."))

    def test_the_core_vector_conflict(self):
        b = BODIES["twist_too_large_hold_shape"]
        m = slots.map_proposal(core.nudge_response(b, {"kind": "plate"}), "plate", "shape", ["shape"])
        self.assertEqual((m["verdict"], m["reason"], m["action"]), ("Not buildable.", "The billet is too big for the machine.", "release"))


class FromTheCoresOwnBodies(unittest.TestCase):
    def test_every_fixture_body_maps_without_the_fallback(self):
        for name, body in BODIES.items():
            r = core.nudge_response(body, {"kind": "plate"})
            m = slots.map_proposal(r, "plate", "shape", [])
            self.assertTrue(m["mapped"], name)
            lim(m["verdict"], 28)
            lim(m["reason"], 68)
            lim(m["facts"], 42)
            self.assertFalse(re.search(r"\d", m["reason"]), (name, m["reason"]))
            self.assertNotIn("plate", (m["verdict"] + m["reason"] + m["facts"]).lower())
            self.assertNotIn("holds", (m["verdict"] + m["reason"]).lower())

    def test_the_eased_vector_reads_as_the_spec_says(self):
        r = core.nudge_response(BODIES["path_too_tight"], {"kind": "plate"})
        m = slots.map_proposal(r, "plate", "shape", [])
        self.assertEqual((m["verdict"], m["reason"]), ("Buildable, eased.", "Path straightened so the layers can bend."))
        self.assertTrue(m["facts"].startswith("Waste 31%  Moved 331 mm  Needs "))

    def test_the_straight_member_is_one_piece_as_it_comes(self):
        r = core.nudge_response(BODIES["no_strokes"], {"kind": "plate"})
        m = slots.map_proposal(r, "plate", "shape", [])
        self.assertEqual((m["verdict"], m["reason"], m["facts"]), ("Buildable as drawn.", "One piece as it comes, no pressing.",
                                                                    "Waste 0%  Needs 1 piece"))


class Fallback(unittest.TestCase):
    def test_an_unknown_sentence_shows_the_core_words_and_says_so(self):
        m = slots.map_proposal(res("Something new the core says now.", dev=0.0, waste=20.0), "plate", "shape", [])
        self.assertEqual((m["mapped"], m["verdict"], m["reason"]), (False, slots.AS_DRAWN, "Something new the core says now."))
        self.assertEqual(m["unmapped"], "Something new the core says now.")
        m = slots.map_proposal(res("Something new the core says now.", dev=12.0), "plate", "shape", [])
        self.assertEqual(m["verdict"], "Buildable, eased.")   # from deviation_mm, a field, never a guess from words
        m = slots.map_proposal(res("x" * 200, "conflict", waste=None), "plate", "shape", [])
        self.assertEqual(m["verdict"], "Not buildable.")
        self.assertTrue(len(m["reason"]) <= 68 and m["reason"].endswith("..."))

    def test_the_old_bend_kind_is_unmapped_not_wrong(self):
        m = slots.map_proposal(res("Your curve holds. Made from 4 glued layers in place of one solid piece."), "bend", "curve", [])
        self.assertFalse(m["mapped"])


class Echo(unittest.TestCase):
    def test_say_lines_by_action_all_fit(self):
        table = [
            ([("hold", "solid")], "Keeping it as one piece."),
            ([("hold", "shape")], "Keeping your shape as drawn."),
            ([("release", "solid")], "Glue is fine again."),
            ([("release", "shape")], "Your shape may move again."),
            ([("hold", "less_waste")], "Thinner layers, less waste."),
            ([("release", "less_waste")], "Back to the thickest layers."),
            ([("hold", "split_ok")], "Shorter pieces are fine."),
            ([("release", "split_ok")], "Keeping it in one length."),
        ]
        for actions, line in table:
            got = slots.echo(("say", actions), "raw", "shape", "plate")
            self.assertEqual(got, line)
            lim(got, 34)

    def test_say_special_cases(self):
        self.assertEqual(slots.echo(("say", [("hold", "less_waste")]), "Already as little waste as this shape allows.",
                                    "shape", "plate"), "Already the least waste.")
        self.assertEqual(slots.echo(("say", []), "I did not catch a change I can make. I can keep it solid, keep your shape, "
                                    "or use less material.", "shape", "plate"), "I did not catch a change.")
        self.assertEqual(slots.echo(("say", [("hold", "shape")]), "Your geometry is never moved.", "part", "part"),
                         "Your geometry is never moved.")
        self.assertEqual(slots.echo(("say", [("hold", "shape")]), "x", "line", "surface"), "Keeping your line as drawn.")

    def test_photo_lines(self):
        def bends(*pairs):
            return [{"size": s, "direction": d, "span": "whole"} for s, d in pairs]
        cases = [(bends(("strong", "up")), "Photo read: strong bend up."),
                 (bends(("moderate", "down")), "Photo read: moderate bend down."),
                 (bends(("moderate", "toward_viewer")), "Photo read: a bend toward you."),
                 (bends(("strong", "away_from_viewer")), "Photo read: a bend away from you."),
                 (bends(("slight", "up"), ("strong", "down")), "Photo read: 2 bends."),
                 ([], "Photo read: no bends.")]
        for b, line in cases:
            got = slots.echo(("photo", b), "raw", "shape", "plate")
            self.assertEqual(got, line)
            lim(got, 34)
        self.assertEqual(slots.echo(("photo_no", None), "I could not read a timber shape from this photo.", "shape", "plate"),
                         "Photo not read.")

    def test_no_source_no_echo_and_an_unknown_source_is_cut_to_fit(self):
        self.assertEqual(slots.echo(None, "", "shape", "plate"), "")
        got = slots.echo(None, "Some raw line the core sent that is far too long to fit on one line.", "shape", "plate")
        lim(got, 34)


class Words(unittest.TestCase):
    def test_why_lines_use_the_glossary(self):
        self.assertEqual(slots.words("The plate sits at most 331 mm from what you drew."),
                         "The member sits at most 331 mm from what you drew.")
        self.assertEqual(slots.words("Your shape holds. One stock 2x4, no pressing."),
                         "Buildable as drawn. One piece as it comes, no pressing.")
        self.assertEqual(slots.words("A plate from your path, 2.4 m along its path."), "A member from your path, 2.4 m along its path.")
        self.assertNotIn("lamella", slots.words("3 lamellas of 38 mm").lower())


if __name__ == "__main__":
    unittest.main()
