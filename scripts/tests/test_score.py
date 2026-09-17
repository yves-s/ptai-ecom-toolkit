"""Der Health Score: gleiche Rechenweise wie die Engine des audit-light."""
import unittest

from audit import score


def _b(schwere, n=1, conf="confirmed", praefix="X"):
    return [{"id": f"{praefix}-{i:02d}", "_schwere": schwere, "confidence": conf}
            for i in range(n)]


class TestSektionsScore(unittest.TestCase):
    def test_ohne_befunde_der_deckel(self):
        """100 wuerde behaupten, es gaebe nichts mehr zu finden."""
        self.assertEqual(score.section_score([]), score.DECKEL)

    def test_ein_schwerer_befund_kostet_mehr_als_ein_leichter(self):
        self.assertLess(score.section_score(_b("hoch")),
                        score.section_score(_b("gering")))

    def test_ein_verdacht_kostet_weniger_als_eine_messung(self):
        self.assertGreater(score.section_score(_b("hoch", conf="hypothesis")),
                           score.section_score(_b("hoch", conf="confirmed")))

    def test_der_boden_haelt(self):
        """Eine gründlich geprüfte Sektion darf nicht durch die MENGE ihrer
        Befunde gegen null laufen."""
        self.assertEqual(score.section_score(_b("hoch", 200)), score.FLOOR)

    def test_abnehmender_ertrag(self):
        """Der zehnte schwere Befund kostet weniger als der erste.

        Sonst misst der Score die Prüftiefe statt die Shop-Qualität: wer
        gründlicher sucht, findet mehr und sieht damit schlechter aus.
        """
        eins = 100 - score.section_score(_b("hoch", 1))
        zwei = 100 - score.section_score(_b("hoch", 2))
        drei = 100 - score.section_score(_b("hoch", 3))
        self.assertLess(drei - zwei, zwei - eins)

    def test_wenige_kleine_befunde_erreichen_den_deckel(self):
        """Der Deckel sagt "hier ist nichts Auffälliges", nicht "perfekt"."""
        self.assertEqual(score.section_score(_b("mittel", 1)), score.DECKEL)


class TestZiel(unittest.TestCase):
    def test_ohne_massnahmen_bleibt_der_score(self):
        findings = _b("hoch", 3)
        s = score.section_score(findings)
        self.assertEqual(score.target(s, findings, []), s)

    def test_alles_behebbar_heisst_der_deckel(self):
        """Die Aussage steckt im Abstand, nicht in der Höhe des Ziels."""
        findings = _b("hoch", 20)
        s = score.section_score(findings)
        massnahmen = [{"finding_ref": f["id"]} for f in findings]
        self.assertEqual(score.target(s, findings, massnahmen), score.DECKEL)

    def test_befunde_ohne_massnahme_bleiben_im_ziel(self):
        """Eine Lücke in der Datenlage verschwindet nicht dadurch, dass
        jemand arbeitet."""
        behebbar = _b("mittel", 4, praefix="A")
        offen = _b("hoch", 3, praefix="B")
        findings = behebbar + offen
        s = score.section_score(findings)
        massnahmen = [{"finding_ref": f["id"]} for f in behebbar]
        z = score.target(s, findings, massnahmen)
        self.assertGreater(z, s)
        self.assertLess(z, score.DECKEL)
        self.assertEqual(z, score.section_score(offen))

    def test_der_abstand_traegt_die_aussage(self):
        """Ein Bereich mit vielen behebbaren Befunden springt weiter."""
        viele = _b("hoch", 8, praefix="A")
        wenige = _b("mittel", 1, praefix="B")
        for findings in (viele, wenige):
            pass
        sprung = []
        for findings in (viele, wenige):
            s = score.section_score(findings)
            m = [{"finding_ref": f["id"]} for f in findings]
            sprung.append(score.target(s, findings, m) - s)
        self.assertGreater(sprung[0], sprung[1])


class TestGesamt(unittest.TestCase):
    def test_eine_sektion_ohne_daten_bekommt_keinen_score(self):
        """Sonst sieht ein Bereich, den niemand prüfen konnte, aus wie einer
        ohne Probleme."""
        out = score.compute({"conversion": _b("hoch", 2)}, [],
                            ohne_daten={"measurement"})
        self.assertIsNone(out["sektionen"]["measurement"])
        self.assertIsNone(out["bereiche"]["tracking"])

    def test_das_gewicht_ausgefallener_bereiche_wird_verteilt(self):
        """Der Gesamtscore darf nicht fallen, nur weil etwas nicht messbar war."""
        voll = score.compute({"conversion": _b("gering", 1),
                              "measurement": _b("gering", 1)}, [])
        ohne = score.compute({"conversion": _b("gering", 1)}, [],
                             ohne_daten={"measurement"})
        self.assertEqual(ohne["gesamt"], voll["bereiche"]["conversion"])

    def test_ohne_jede_sektion_kein_gesamtwert(self):
        self.assertIsNone(score.compute({}, [])["gesamt"])

    def test_jede_sektion_gehoert_zu_genau_einem_bereich(self):
        gesehen = []
        for b in score.AREAS.values():
            gesehen += list(b["sektionen"])
        self.assertEqual(len(gesehen), len(set(gesehen)))

    def test_die_gewichte_ergeben_eins(self):
        total = sum(b["gewicht"] for b in score.AREAS.values())
        self.assertAlmostEqual(total, 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
