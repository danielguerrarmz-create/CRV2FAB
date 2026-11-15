# -*- coding: utf-8 -*-
"""A photo as design intent (spec v8), client side: pure, no Rhino. Bodies as the core sends them."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gnj_core as core  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "plate_bodies.json")


def plate_body(name="path_too_tight"):
    import json
    with open(FIXTURES) as fh:
        return json.load(fh)["bodies"][name]


READ = {"understood": True,
        "heard": "Read from your photo: a moderate bend up along the whole length, then a strong bend up at the right end.",
        "bends": [{"span": "whole", "direction": "up", "size": "moderate"},
                  {"span": "right_third", "direction": "up", "size": "strong"}],
        "source": "claude-code", "model_ms": 3413,
        "nudge": {"status": "pending", "pending": "sculpt not merged yet", "bends": []}}
NOT_READ = {"understood": False, "heard": "I could not read a timber shape from this photo.", "bends": [],
            "source": "claude-code", "nudge": None}


class Canned(core.CoreClient):
    def __init__(self, body):
        core.CoreClient.__init__(self, "http://canned")
        self.body, self.posts = body, []

    def _post(self, path, body, timeout):
        self.posts.append((path, body, timeout))
        return self.body


class Photo(unittest.TestCase):
    def test_media_type_from_the_first_bytes(self):
        self.assertEqual(core.photo_media_type("a.png", b"\xff\xd8\xff\xe0\x00\x10JF"), "image/jpeg")
        self.assertEqual(core.photo_media_type("a.jpg", b"\x89PNG\r\n\x1a\n"), "image/png")
        self.assertIsNone(core.photo_media_type("a.gif", b"GIF89a\x00\x00"))

    def test_the_request_carries_bytes_never_a_path(self):
        c = Canned(READ)
        c.photo("QUJD", "image/jpeg")
        path, body, timeout = c.posts[0]
        self.assertEqual((path, sorted(body), timeout), ("/photo", ["image_b64", "media_type", "member_id"], core.PHOTO_TIMEOUT_S))
        self.assertNotIn("image_path", body)

    def test_a_photo_answers_with_a_plate_proposal(self):
        """Spec v9: the core builds a plate path from the bends and answers as /nudge does. No
        'sculpting' copy, ever."""
        s = core.Session(Canned(dict(READ, nudge=plate_body())))
        gen = s.begin_photo("arch.png")
        self.assertEqual((s.headline(), s.subline()), (core.READING_PHOTO, core.PHOTO_NOTICE))
        self.assertTrue(s.finish_photo(gen, s.client.photo("QUJD", "image/png")))
        self.assertEqual((s.heard, s.phase, s.photo_name), (READ["heard"], "proposed", "arch.png"))
        self.assertEqual((s.headline(), s.subline()), ("Buildable, eased.", "Path straightened so the layers can bend."))
        self.assertEqual(s.echo_line(), "Photo read: 2 bends.")   # SPEC_V9_CARD_SLOTS: Echo, from the bends
        self.assertTrue(s.can_judge() and s.result["form"]["kind"] == "plate_member")
        self.assertEqual(core.strokes_summary(s.sent_strokes),
                         "Path from your photo, Start kept as is, End kept as is")
        # a hold re-sends the photo's plate: its drawn path is the intent grid's row means
        path = s.intent()["path"]
        self.assertEqual(len(path), 65)
        self.assertAlmostEqual(path[32][2], max(p[2] for p in path), places=6)
        self.assertNotIn("sculpt", (s.headline() + s.subline()).lower())
        gen = s.begin_photo("second.png")
        self.assertEqual(s.subline(), "")   # the notice shows once a session

    def test_a_read_photo_with_no_plate_says_the_helper_could_not_take_it(self):
        s = core.Session(Canned(READ))   # an older core: nudge pending
        gen = s.begin_photo("arch.png")
        s.finish_photo(gen, s.client.photo("QUJD", "image/png"))
        self.assertEqual((s.phase, s.note), ("idle", core.PHOTO_REFUSED))

    def test_not_read_changes_nothing(self):
        s = core.Session(Canned(NOT_READ))
        gen = s.begin_photo("grey.png")
        s.finish_photo(gen, s.client.photo("QUJD", "image/png"))
        self.assertEqual((s.subline(), s.phase), (NOT_READ["heard"], "idle"))   # Reason carries the full line
        self.assertEqual(s.echo_line(), "Photo not read.")

    def test_refused_and_unreachable_say_so(self):
        s = core.Session(core.OfflineClient())
        gen = s.begin_photo("x.png")
        s.finish_photo(gen, None, refused=True)
        self.assertEqual(s.subline(), core.PHOTO_REFUSED)
        gen = s.begin_photo("x.png")
        s.finish_photo(gen, None)
        self.assertEqual(s.subline(), core.HELPER_DOWN)

    def test_one_photo_at_a_time(self):
        s = core.Session(core.OfflineClient())
        self.assertIsNotNone(s.begin_photo("a.png"))
        self.assertIsNone(s.begin_photo("b.png"))


if __name__ == "__main__":
    unittest.main()
