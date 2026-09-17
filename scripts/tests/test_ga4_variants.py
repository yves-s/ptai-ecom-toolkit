"""GA4-Raten mit und ohne Bot-Profil, und nur mit dem ersten Absender."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit import ga4_variants  # noqa: E402


def block(total, channels, devices, funnel, primary=None):
    out = {
        "totals": {"sessions": total},
        "channels": [{"channel": c, "sessions": s, "total_users": u, "purchases": p,
                      "engaged_sessions": e, "purchase_revenue": 0.0}
                     for c, s, u, p, e in channels],
        "devices": [{"device": d, "sessions": s, "purchases": p} for d, s, p in devices],
        "funnel": dict({"sessions": total},
                       **{k: {"events": v * 2, "sessions": v} for k, v in funnel.items()}),
        "landing_pages": [{"landing_page": "/", "sessions": total // 2,
                           "engagement_rate": 0.5, "purchases": 10}],
    }
    if primary:
        out["primary_sender"] = primary
    return out


FUNNEL_ALL = {"view_item": 5_000, "add_to_cart": 250, "view_cart": 270,
              "begin_checkout": 110, "purchase": 92}
FUNNEL_CLEAN = dict(FUNNEL_ALL, view_item=2_600)


def snapshot(with_profile=True, primary=True):
    ga4 = block(10_000,
                [("Direct", 6_000, 5_900, 12, 900), ("Organic Search", 4_000, 3_000, 80, 2_400)],
                [("desktop", 7_000, 20), ("mobile", 3_000, 72)],
                FUNNEL_ALL)
    if with_profile:
        ga4["bot_profiles"] = {
            "checked": True,
            "flagged": True,
            "profiles": [{"label": "1440x1440 / Windows / desktop / Chrome", "flagged": True}],
            "without": block(
                5_000,
                [("Direct", 1_000, 900, 12, 500), ("Organic Search", 4_000, 3_000, 80, 2_400)],
                [("desktop", 2_000, 20), ("mobile", 3_000, 72)],
                FUNNEL_CLEAN,
                primary={"funnel": dict({k: {"events": v, "sessions": v}
                                         for k, v in FUNNEL_CLEAN.items()},
                                        view_item={"events": 3_000, "sessions": 2_500},
                                        add_to_cart={"events": 240, "sessions": 240}),
                         "channels": [{"channel": "Direct", "purchases": 9}],
                         "devices": [{"device": "desktop", "purchases": 15}]} if primary else None),
            "filter_proposal": {"enabled": False, "exclude": [{"reason": "Geräteprofil X"}]},
        }
    return ga4


class TestVariants(unittest.TestCase):
    def test_without_a_detected_profile_there_is_one_variant(self):
        result = ga4_variants.compare(snapshot(with_profile=False))
        self.assertEqual([v["key"] for v in result["variants"]], ["all_sessions"])
        self.assertFalse(result["bot_profiles_checked"])

    def test_both_variants_carry_a_label_for_the_finding(self):
        result = ga4_variants.compare(snapshot())
        self.assertEqual([(v["key"], v["label"]) for v in result["variants"]],
                         [("all_sessions", "alle Sitzungen"),
                          ("without_bot_profiles", "ohne Bot-Profil")])
        self.assertTrue(result["bot_profiles_checked"])
        self.assertEqual(result["flagged_profiles"], ["1440x1440 / Windows / desktop / Chrome"])


class TestRates(unittest.TestCase):
    def variant(self, key):
        return [v for v in ga4_variants.compare(snapshot())["variants"] if v["key"] == key][0]["rates"]

    def test_a_channel_share_changes_with_the_denominator(self):
        direct_all = self.variant("all_sessions")["channels"][0]
        direct_clean = self.variant("without_bot_profiles")["channels"][0]
        self.assertEqual((direct_all["sessions"], direct_all["share"]), (6_000, 0.6))
        self.assertEqual((direct_clean["sessions"], direct_clean["share"]), (1_000, 0.2))

    def test_the_conversion_rate_is_purchases_per_session(self):
        desktop = self.variant("without_bot_profiles")["devices"][0]
        self.assertEqual(desktop["conversion_rate"], 0.01)

    def test_the_add_to_cart_rate_is_session_based(self):
        steps = {s["to"]: s for s in self.variant("all_sessions")["funnel"]}
        self.assertEqual(steps["add_to_cart"]["sessions_from"], 5_000)
        self.assertEqual(steps["add_to_cart"]["rate"], 0.05)
        self.assertEqual(steps["view_item"]["sessions_from"], 10_000)

    def test_first_sender_rates_only_where_they_were_measured(self):
        clean = self.variant("without_bot_profiles")
        self.assertEqual(clean["devices"][0]["conversion_rate_primary_sender"], 0.0075)
        self.assertEqual(clean["channels"][1]["purchases_primary_sender"], 0)
        steps = {s["to"]: s for s in clean["funnel"]}
        self.assertEqual(steps["add_to_cart"]["rate_primary_sender"], round(240 / 2_500, 5))
        self.assertNotIn("conversion_rate_primary_sender", self.variant("all_sessions")["devices"][0])

    def test_missing_purchases_stay_unknown(self):
        ga4 = snapshot(with_profile=False)
        ga4["devices"][0]["purchases"] = None
        rates = ga4_variants.compare(ga4)["variants"][0]["rates"]
        self.assertIsNone(rates["devices"][0]["conversion_rate"])

    def test_the_channel_signals_are_judged_per_variant(self):
        all_sessions = self.variant("all_sessions")
        self.assertIn("suspicious_channels", all_sessions)


if __name__ == "__main__":
    unittest.main()
