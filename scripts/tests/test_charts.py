"""Die Diagramme: gueltiges SVG, belegte Bauform, keine erfundenen Nullen.

Geprueft wird die Form, nicht die Optik. Was ein Test hier halten kann, ist
die Regel dahinter: gemeinsame Grundlinie, keine zweite Y-Achse, keine
Trichterform, und eine fehlende Zahl wird als fehlend gezeigt.
"""
import unittest
import xml.etree.ElementTree as ET

from audit import charts


def _svg(markup: str):
    """Das SVG aus dem <figure>-Rahmen, geparst. Wirft bei kaputtem XML."""
    inner = markup[markup.index("<svg"):markup.index("</svg>") + 6]
    return ET.fromstring(inner)


class TestBalkenpaar(unittest.TestCase):
    ZEILEN = [("Direkt", 1200000, 1500000.0),
              ("Organische Suche", 900000, 700000.0),
              ("Verweis", 300000, 250000.0)]

    def test_gueltiges_svg(self):
        wurzel = _svg(charts.bar_pair(self.ZEILEN, "Sitzungen", "Umsatz", "t"))
        self.assertTrue(wurzel.tag.endswith("svg"))

    def test_zwei_panels_teilen_die_kategorienachse(self):
        """Nur bei gleicher Reihenfolge faellt auf, wo viel Traffic wenig
        Umsatz traegt. Je Zeile genau ein Name, zweimal ein Balken."""
        markup = charts.bar_pair(self.ZEILEN, "Sitzungen", "Umsatz", "t")
        wurzel = _svg(markup)
        balken = [r for r in wurzel.iter() if r.tag.endswith("rect")]
        self.assertEqual(len(balken), 2 * len(self.ZEILEN))
        for name, _, _ in self.ZEILEN:
            self.assertIn(f">{name}<", markup)

    def test_balken_beginnen_bei_null(self):
        """Die Laenge kodiert den Wert, deshalb ist die Nulllinie Pflicht
        (Knaflic). Beide Panels starten an ihrem festen x."""
        wurzel = _svg(charts.bar_pair(self.ZEILEN, "a", "b", "t"))
        starts = {r.get("x") for r in wurzel.iter() if r.tag.endswith("rect")}
        self.assertEqual(len(starts), 2, "mehr als zwei Startpunkte, "
                                         "also keine gemeinsame Nulllinie")

    def test_fehlender_wert_wird_nicht_zu_null(self):
        markup = charts.bar_pair([("A", 100, None), ("B", 50, 20)],
                                   "a", "b", "t")
        self.assertIn("nicht erhoben", markup)
        self.assertEqual(len([r for r in _svg(markup).iter()
                              if r.tag.endswith("rect")]), 3)

    def test_ohne_zeilen_entsteht_kein_leeres_bild(self):
        self.assertEqual(charts.bar_pair([], "a", "b", "t"), "")


class TestStufenbalken(unittest.TestCase):
    STUFEN = [("Sitzung begonnen", 1000000, "Ausgangspunkt"),
              ("Artikel angesehen", 400000, "40,0 %"),
              ("Kauf", 20000, "2,0 %")]

    def test_keine_trichterform(self):
        """Der Trichter kodiert nichts: seine Breite folgt der Position im
        Stapel, nicht dem Wert, und ihm fehlt die gemeinsame Grundlinie.
        Alle Balken starten deshalb an derselben x-Position."""
        wurzel = _svg(charts.step_bars(self.STUFEN, "t"))
        starts = {r.get("x") for r in wurzel.iter() if r.tag.endswith("rect")}
        self.assertEqual(len(starts), 1)

    def test_laenge_folgt_dem_wert(self):
        wurzel = _svg(charts.step_bars(self.STUFEN, "t"))
        breiten = [float(r.get("width")) for r in wurzel.iter()
                   if r.tag.endswith("rect")]
        self.assertEqual(breiten, sorted(breiten, reverse=True))

    def test_die_quote_steht_daneben(self):
        markup = charts.step_bars(self.STUFEN, "t")
        for _, _, quote in self.STUFEN:
            self.assertIn(f">{quote}<", markup)

    def test_die_spalte_heisst_nicht_uebergang(self):
        """GA4 zählt je Stufe die Sitzungen mit diesem Ereignis, nicht den Weg.

        Eine Spalte "Weiter von der Stufe davor" behauptet eine Kette, die die
        Zahlen nicht beschreiben, und meldete am 07.09.2026 für den Warenkorb
        237,6 Prozent: mehr Sitzungen in der Stufe als in der davor.
        """
        markup = charts.step_bars(self.STUFEN, "t")
        self.assertNotIn("Stufe davor", markup)
        self.assertIn("Anteil aller Sitzungen", markup)


class TestJahresvergleich(unittest.TestCase):
    MONATE = [("09", 100000, 125000), ("10", 100000, 80000),
              ("11", 100000, 100000)]

    def test_zwei_saeulen_je_monat_plus_abweichung(self):
        wurzel = _svg(charts.year_comparison(self.MONATE, "t"))
        rects = [r for r in wurzel.iter() if r.tag.endswith("rect")]
        # zwei Legendenkaestchen, zwei Saeulen je Monat, ein Abweichungsbalken
        self.assertEqual(len(rects), 2 + 3 * len(self.MONATE))

    def test_die_abweichung_traegt_ihr_vorzeichen(self):
        markup = charts.year_comparison(self.MONATE, "t")
        self.assertIn(">+25%<", markup)
        self.assertIn(">-20%<", markup)

    def test_ein_monat_ohne_vorjahr_bricht_nicht(self):
        markup = charts.year_comparison([("01", 100, None)], "t")
        self.assertTrue(markup.startswith("<figure"))


if __name__ == "__main__":
    unittest.main()
