"""Automatisierten Traffic erkennen: was anschlagen muss, was nicht."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit import bots  # noqa: E402


def kanal(name, sessions, users, purchases=None, engaged=None):
    return {"channel": name, "sessions": sessions, "total_users": users,
            "purchases": purchases, "engaged_sessions": engaged,
            "purchase_revenue": 0.0}


def snapshot(*kanaele, sessions=None):
    gesamt = sessions if sessions is not None else sum(k["sessions"] for k in kanaele)
    return {"channels": list(kanaele), "totals": {"sessions": gesamt}}


#: Ein glaubwuerdiger Shop: fuenf Kanaele, die sich menschlich verhalten.
GESUND = [
    kanal("Organic Search", 200_000, 156_000, 2_500, 120_000),
    kanal("Paid Search", 260_000, 197_000, 7_200, 160_000),
    kanal("Paid Shopping", 270_000, 219_000, 5_000, 170_000),
    kanal("Referral", 30_000, 22_000, 700, 19_000),
    kanal("Organic Social", 56_000, 52_000, 500, 30_000),
]


class TestGesunderShop(unittest.TestCase):
    def test_ein_shop_ohne_auffaelligkeit_meldet_nichts(self):
        r = bots.analyze(snapshot(*GESUND))
        self.assertTrue(r["measurable"])
        self.assertEqual(r["suspicious_channels"], [])
        self.assertEqual(r["upper_bound_sessions"], 0)


class TestAnzeichen(unittest.TestCase):
    def test_zwei_anzeichen_reichen(self):
        verdaechtig = kanal("Direct", 1_600_000, 1_570_000, 5_300)
        r = bots.analyze(snapshot(*GESUND, verdaechtig))
        namen = [k["channel"] for k in r["suspicious_channels"]]
        self.assertEqual(namen, ["Direct"])
        self.assertEqual(r["upper_bound_sessions"], 1_600_000)

    def test_ein_anzeichen_allein_reicht_nicht(self):
        """Jedes Anzeichen hat eine harmlose Erklaerung. Eine Kampagne auf eine
        Landingpage bringt Einmalbesucher, und das ist kein Bot."""
        nur_einmalbesucher = kanal("Paid Social", 60_000, 59_000, 1_100, 40_000)
        r = bots.analyze(snapshot(*GESUND, nur_einmalbesucher))
        self.assertEqual(r["suspicious_channels"], [])

    def test_ein_kleiner_kanal_wird_nicht_beurteilt(self):
        """Acht Sitzungen ohne Kauf ergeben rechnerisch null Prozent
        Conversion und bedeuten nichts."""
        winzig = kanal("Organic Video", 8, 5, 0)
        r = bots.analyze(snapshot(*GESUND, winzig))
        self.assertEqual(r["suspicious_channels"], [])
        row = [k for k in r["channels"] if k["channel"] == "Organic Video"][0]
        self.assertTrue(row["too_small_to_judge"])

    def test_eine_fehlende_kennzahl_macht_keinen_kanal_verdaechtig(self):
        """Eine Property, die die Kaufmetrik verweigert, darf keinen Verdacht
        erzeugen. Null heisst hier unbekannt, nicht null Bestellungen."""
        ohne = kanal("Direct", 1_600_000, 1_570_000, purchases=None)
        r = bots.analyze(snapshot(*GESUND, ohne))
        row = [k for k in r["channels"] if k["channel"] == "Direct"][0]
        self.assertEqual(len(row["signals"]), 1)
        self.assertEqual(r["suspicious_channels"], [])

    def test_transactions_from_an_old_snapshot_are_not_read_as_purchases(self):
        """Snapshots vor dem 11.09.2026 tragen `transactions`, und darin zählt
        GA4 Refunds mit. Der Kanal gilt dann als ungemessen, nicht als Kanal
        mit Käufen."""
        alt = {"channel": "Direct", "sessions": 1_000, "total_users": 900,
               "transactions": 40, "engaged_sessions": 600, "purchase_revenue": 0.0}
        row = bots.check_channel(alt, 10_000, 0.02)
        self.assertIsNone(row["conversion_rate"])


class TestReferenz(unittest.TestCase):
    """Der Fehler, an dem die erste Fassung gescheitert ist."""

    def test_ein_grosser_kanal_kann_die_referenz_nicht_verschieben(self):
        """Traegt ein Kanal die Haelfte aller Sitzungen und kauft nicht, zieht
        er den Shop-Durchschnitt so weit herunter, dass er selbst dagegen
        unauffaellig wirkt. Der Median mehrerer Kanaele geht das nicht mit."""
        verdaechtig = kanal("Direct", 1_646_538, 1_609_928, 5_327)
        daten = snapshot(*GESUND, verdaechtig)
        r = bots.analyze(daten)

        shop = r["shop_conversion_rate"]
        referenz = r["reference_conversion_rate"]
        self.assertLess(shop, referenz,
                        "der Durchschnitt muesste vom Verdachtskanal "
                        "heruntergezogen sein")
        self.assertIn("Direct", [k["channel"] for k in r["suspicious_channels"]])

    def test_unter_drei_grossen_kanaelen_faellt_das_anzeichen_aus(self):
        """Ein Median aus zwei Werten traegt nicht."""
        r = bots.analyze(snapshot(
            kanal("A", 100_000, 90_000, 1_000),
            kanal("B", 100_000, 95_000, 20),
        ))
        self.assertIsNone(r["reference_conversion_rate"])


class TestSpanne(unittest.TestCase):
    def test_die_untergrenze_zaehlt_nur_sitzungen_ohne_engagement(self):
        verdaechtig = kanal("Direct", 1_000_000, 990_000, 300, engaged=100_000)
        r = bots.analyze(snapshot(*GESUND, verdaechtig))
        self.assertEqual(r["lower_bound_sessions"], 900_000)
        self.assertLess(r["lower_bound_sessions"], r["upper_bound_sessions"])

    def test_ohne_engagement_gibt_es_keine_untergrenze_statt_einer_null(self):
        """Null waere die Behauptung, es gebe keinen Bot-Traffic."""
        verdaechtig = kanal("Direct", 1_000_000, 990_000, 300)
        r = bots.analyze(snapshot(*GESUND, verdaechtig))
        self.assertIsNone(r["lower_bound_sessions"])

    def test_die_notiz_sagt_woher_die_spanne_kommt(self):
        r = bots.analyze(snapshot(*GESUND))
        self.assertIn("Server", r["note"])


class TestNichtMessbar(unittest.TestCase):
    def test_ohne_kanaele_sagt_das_ergebnis_das(self):
        r = bots.analyze({"channels": [], "totals": {"sessions": 0}})
        self.assertFalse(r["measurable"])
        self.assertIn("keine Kanalzahlen", r["reason"])
        self.assertEqual(r["suspicious_channels"], [])


BOT = {"screenResolution": "1440x1440", "operatingSystem": "Windows",
       "deviceCategory": "desktop", "browser": "Chrome"}
PHONE = {"screenResolution": "390x844", "operatingSystem": "iOS",
         "deviceCategory": "mobile", "browser": "Safari"}


def day(n):
    """Kalendertag n ab dem 01.01.2026 als ISO-Datum."""
    from datetime import date, timedelta
    return (date(2026, 1, 1) + timedelta(days=n)).isoformat()


def profile_row(n, profile, sessions, engaged, purchases):
    return {"date": day(n), "profile": dict(profile), "sessions": sessions,
            "engaged_sessions": engaged, "purchases": purchases}


class TestFilterProposal(unittest.TestCase):
    """Der Vorschlag kommt aus dem Geräteprofil, nie aus einem Kanal.

    Am 13.09.2026 nachgerechnet: der Audit hatte empfohlen, einen ganzen Kanal
    auszuschliessen. Das hätte die echten Sitzungen des Kanals samt ihren
    Käufen entfernt und die Bot-Sitzungen in einem anderen Kanal stehen
    lassen.
    """

    def flagged(self):
        return {"profiles": [bots.assess_profile(
            BOT, {"sessions": 480_000, "engaged_sessions": 40_000, "purchases": 0},
            1_000_000)]}

    def test_the_proposal_is_never_switched_on(self):
        proposal = bots.filter_proposal(self.flagged())
        self.assertFalse(proposal["enabled"])

    def test_the_rule_names_every_profile_dimension(self):
        rule = bots.filter_proposal(self.flagged())["exclude"][0]
        self.assertEqual(rule["screen_resolution_in"], ["1440x1440"])
        self.assertEqual(rule["operating_system_in"], ["Windows"])
        self.assertEqual(rule["device_in"], ["desktop"])
        self.assertEqual(rule["browser_in"], ["Chrome"])
        self.assertIn("Sitzungen", rule["reason"])

    def test_a_suspicious_channel_never_becomes_a_channel_filter(self):
        verdaechtig = kanal("Direct", 1_600_000, 1_570_000, 5_300)
        r = bots.analyze(snapshot(*GESUND, verdaechtig))
        self.assertIn("Direct", [k["channel"] for k in r["suspicious_channels"]])
        self.assertIsNone(bots.filter_proposal(r))

    def test_without_a_flagged_profile_there_is_no_proposal(self):
        human = bots.assess_profile(
            PHONE, {"sessions": 120_000, "engaged_sessions": 66_000, "purchases": 2_700},
            1_000_000)
        self.assertIsNone(bots.filter_proposal({"profiles": [human]}))


class TestProfileVerdict(unittest.TestCase):
    """Drei Bedingungen zusammen: Anteil, kaum Engagement, praktisch kein Kauf."""

    def test_a_large_profile_without_engagement_and_purchases_is_flagged(self):
        r = bots.assess_profile(
            BOT, {"sessions": 480_000, "engaged_sessions": 60_000, "purchases": 0},
            1_000_000)
        self.assertTrue(r["flagged"])
        self.assertEqual(r["share_of_sessions"], 0.48)

    def test_a_profile_that_buys_is_never_flagged(self):
        """Ein menschliches Gerät kauft. Wer es filtert, verliert Umsatz."""
        r = bots.assess_profile(
            BOT, {"sessions": 480_000, "engaged_sessions": 60_000, "purchases": 900},
            1_000_000)
        self.assertFalse(r["flagged"])

    def test_a_few_purchases_do_not_protect_a_bot_profile(self):
        """Ein paar echte Menschen mit demselben Gerät kippen den Befund nicht.
        Jeder Kauf, den der Filter mitnähme, steht im Ergebnis."""
        r = bots.assess_profile(
            BOT, {"sessions": 480_000, "engaged_sessions": 60_000, "purchases": 12},
            1_000_000)
        self.assertTrue(r["flagged"])
        self.assertEqual(r["purchases"], 12)

    def test_an_engaged_profile_is_not_flagged(self):
        r = bots.assess_profile(
            PHONE, {"sessions": 60_000, "engaged_sessions": 33_000, "purchases": 0},
            1_000_000)
        self.assertFalse(r["flagged"])

    def test_a_small_profile_is_not_flagged(self):
        """Unter einem Prozent aller Sitzungen verschiebt ein Profil keine
        Rate des Audits sichtbar."""
        r = bots.assess_profile(
            BOT, {"sessions": 6_000, "engaged_sessions": 100, "purchases": 0}, 1_000_000)
        self.assertFalse(r["flagged"])

    def test_unknown_engagement_or_purchases_never_flag(self):
        for totals in ({"sessions": 480_000, "engaged_sessions": None, "purchases": 0},
                       {"sessions": 480_000, "engaged_sessions": 1_000, "purchases": None}):
            with self.subTest(totals=totals):
                self.assertFalse(bots.assess_profile(BOT, totals, 1_000_000)["flagged"])

    def test_channels_and_windows_are_carried_along(self):
        channels = [{"channel": "Direct", "sessions": 400_000}]
        windows = [{"start": day(0), "end": day(9)}]
        r = bots.assess_profile(
            BOT, {"sessions": 480_000, "engaged_sessions": 60_000, "purchases": 0},
            1_000_000, channels=channels, windows=windows)
        self.assertEqual(r["channels"], channels)
        self.assertEqual(r["windows"], windows)


class TestProfileCandidates(unittest.TestCase):
    """Aus der Tagesreihe je Geräteprofil die Kandidaten fürs Nachzählen."""

    def rows(self):
        out = []
        for n in range(30):
            out.append(profile_row(n, PHONE, 400, 220, 9))
            out.append(profile_row(n, BOT, 900 if 10 <= n < 20 else 20, 30, 0))
        return out

    def test_the_bot_profile_is_a_candidate_and_the_phone_is_not(self):
        cands = bots.profile_candidates(self.rows(), total_sessions=60_000)
        self.assertEqual([c["profile"] for c in cands], [BOT])
        self.assertEqual(cands[0]["sessions"], 10 * 900 + 20 * 20)
        self.assertEqual(cands[0]["days"][day(10)], 900)

    def test_the_list_is_capped(self):
        rows = []
        for i in range(bots.MAX_CANDIDATES + 3):
            p = dict(BOT, screenResolution=f"{1000 + i}x{1000 + i}")
            rows.append(profile_row(0, p, 1_000 + i, 10, 0))
        cands = bots.profile_candidates(rows, total_sessions=20_000)
        self.assertEqual(len(cands), bots.MAX_CANDIDATES)
        self.assertEqual(cands[0]["sessions"], 1_000 + bots.MAX_CANDIDATES + 2)

    def test_the_daily_floor_scales_with_the_shop(self):
        self.assertEqual(bots.daily_floor(3_650_000, 365), 50)
        self.assertEqual(bots.daily_floor(36_500, 365), bots.MIN_DAILY_FLOOR)


class TestWaveWindows(unittest.TestCase):
    """Die Zeiträume, in denen ein Profil einen ungewöhnlichen Anteil trägt."""

    TOTALS = {day(n): 1_000 for n in range(60)}

    def test_a_wave_with_a_short_dip_is_one_window(self):
        profile = {day(n): 10 for n in range(60)}
        profile.update({day(n): 700 for n in range(15, 31)})
        profile[day(21)] = profile[day(22)] = 30
        windows = bots.wave_windows(self.TOTALS, profile)
        self.assertEqual([(w["start"], w["end"]) for w in windows], [(day(15), day(30))])
        self.assertEqual(windows[0]["days"], 16)
        self.assertEqual(windows[0]["sessions"], 14 * 700 + 2 * 30)

    def test_a_longer_gap_splits_the_wave(self):
        profile = {day(n): 10 for n in range(60)}
        profile.update({day(n): 700 for n in list(range(10, 15)) + list(range(18, 25))})
        windows = bots.wave_windows(self.TOTALS, profile)
        self.assertEqual([(w["start"], w["end"]) for w in windows],
                         [(day(10), day(14)), (day(18), day(24))])

    def test_a_negligible_spike_is_not_a_window(self):
        """Ein Tag, der weniger als ein Prozent der Profil-Sitzungen trägt,
        ändert keine Zahl."""
        profile = {day(n): 10 for n in range(60)}
        profile.update({day(n): 900 for n in range(15, 31)})
        profile[day(50)] = 120
        windows = bots.wave_windows(self.TOTALS, profile)
        self.assertEqual([(w["start"], w["end"]) for w in windows], [(day(15), day(30))])

    def test_a_constant_bot_gets_its_active_period_as_window(self):
        """Ohne Welle gibt es keinen Tag über dem eigenen Normalanteil. Das
        Profil läuft dann durchgehend, und genau das steht da."""
        profile = {day(n): 400 for n in range(5, 55)}
        windows = bots.wave_windows(self.TOTALS, profile)
        self.assertEqual([(w["start"], w["end"]) for w in windows], [(day(5), day(54))])

    def test_the_window_carries_its_share_and_peak(self):
        profile = {day(n): 10 for n in range(60)}
        profile.update({day(n): 500 for n in range(15, 20)})
        profile[day(17)] = 800
        w = bots.wave_windows(self.TOTALS, profile)[0]
        self.assertEqual(w["peak_day"], day(17))
        self.assertEqual(w["peak_share"], 0.8)
        self.assertEqual(w["share"], round(2_800 / 5_000, 4))


if __name__ == "__main__":
    unittest.main()
