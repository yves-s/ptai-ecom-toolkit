"""Der Report-Builder: Formatierung, Sektionen, Platzhalter.

Der Schwerpunkt liegt auf den fünf Stellen, an denen der erste echte Lauf am
07.09.2026 ein unbrauchbares PDF erzeugt hat. Ein Test je Ursache, damit keine
davon still zurückkommt.
"""
import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from audit import env
from audit import report_build as rb


#: Die Einstellungen, aus denen der Schluss des Audits entsteht. Kein Test hier
#: liest sie aus der echten Umgebung oder der echten zentralen Datei.
CLOSING_SETTINGS = ("PTAI_OPERATOR_NAME", "PTAI_OPERATOR_CONTACT", "PTAI_OPERATOR_EMAIL",
                    "PTAI_OPERATOR_BOOKING_URL", "PTAI_CLOSING_FILE")

#: Eine erfundene Schlussseite in der Form, die `PTAI_CLOSING_FILE` verlangt.
FRAGMENT = ('<section class="beispiel-abbinder" '
            'style="break-before:page;width:210mm;height:297mm">Beispiel-Abbinder</section>\n')


def _schreibe(pfad: Path, doc) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def _render(section, run):
    """Die Sektion bauen, ihre Warnungen auf stderr getrennt davon."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        return section(run), err.getvalue()


class TestZahlen(unittest.TestCase):
    def test_deutsches_format(self):
        self.assertEqual(rb.num_de(1234567), "1.234.567")
        self.assertEqual(rb.num_de(64.0839, 2), "64,08")

    def test_fehlender_wert_wird_nie_null(self):
        """Eine leere Zelle liest sich als Null, und eine Null ist eine Messung."""
        self.assertEqual(rb.num_de(None), "nicht erhoben")
        self.assertEqual(rb.percent(None), "nicht erhoben")

    def test_einheit_bricht_nicht_um(self):
        """Auf einer schmalen Kachel rutscht das Euro-Zeichen sonst in Zeile zwei."""
        self.assertEqual(rb.num_de(1234567, 0, " €"), f"1.234.567{rb.NBSP}€")
        self.assertNotIn(" €", rb.num_de(12, 0, " €"))

    def test_veraenderung_traegt_ihr_vorzeichen(self):
        """Ohne Vorzeichen liest sich ein Rückgang wie ein Zuwachs."""
        self.assertEqual(rb.delta(-0.204), f"-20,4{rb.NBSP}%")
        self.assertEqual(rb.delta(0.025), f"+2,5{rb.NBSP}%")
        self.assertEqual(rb.delta(None), "kein Vergleichswert")


class TestDatum(unittest.TestCase):
    def test_iso_wird_deutsch(self):
        """"2026-09-06" liest ein deutscher Leser sonst als 9. Juni."""
        self.assertEqual(rb.date_de("2026-09-06"), "06.09.2026")
        self.assertEqual(rb.date_de("2026-09-06T11:20:00Z"), "06.09.2026")

    def test_zeitraum_ohne_daten_bleibt_momentaufnahme(self):
        self.assertEqual(rb.period_de({}), "Momentaufnahme")
        self.assertEqual(rb.period_de(None), "Momentaufnahme")

    def test_monat_wird_deutsch(self):
        self.assertEqual(rb._month_de("2026-01"), "01/2026")


class TestToteSpalte(unittest.TestCase):
    """Eine Spalte, in der jede Zelle leer ist, ist fast nie eine Lücke."""

    def test_warnung_bei_ganz_leerer_spalte(self):
        import contextlib, io as _io
        err = _io.StringIO()
        with contextlib.redirect_stderr(err):
            rb.table(["Domain", "Keywords"],
                       [("a.de", "nicht erhoben"), ("b.de", "nicht erhoben"),
                        ("c.de", "nicht erhoben")])
        self.assertIn("Keywords", err.getvalue())

    def test_erlaubte_spalte_warnt_nicht(self):
        import contextlib, io as _io
        err = _io.StringIO()
        with contextlib.redirect_stderr(err):
            rb.table(["Quelle", "Status"],
                       [("a", "nicht erhoben"), ("b", "nicht erhoben"),
                        ("c", "nicht erhoben")], leerspalten_ok=("Status",))
        self.assertEqual(err.getvalue(), "")


class TestTabelle(unittest.TestCase):
    def test_ohne_zeilen_entsteht_ein_satz_statt_eines_kopfes(self):
        """Ein Tabellenkopf ohne Inhalt sieht aus wie ein Renderfehler."""
        out = rb.table(["A", "B"], [], empty="Nichts erhoben.")
        self.assertNotIn("<table", out)
        self.assertIn("Nichts erhoben.", out)

    def test_zahlenspalten_werden_aus_den_werten_erkannt(self):
        out = rb.table(["Kennzahl", "Wert", "Bezug"],
                         [("Klicks", "120.000", "aus der Google-Suche"),
                          ("Impressionen", "4.800.000", "im selben Zeitraum")])
        header = out[out.index("<thead>"):out.index("</thead>")]
        self.assertEqual(header.count('class="num"'), 1)

    def test_zahlenblock_verlangt_seinen_zeitraum(self):
        """"1.200.000 Sessions" kann ein Monat oder fünf Jahre sein."""
        out = rb.numbers_block(["A"], [("1",)], zeitraum="2025-09 bis 2026-08")
        self.assertIn("2025-09 bis 2026-08", out)


class TestUeberschrift(unittest.TestCase):
    def test_ganzer_satz_schlaegt_kurzen(self):
        """Ein Kopf, der mitten im Satz endet, liest sich wie ein Renderfehler."""
        text = ("In den acht Monaten mit nachweislich laufender Kaufmessung "
                "(2025-09 bis 2025-12 und 2026-05 bis 2026-08) fuehrt Shopify "
                "12.000 Bestellungen, GA4 zaehlt 9.000 Transaktionen. Es fehlen "
                "3.000 Bestellungen.")
        header, remainder = rb.first_sentence(text)
        self.assertTrue(header.endswith("Transaktionen."), header)
        self.assertTrue(remainder.startswith("Es fehlen"))

    def test_ohne_satzende_wird_an_einer_wortgrenze_getrennt(self):
        header, remainder = rb.first_sentence("wort " * 60)
        self.assertLessEqual(len(header), 170)
        self.assertTrue(remainder)


class TestBaukasten(unittest.TestCase):
    """Der BAUKASTEN enthält selbst Kommentare.

    Ein nicht-gieriges `.*?` bricht am ersten inneren "-->" ab und lässt den
    Rest als sichtbaren Text im Kundendokument stehen. Genau das ist am
    07.09.2026 passiert.
    """

    TEMPLATE = Path(__file__).resolve().parents[2] / "skills" / "audit" / "templates" / "audit.html"

    def test_der_kommentar_enthaelt_kommentare(self):
        text = self.TEMPLATE.read_text(encoding="utf-8")
        start = text.index("<!-- ======================= BAUKASTEN")
        end = text.index("==================================================================== -->")
        self.assertIn("-->", text[start + 40:end],
                      "Ohne inneren Kommentar prüft der Test unten nichts mehr.")

    def test_der_block_wird_vollstaendig_entfernt(self):
        import re
        text = self.TEMPLATE.read_text(encoding="utf-8")
        out = re.sub(r"<!-- ===+ BAUKASTEN.*?^=+ -->\n?", "", text,
                     flags=re.S | re.M)
        self.assertNotIn("BAUKASTEN", out)
        self.assertNotIn("Was gemessen wurde", out)


class TestKennung(unittest.TestCase):
    """Ein Agent, der sich eigene Kürzel ausdenkt, bricht jede Verknüpfung."""

    def test_das_kuerzel_kommt_aus_der_datei_nicht_vom_agent(self):
        self.assertEqual(rb.finding_id("data-quality", "DQ-07", 3), "MES-07")
        self.assertEqual(rb.finding_id("seo-content", "SEO-12", 1), "SEO-12")

    def test_ohne_kennung_zaehlt_die_reihenfolge(self):
        self.assertEqual(rb.finding_id("commerce", None, 4), "HDL-04")

    def test_unbekannte_datei_bekommt_ein_neutrales_kuerzel(self):
        self.assertEqual(rb.finding_id("neue-disziplin", None, 1), "BEF-01")


class TestSektionen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        run_id = "2026-10-01-audit"
        self.run_id = run_id
        _schreibe(self.ws / "reporting" / "config.json", {"brand": "Beispielshop"})
        _schreibe(self.ws / "reporting" / "runs" / run_id / "state.json", {
            "sources": {"shopify": {"status": "done", "last_pulled": "2026-10-01"},
                        "ads": {"status": "skipped",
                                "reason": "Kein Zugang zum Werbekonto"}}})

    def tearDown(self):
        self.tmp.cleanup()

    def _lauf(self):
        return rb.Run(self.ws, self.run_id)

    def test_ausgefallene_quelle_nennt_ihren_grund(self):
        """Eine Sektion, die sagt warum, ist eine Aussage; eine leere ist ein Fehler."""
        out = rb.sec_sea(self._lauf())
        self.assertIn("Kein Zugang zum Werbekonto", out)
        self.assertNotIn("<table", out)

    def test_luecken_zeigen_nur_was_gefehlt_hat(self):
        out = rb.sec_gaps(self._lauf())
        self.assertIn("Google Ads", out)
        self.assertNotIn("Shopify Admin", out)

    def test_der_eigene_ausbaustand_steht_nicht_im_kundendokument(self):
        """"Pull noch nicht gebaut (Stufe 3)" ist der Roadmap-Stand unseres
        Werkzeugs. Der Leser hat Fragen zu seinem Shop."""
        _schreibe(self.ws / "reporting" / "runs" / self.run_id / "state.json", {
            "sources": {"esp": {"status": "skipped",
                                "reason": "Pull noch nicht gebaut"},
                        "gsc": {"status": "failed",
                                "reason": "Dienstkonto nicht eingeladen"}}})
        out = rb.sec_gaps(self._lauf())
        self.assertNotIn("noch nicht gebaut", out)
        self.assertNotIn("E-Mail-Versand", out)
        self.assertIn("Dienstkonto nicht eingeladen", out)

    def test_die_eigenen_abfragekosten_stehen_nicht_drin(self):
        (self.ws / "reporting" / "dfs-ledger.jsonl").write_text(
            '{"run_id": "%s", "cost_usd": 0.53}\n' % self.run_id, encoding="utf-8")
        out = rb.sec_sources(self._lauf())
        self.assertNotIn("USD", out)
        self.assertNotIn("gekostet", out)

    def test_quellen_tragen_werkzeugnamen(self):
        """Der Leser hat Fragen zu seinem Shop, keine zu unseren Schlüsseln."""
        out = rb.sec_sources(self._lauf())
        self.assertIn("Shopify Admin", out)
        self.assertNotIn(">shopify<", out)
        self.assertNotIn("dfs-ledger", out)

    def test_leere_kachel_traegt_ihren_grund(self):
        """"nicht erhoben / gesamter Zeitraum" ist eine leere Aussage."""
        _schreibe(self.ws / "reporting" / "runs" / self.run_id / "state.json", {
            "sources": {"shopify": {"status": "failed",
                                    "reason": "read_all_orders fehlt im Grant"}}})
        k = rb.key_figures(self._lauf())
        self.assertEqual(k["__KPI_REVENUE__"], "nicht erhoben")
        self.assertIn("read_all_orders", k["__KPI_REVENUE_NOTE__"])

    def test_keine_sektion_bricht_ohne_daten(self):
        """Ein Lauf, in dem jede Quelle ausfaellt, rendert trotzdem."""
        run = self._lauf()
        for key, fn in rb.SECTIONS.items():
            with self.subTest(sektion=key):
                out = fn(run)
                self.assertNotIn("None", out)

    def test_die_abschnittsnamen_stimmen_mit_dem_template_ueberein(self):
        """Die Web-Navigation kommt aus der Tabelle, das PDF aus dem Template.

        Laufen sie auseinander, heißt derselbe Abschnitt an zwei Stellen
        verschieden, und niemand merkt es, weil beide für sich rendern.
        """
        import re
        template = (Path(__file__).resolve().parents[2] / "skills" / "audit"
                    / "templates" / "audit.html").read_text(encoding="utf-8")
        aus_template = dict(
            (int(n), t.strip())
            for n, t in re.findall(r"<h2>(\d+) · ([^<]+)</h2>", template))
        for key, (number, title) in rb.SECTION_TITLES.items():
            with self.subTest(sektion=key):
                self.assertEqual(aus_template.get(number), title)

    def test_jeder_marker_hat_einen_bauer(self):
        """Ein Marker ohne Funktion bliebe als Kommentar im fertigen PDF stehen."""
        template = (Path(__file__).resolve().parents[2] / "skills" / "audit"
                    / "templates" / "audit.html").read_text(encoding="utf-8")
        import re
        marker = set(re.findall(r"<!-- SECTION:(\w+) -->", template))
        gebaut = set(rb.SECTIONS) | {"measures"}
        self.assertEqual(marker, gebaut)


class TestAnalyticsPurchases(unittest.TestCase):
    """Käufe aus Analytics kommen aus `purchases`, Umsatz nur in Euro.

    Bis zum 11.09.2026 las der Report `transactions`, und darin zählt GA4
    Refunds mit. Ältere Snapshots tragen nur dieses Feld; ihre Conversion Rate
    steht als nicht messbar da, statt Refunds als Käufe zu zeigen.
    """

    RUN_ID = "2026-10-01-audit"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)
        _schreibe(self.ws / "reporting" / "config.json", {"brand": "Beispielshop"})

    def run_with(self, ga4_extra=None, month_row=None):
        """Zwei volle Jahre Shop und Analytics, 100 Bestellungen je Monat."""
        months = rb.window_mod.months("2026-08", 24)
        data = self.ws / "reporting" / "data" / self.RUN_ID
        _schreibe(data / "shopify.json", {
            "period": {"start": "2024-09-01", "end": "2026-08-31"},
            "by_month": [{"month": m, "total_sales": 10_000.0, "net_sales": 8_000.0,
                          "orders": 100} for m in months]})
        row = month_row or {"purchases": 95, "purchase_revenue": 9_000.0}
        _schreibe(data / "ga4.json", {
            "period": {"start": "2024-09-01", "end": "2026-08-31",
                       "granularity": "max_history"},
            "currency": "EUR",
            "by_month": [{"month": m, "sessions": 5_000, **row} for m in months],
            **(ga4_extra or {})})
        return rb.Run(self.ws, self.RUN_ID)

    def test_channel_conversion_comes_from_purchases(self):
        run = self.run_with({"channels": [
            {"channel": "Direct", "sessions": 1_000, "purchase_revenue": 5_000.0,
             "purchases": 17, "transactions": 23}]})
        out = rb.sec_traffic(run)
        self.assertIn(rb.percent(0.017, 2), out)
        self.assertNotIn(rb.percent(0.023, 2), out)

    def test_a_channel_with_only_transactions_is_not_measurable(self):
        run = self.run_with({"channels": [
            {"channel": "Direct", "sessions": 1_000, "purchase_revenue": 5_000.0,
             "transactions": 23}]})
        out = rb.sec_traffic(run)
        self.assertIn("nicht messbar", out)
        self.assertNotIn(rb.percent(0.023, 2), out)

    def test_device_conversion_comes_from_purchases(self):
        run = self.run_with({
            "funnel": {"sessions": 5_000, "view_item": {"events": 3_000, "sessions": 2_000},
                       "purchase": {"events": 100, "sessions": 100}},
            "devices": [{"device": "mobile", "sessions": 1_000,
                         "purchase_revenue": 5_000.0, "purchases": 17,
                         "transactions": 23}]})
        out = rb.sec_conversion(run)
        self.assertIn(rb.percent(0.017, 2), out)
        self.assertNotIn(rb.percent(0.023, 2), out)

    def test_the_order_gap_counts_purchases(self):
        run = self.run_with(month_row={"purchases": 90, "transactions": 120,
                                       "purchase_revenue": 9_000.0})
        out = rb.sec_measurement(run)
        self.assertIn(rb.num_de(90 * 12), out)
        self.assertIn(rb.percent(1 - 1_080 / 1_200), out)

    def test_the_revenue_gap_needs_analytics_in_euro(self):
        # Eine Property kann in Dollar berichten, während der Shop in Euro
        # bucht. Die Lücke wäre dann um den Wechselkurs verschoben und stünde
        # trotzdem mit Euro-Zeichen im Report.
        out = rb.sec_measurement(self.run_with({"currency": "USD"}))
        self.assertNotIn("Zuordnungslücke Umsatz", out)
        self.assertIn("Zuordnungslücke Bestellungen", out)

    def test_without_a_known_currency_the_revenue_gap_is_left_out(self):
        # Snapshots vor dem 11.09.2026 tragen keine Währung.
        out = rb.sec_measurement(self.run_with({"currency": None}))
        self.assertNotIn("Zuordnungslücke Umsatz", out)

    def test_the_revenue_gap_stays_for_analytics_in_euro(self):
        out = rb.sec_measurement(self.run_with())
        self.assertIn("Zuordnungslücke Umsatz", out)


class TestAnalyticsRevenueCurrency(unittest.TestCase):
    """Umsätze aus Analytics stehen in der Berichtswährung der Property.

    Bis zum 12.09.2026 stand jeder Umsatz aus ga4.json mit Euro-Zeichen im
    Report, auch aus einer Property, die in USD berichtet. Umsätze aus dem
    Shop bleiben in Euro.
    """

    RUN_ID = "2026-10-01-audit"
    CHANNELS = [{"channel": "Direct", "sessions": 1_000, "purchase_revenue": 5_000.0,
                 "purchases": 17}]
    LANDING_PAGES = [{"landing_page": "/", "sessions": 800, "engagement_rate": 0.5,
                      "purchase_revenue": 1_234.0}]
    DEVICES = [{"device": "mobile", "sessions": 1_000, "purchase_revenue": 5_000.0,
                "purchases": 17}]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)
        _schreibe(self.ws / "reporting" / "config.json", {"brand": "Beispielshop"})

    def run_with(self, ga4_extra, shop_extra=None):
        """Zwei volle Jahre Shop und Analytics wie in TestAnalyticsPurchases.

        Die Währung steht nur in `ga4_extra`, damit jeder Test sie selbst setzt.
        """
        months = rb.window_mod.months("2026-08", 24)
        data = self.ws / "reporting" / "data" / self.RUN_ID
        _schreibe(data / "shopify.json", {
            "period": {"start": "2024-09-01", "end": "2026-08-31"},
            "by_month": [{"month": m, "total_sales": 10_000.0, "net_sales": 8_000.0,
                          "orders": 100} for m in months],
            **(shop_extra or {})})
        _schreibe(data / "ga4.json", {
            "period": {"start": "2024-09-01", "end": "2026-08-31",
                       "granularity": "max_history"},
            "by_month": [{"month": m, "sessions": 5_000, "purchases": 95,
                          "purchase_revenue": 9_000.0} for m in months],
            **ga4_extra})
        return rb.Run(self.ws, self.RUN_ID)

    def test_traffic_revenue_carries_a_foreign_currency_code(self):
        out, _ = _render(rb.sec_traffic, self.run_with({
            "currency": "USD", "channels": self.CHANNELS,
            "landing_pages": self.LANDING_PAGES}))
        self.assertNotIn("€", out)
        # Einmal im Diagramm, einmal in der Kanal-Tabelle.
        self.assertEqual(out.count(rb.num_de(5_000, 0, " USD")), 2)
        self.assertIn(rb.num_de(1_234, 0, " USD"), out)

    def test_device_revenue_carries_a_foreign_currency_code(self):
        out, _ = _render(rb.sec_conversion, self.run_with({
            "currency": "USD", "devices": self.DEVICES}))
        self.assertNotIn("€", out)
        self.assertIn(rb.num_de(5_000, 0, " USD"), out)

    def test_revenue_in_euro_keeps_the_euro_sign(self):
        run = self.run_with({"currency": "EUR", "channels": self.CHANNELS,
                             "devices": self.DEVICES})
        for section in (rb.sec_traffic, rb.sec_conversion):
            with self.subTest(section=section.__name__):
                out, _ = _render(section, run)
                self.assertIn(rb.num_de(5_000, 0, " €"), out)

    def test_without_a_currency_the_amount_stands_without_a_unit(self):
        # Snapshots vor dem 11.09.2026 tragen keine Währung. Euro anzunehmen
        # wäre bei einer Property in USD genau der Fehler, um den es hier geht.
        run = self.run_with({"currency": None, "channels": self.CHANNELS,
                             "devices": self.DEVICES})
        for section in (rb.sec_traffic, rb.sec_conversion):
            with self.subTest(section=section.__name__):
                out, _ = _render(section, run)
                self.assertNotIn("€", out)
                self.assertIn(f">{rb.num_de(5_000)}<", out)

    def test_without_a_currency_the_build_warns(self):
        run = self.run_with({"currency": None, "channels": self.CHANNELS})
        _, err = _render(rb.sec_traffic, run)
        self.assertIn("Währung", err)

    def test_shop_revenue_stays_in_euro(self):
        run = self.run_with({"currency": "USD", "devices": self.DEVICES},
                            shop_extra={"abandoned_checkouts": {
                                "count": 12, "total_value": 3_456.0}})
        out, _ = _render(rb.sec_conversion, run)
        self.assertIn(rb.num_de(3_456, 0, " €"), out)

    def test_a_currency_code_column_is_aligned_as_a_number(self):
        out = rb.table(["Kanal", "Umsatz"],
                       [("Direkt", rb.num_de(5_000, 0, " USD")),
                        ("Suche", rb.num_de(1_234, 0, " USD"))])
        header = out[out.index("<thead>"):out.index("</thead>")]
        self.assertEqual(header.count('class="num"'), 1)


class TestAnalyticsVariants(unittest.TestCase):
    """Die GA4-Tabellen zeigen die Zahlen, auf denen die Befunde stehen.

    Seit dem 13.09.2026 rechnen die Analysen ohne auffälliges Bot-Profil
    (`bot_profiles.without`) und, wo ein zweiter Absender dieselben Ereignisse
    meldet, mit denen des ersten (`primary_sender`). Der Report las bis zum
    15.09.2026 weiter den Hauptteil von ga4.json und druckte neben diesen
    Befunden Kanalanteile und einen Kaufweg, deren erste Stufen zur Hälfte Bots
    waren. Jede Tabelle sagt deshalb, welche Zahlen sie zeigt.
    """

    RUN_ID = "2026-10-01-audit"
    FUNNEL = {"view_item": 5_000, "add_to_cart": 250, "view_cart": 270,
              "begin_checkout": 110, "purchase": 92}
    FIRST_SENDER = {
        "funnel": {"view_item": {"events": 2_400, "sessions": 2_400},
                   "purchase": {"events": 46, "sessions": 46}},
        "channels": [{"channel": "Direct", "purchases": 6, "purchase_revenue": 600.0},
                     {"channel": "Organic Search", "purchases": 40,
                      "purchase_revenue": 4_000.0}],
        "devices": [{"device": "desktop", "purchases": 10, "purchase_revenue": 1_000.0},
                    {"device": "mobile", "purchases": 36, "purchase_revenue": 3_600.0}],
    }

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)
        _schreibe(self.ws / "reporting" / "config.json", {"brand": "Beispielshop"})

    @staticmethod
    def block(channels, devices, funnel, landing_pages):
        """Ein Block, wie ihn der GA4-Pull für den Hauptteil und für `without` baut."""
        total = sum(sessions for _, sessions, _, _ in channels)
        return {
            "totals": {"sessions": total},
            "channels": [{"channel": c, "sessions": s, "purchases": p, "purchase_revenue": u}
                         for c, s, p, u in channels],
            "devices": [{"device": d, "sessions": s, "purchases": p, "purchase_revenue": u}
                        for d, s, p, u in devices],
            "funnel": dict({"sessions": total},
                           **{k: {"events": v, "sessions": v} for k, v in funnel.items()}),
            "landing_pages": [{"landing_page": lp, "sessions": s, "engagement_rate": e,
                               "purchases": p, "purchase_revenue": u}
                              for lp, s, e, p, u in landing_pages],
        }

    def all_sessions(self):
        """Alle Sitzungen: das Bot-Profil trägt die Hälfte, über Direkt und Desktop."""
        return self.block(
            [("Direct", 6_000, 12, 1_200.0), ("Organic Search", 4_000, 80, 8_000.0)],
            [("desktop", 7_000, 20, 2_000.0), ("mobile", 3_000, 72, 7_200.0)],
            self.FUNNEL,
            [("/bot-einstieg", 5_000, 0.02, 0, 0.0), ("/", 3_000, 0.45, 60, 6_000.0)])

    def without_bot_profile(self):
        return self.block(
            [("Direct", 1_000, 12, 1_200.0), ("Organic Search", 4_000, 80, 8_000.0)],
            [("desktop", 2_000, 20, 2_000.0), ("mobile", 3_000, 72, 7_200.0)],
            dict(self.FUNNEL, view_item=2_600),
            [("/", 3_000, 0.45, 60, 6_000.0), ("/kategorie", 900, 0.38, 20, 2_000.0)])

    def run_with(self, ga4_extra):
        """Zwei volle Jahre Shop und Analytics wie in TestAnalyticsPurchases."""
        months = rb.window_mod.months("2026-08", 24)
        data = self.ws / "reporting" / "data" / self.RUN_ID
        _schreibe(data / "shopify.json", {
            "period": {"start": "2024-09-01", "end": "2026-08-31"},
            "by_month": [{"month": m, "total_sales": 10_000.0, "net_sales": 8_000.0,
                          "orders": 100} for m in months]})
        _schreibe(data / "ga4.json", {
            "period": {"start": "2024-09-01", "end": "2026-08-31",
                       "granularity": "max_history"},
            "currency": "EUR",
            "by_month": [{"month": m, "sessions": 5_000, "purchases": 95,
                          "purchase_revenue": 9_000.0} for m in months],
            **self.all_sessions(), **ga4_extra})
        return rb.Run(self.ws, self.RUN_ID)

    def with_bot_profile(self, without_extra=None, **ga4_extra):
        without = dict(self.without_bot_profile(), filter=["Geräteprofil"],
                       **(without_extra or {}))
        return self.run_with({"bot_profiles": {"checked": True, "without": without},
                              **ga4_extra})

    @staticmethod
    def double_counted(*events):
        return {"senders": {"measurable": True, "double_counted_events": list(events)}}

    def test_channel_table_comes_from_the_block_without_bot_profiles(self):
        """Direkt trägt mit dem Profil 60 Prozent der Sitzungen, ohne es 20."""
        out = rb.sec_traffic(self.with_bot_profile())
        self.assertIn(rb.percent(0.2), out)
        self.assertNotIn(rb.percent(0.6), out)
        self.assertIn(rb.percent(0.012, 2), out)
        self.assertNotIn(rb.percent(0.002, 2), out)

    def test_landing_pages_come_from_the_block_without_bot_profiles(self):
        out = rb.sec_traffic(self.with_bot_profile())
        self.assertIn("/kategorie", out)
        self.assertNotIn("/bot-einstieg", out)

    def test_purchase_path_comes_from_the_block_without_bot_profiles(self):
        """Die Produktansicht steht ohne Profil gegen 5.000 Sitzungen, nicht 10.000."""
        out = rb.sec_conversion(self.with_bot_profile())
        self.assertIn(rb.percent(0.52), out)
        self.assertNotIn(rb.percent(0.5), out)

    def test_device_conversion_comes_from_the_block_without_bot_profiles(self):
        out = rb.sec_conversion(self.with_bot_profile())
        self.assertIn(rb.percent(0.01, 2), out)
        self.assertNotIn(rb.percent(20 / 7_000, 2), out)

    def test_every_table_says_it_shows_numbers_without_bot_profiles(self):
        """Kanäle und Einstiegsseiten, Kaufweg und Geräte: je eine Angabe."""
        run = self.with_bot_profile()
        for section in (rb.sec_traffic, rb.sec_conversion):
            with self.subTest(section=section.__name__):
                out = section(run)
                self.assertEqual(out.count("ohne Bot-Profil"), 2)
                self.assertNotIn("nur erster Absender", out)

    def test_double_counted_purchases_come_from_the_first_sender(self):
        """Direkt: 6 Käufe des ersten Absenders auf 1.000 Sitzungen, nicht 12."""
        run = self.with_bot_profile({"primary_sender": self.FIRST_SENDER},
                                    **self.double_counted("purchase"))
        out = rb.sec_traffic(run)
        self.assertIn(rb.percent(0.006, 2), out)
        self.assertNotIn(rb.percent(0.012, 2), out)
        self.assertIn(rb.num_de(600, 0, " €"), out)
        self.assertNotIn(rb.num_de(1_200, 0, " €"), out)
        self.assertEqual(out.count("nur erster Absender"), 1)

    def test_landing_page_revenue_is_not_shown_while_purchases_count_twice(self):
        """Je Einstiegsseite gibt es keine Käufe des ersten Absenders, also
        keine bereinigte Zahl. Die doppelt gezählte wäre falsch."""
        run = self.with_bot_profile({"primary_sender": self.FIRST_SENDER},
                                    **self.double_counted("purchase"))
        out = rb.sec_traffic(run)
        self.assertNotIn(rb.num_de(6_000, 0, " €"), out)
        self.assertIn("nicht messbar", out)
        self.assertNotIn("Ab dem nächsten Lauf", out)

    def test_double_counted_device_purchases_come_from_the_first_sender(self):
        run = self.with_bot_profile({"primary_sender": self.FIRST_SENDER},
                                    **self.double_counted("purchase"))
        out = rb.sec_conversion(run)
        self.assertIn(rb.percent(0.005, 2), out)
        self.assertNotIn(rb.percent(0.01, 2), out)

    def test_a_double_counted_step_counts_the_first_sender_sessions(self):
        run = self.with_bot_profile({"primary_sender": self.FIRST_SENDER},
                                    **self.double_counted("view_item", "purchase"))
        out = rb.sec_conversion(run)
        self.assertIn(rb.percent(0.48), out)
        self.assertNotIn(rb.percent(0.52), out)
        self.assertEqual(out.count("nur erster Absender"), 2)

    def test_first_sender_without_a_bot_profile(self):
        """Ein zweiter Absender ohne Bot-Profil: Hauptteil, Käufe vom ersten."""
        run = self.run_with(dict(self.double_counted("purchase"), primary_sender={
            "channels": [{"channel": "Direct", "purchases": 3, "purchase_revenue": 300.0}]}))
        out = rb.sec_traffic(run)
        self.assertIn(rb.percent(0.0005, 2), out)
        self.assertIn("nur erster Absender", out)
        self.assertNotIn("ohne Bot-Profil", out)

    def test_purchases_counted_twice_without_first_sender_numbers_are_not_measurable(self):
        """Mehrere Mess-IDs mit zweitem Absender, oder die Abfrage scheiterte:
        dann gibt es keine bereinigte Zahl (senders.primary_sender)."""
        run = self.with_bot_profile(**self.double_counted("purchase"))
        for section, rate, revenue in ((rb.sec_traffic, rb.percent(0.012, 2), 1_200),
                                       (rb.sec_conversion, rb.percent(0.01, 2), 2_000)):
            with self.subTest(section=section.__name__):
                out = section(run)
                self.assertNotIn(rate, out)
                self.assertNotIn(rb.num_de(revenue, 0, " €"), out)
                self.assertIn("nicht messbar", out)
                self.assertNotIn("nur erster Absender", out)
                self.assertNotIn("Ab dem nächsten Lauf", out)

    def test_without_findings_from_the_checks_the_tables_stay_as_they_are(self):
        """Ohne `--audit-checks` oder ohne Treffer rendert alles wie bisher.

        Schützt bestehendes Verhalten und läuft deshalb schon vor der Änderung grün."""
        for extra in ({}, {"bot_profiles": {"checked": True, "profiles": []},
                           "senders": {"measurable": True, "double_counted_events": []}}):
            with self.subTest(extra=extra):
                run = self.run_with(extra)
                traffic, conversion = rb.sec_traffic(run), rb.sec_conversion(run)
                self.assertIn(rb.percent(0.6), traffic)
                self.assertIn("/bot-einstieg", traffic)
                self.assertIn(rb.percent(0.5), conversion)
                for out in (traffic, conversion):
                    self.assertNotIn("ohne Bot-Profil", out)
                    self.assertNotIn("nur erster Absender", out)


class TestCleanedAnalyticsOnCoverAndOrderGap(unittest.TestCase):
    """Deckblatt und Zuordnungslücke rechnen nicht mit Bots und doppelten Käufen.

    Seit dem 15.09.2026 zeigen die Tabellen zu Traffic und Kaufweg die Zahlen
    ohne Bot-Profil und doppelt gezählte Käufe nur vom ersten Absender
    (TestAnalyticsVariants). Deckblatt und Zuordnungslücke rechnen dagegen über
    das Auswertungsfenster aus der Monatsreihe von ga4.json, und die gibt es
    nur für alle Sitzungen. Eine bereinigte Zahl für das Fenster gibt es damit
    nicht, also steht dort "nicht messbar" mit dem Grund.
    """

    RUN_ID = "2026-10-01-audit"
    #: Ein erkanntes Bot-Profil. Der Block ohne das Profil hat keine Monatsreihe.
    BOT_PROFILE = {"bot_profiles": {"checked": True, "without": {
        "totals": {"sessions": 30_000}, "filter": ["Geräteprofil"]}}}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)
        _schreibe(self.ws / "reporting" / "config.json", {"brand": "Beispielshop"})

    def run_with(self, ga4_extra=None, shop_sessions=False):
        """Zwei volle Jahre: im Shop 100 Bestellungen je Monat, in Analytics
        5.000 Sitzungen, 95 Käufe und 9.000 € Umsatz. Mit `shop_sessions` zählt
        der Shop selbst 4.000 Sitzungen je Monat."""
        months = rb.window_mod.months("2026-08", 24)
        data = self.ws / "reporting" / "data" / self.RUN_ID
        shop = {"period": {"start": "2024-09-01", "end": "2026-08-31"},
                "by_month": [{"month": m, "total_sales": 10_000.0, "net_sales": 8_000.0,
                              "orders": 100} for m in months]}
        if shop_sessions:
            shop["sessions_by_month"] = [{"month": m, "sessions": 4_000} for m in months]
        _schreibe(data / "shopify.json", shop)
        _schreibe(data / "ga4.json", {
            "period": {"start": "2024-09-01", "end": "2026-08-31",
                       "granularity": "max_history"},
            "currency": "EUR",
            "by_month": [{"month": m, "sessions": 5_000, "purchases": 95,
                          "purchase_revenue": 9_000.0} for m in months],
            **(ga4_extra or {})})
        return rb.Run(self.ws, self.RUN_ID)

    @staticmethod
    def double_counted(*events, onset="2026-03-02"):
        return {"senders": {"measurable": True, "onset": onset,
                            "double_counted_events": list(events)}}

    @staticmethod
    def cell(out, label):
        """Der Wert in der Zeile `label` eines Zahlenblocks, oder None."""
        found = re.search(rf"<tr><td>{re.escape(label)}</td><td[^>]*>([^<]*)</td>", out)
        return found.group(1) if found else None

    def test_the_conversion_tile_is_not_measurable_on_analytics_sessions_with_a_bot_profile(self):
        # 1.200 Bestellungen durch 60.000 Sitzungen, von denen ein Teil Bots
        # sind: 2,00 Prozent stünden zu niedrig da.
        k = rb.key_figures(self.run_with(self.BOT_PROFILE))
        self.assertEqual(k["__KPI_CR__"], "nicht messbar")
        self.assertIn("Bot-Profil", k["__KPI_CR_NOTE__"])

    def test_the_sessions_tile_is_not_measurable_on_analytics_sessions_with_a_bot_profile(self):
        k = rb.key_figures(self.run_with(self.BOT_PROFILE))
        self.assertEqual(k["__KPI_SESSIONS__"], "nicht messbar")
        self.assertIn("Bot-Profil", k["__KPI_SESSIONS_NOTE__"])

    def test_shop_sessions_keep_both_tiles_and_name_the_bot_profile_in_analytics(self):
        k = rb.key_figures(self.run_with(self.BOT_PROFILE, shop_sessions=True))
        self.assertEqual(k["__KPI_CR__"], rb.percent(1_200 / 48_000, 2))
        self.assertEqual(k["__KPI_SESSIONS__"], rb.num_de(48_000))
        note = k["__KPI_SESSIONS_NOTE__"]
        self.assertIn(rb.num_de(60_000), note)
        self.assertIn("Bot-Profil", note)

    def test_without_a_flagged_profile_the_tiles_stay_as_they_are(self):
        """Schützt bestehendes Verhalten und läuft deshalb schon vor der Änderung grün."""
        k = rb.key_figures(self.run_with({"bot_profiles": {"checked": True, "profiles": []}}))
        self.assertEqual(k["__KPI_CR__"], rb.percent(1_200 / 60_000, 2))
        self.assertEqual(k["__KPI_SESSIONS__"], rb.num_de(60_000))
        self.assertNotIn("Bot-Profil", k["__KPI_SESSIONS_NOTE__"])

    def test_the_order_gap_is_not_measurable_while_purchases_count_twice(self):
        # 1.140 Kaufereignisse gegen 1.200 Bestellungen wären 5,0 Prozent
        # Lücke, und ein Teil der Kaufereignisse ist doppelt gezählt.
        out = rb.sec_measurement(self.run_with(self.double_counted("purchase")))
        self.assertEqual(self.cell(out, "Zuordnungslücke Bestellungen"), "nicht messbar")
        self.assertNotIn(rb.percent(1 - 1_140 / 1_200), out)
        self.assertIn("02.03.2026", out)

    def test_the_revenue_gap_is_not_measurable_while_purchases_count_twice(self):
        out = rb.sec_measurement(self.run_with(self.double_counted("purchase")))
        self.assertEqual(self.cell(out, "Zuordnungslücke Umsatz"), "nicht messbar")
        self.assertNotIn(rb.percent(1 - 108_000 / 120_000), out)

    def test_the_gaps_stay_when_only_other_events_count_twice(self):
        """Schützt bestehendes Verhalten und läuft deshalb schon vor der Änderung grün."""
        out = rb.sec_measurement(self.run_with(self.double_counted("view_item")))
        self.assertEqual(self.cell(out, "Zuordnungslücke Bestellungen"),
                         rb.percent(1 - 1_140 / 1_200))
        self.assertEqual(self.cell(out, "Zuordnungslücke Umsatz"),
                         rb.percent(1 - 108_000 / 120_000))


class TestAdsCurrency(unittest.TestCase):
    """Beträge aus Google Ads stehen in der Währung des Kontos.

    Bis zum 13.09.2026 standen Kosten und Umsatz aus ads.json mit Euro-Zeichen
    im Report und der ROAS als "Rückfluss je Euro", auch für ein Konto in
    Franken. Der Pull legt die Kontowährung als `currency` in den Snapshot.
    """

    RUN_ID = "2026-10-01-audit"
    # Zwei Monate, wie pull-ads sie in `by_month` schreibt: zusammen 2.000
    # Kosten, 900 Klicks und 7.654 Umsatz, also ROAS 3,83. Bis zum 15.09.2026
    # stand hier `totals`, ein Feld, das der Pull nie schreibt (TestAdsTotals).
    BY_MONTH = [
        {"month": "2026-07", "clicks": 400, "cost": 800.0,
         "conversions_value": 3_054.0, "roas": 3.82},
        {"month": "2026-08", "clicks": 500, "cost": 1_200.0,
         "conversions_value": 4_600.0, "roas": 3.83},
    ]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)
        _schreibe(self.ws / "reporting" / "config.json", {"brand": "Beispielshop"})

    def run_with(self, currency):
        """Ein Werbekonto mit zwei Monaten, die Währung setzt jeder Test selbst.

        Ohne Shop und Analytics meldet Run auf stderr, dass es kein
        Auswertungsfenster gibt. sec_sea zählt dann jeden Monat des Snapshots,
        und die Meldung bleibt aus der Testausgabe.
        """
        _schreibe(self.ws / "reporting" / "data" / self.RUN_ID / "ads.json", {
            "source": "ads",
            "period": {"start": "2024-09-01", "end": "2026-08-31"},
            "currency": currency, "by_month": self.BY_MONTH})
        with contextlib.redirect_stderr(io.StringIO()):
            return rb.Run(self.ws, self.RUN_ID)

    def test_amounts_carry_a_foreign_currency_code(self):
        out, _ = _render(rb.sec_sea, self.run_with("CHF"))
        self.assertNotIn("€", out)
        self.assertIn(rb.num_de(2_000, 0, " CHF"), out)
        self.assertIn(rb.num_de(7_654, 0, " CHF"), out)

    def test_amounts_in_euro_keep_the_euro_sign(self):
        out, _ = _render(rb.sec_sea, self.run_with("EUR"))
        self.assertIn(rb.num_de(2_000, 0, " €"), out)
        self.assertIn(rb.num_de(7_654, 0, " €"), out)

    def test_without_a_currency_the_amounts_stand_without_a_unit(self):
        # Euro anzunehmen wäre bei einem Konto in Franken genau der Fehler,
        # um den es hier geht.
        out, _ = _render(rb.sec_sea, self.run_with(None))
        self.assertNotIn("€", out)
        self.assertIn(f">{rb.num_de(2_000)}<", out)
        self.assertIn(f">{rb.num_de(7_654)}<", out)

    def test_without_a_currency_the_build_warns_and_names_the_file(self):
        _, err = _render(rb.sec_sea, self.run_with(None))
        self.assertIn("Währung", err)
        self.assertIn("ads.json", err)

    def test_the_return_on_ad_spend_is_named_roas(self):
        # "Rückfluss je Euro" nennt eine Währung, die das Konto nicht haben
        # muss. Im Report heißt die Kennzahl ROAS (skills/audit/SKILL.md,
        # Wie eine Kennzahl heißt).
        out, _ = _render(rb.sec_sea, self.run_with("CHF"))
        self.assertIn(">ROAS<", out)
        self.assertNotIn("Euro", out)
        self.assertIn(rb.num_de(3.83, 2, " x"), out)


class TestAdsTotals(unittest.TestCase):
    """Kosten, Klicks, Umsatz und ROAS entstehen aus der Monatsreihe des Pulls.

    Bis zum 15.09.2026 las sec_sea `totals` aus ads.json, und dieses Feld
    schreibt pull-ads nicht. Auf jedem echten Snapshot stand deshalb in allen
    vier Zeilen "nicht erhoben", und der Build meldete das nur als tote Spalte
    auf stderr. Gezählt werden die Monate des Auswertungsfensters, wie im
    Handel und auf den Kacheln.
    """

    RUN_ID = "2026-10-01-audit"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)
        self.data = self.ws / "reporting" / "data" / self.RUN_ID
        _schreibe(self.ws / "reporting" / "config.json", {"brand": "Beispielshop"})

    @staticmethod
    def month(month, cost, clicks, value):
        """Ein Monat mit den Feldern, die ads_pull.by_month schreibt."""
        return {"month": month, "impressions": 20 * clicks, "clicks": clicks,
                "cost": cost, "conversions": 1.0 if value else 0.0,
                "conversions_value": value,
                "roas": round(value / cost, 2) if cost else None,
                "search_impression_share": 0.5,
                "search_budget_lost_impression_share": 0.2,
                "search_rank_lost_impression_share": 0.3}

    def run_with(self, months, period=("2024-09-01", "2026-09-14"), window=False):
        """Ein Snapshot mit genau den Blöcken aus ads_pull.py, also ohne `totals`.

        Mit `window` liegen zwei volle Jahre Shop und Analytics daneben wie in
        TestAnalyticsRevenueCurrency, und das Auswertungsfenster läuft von
        09/2025 bis 08/2026. Ohne sie meldet Run auf stderr, dass es kein
        Fenster gibt, und die Meldung bleibt aus der Testausgabe.
        """
        _schreibe(self.data / "ads.json", {
            "source": "ads",
            "period": {"start": period[0], "end": period[1],
                       "granularity": "max_history"},
            "currency": "EUR", "history_from": period[0],
            "by_month": months,
            "campaigns": [], "campaigns_truncated": False,
            "summary_campaigns": {"campaigns_total": 0},
            "summary_search_terms": {"search_terms_total": 0,
                                     "terms_without_conversion": 0,
                                     "cost_without_conversion": 0.0},
            "search_terms_without_conversion": [],
            "search_terms_truncated": False})
        if window:
            shop_months = rb.window_mod.months("2026-08", 24)
            _schreibe(self.data / "shopify.json", {
                "period": {"start": "2024-09-01", "end": "2026-08-31"},
                "by_month": [{"month": m, "total_sales": 10_000.0,
                              "net_sales": 8_000.0, "orders": 100}
                             for m in shop_months]})
            _schreibe(self.data / "ga4.json", {
                "period": {"start": "2024-09-01", "end": "2026-08-31"},
                "by_month": [{"month": m, "sessions": 5_000, "purchases": 95,
                              "purchase_revenue": 9_000.0} for m in shop_months]})
        with contextlib.redirect_stderr(io.StringIO()):
            return rb.Run(self.ws, self.RUN_ID)

    @staticmethod
    def value(out, label):
        """Der Wert in der Zeile `label` des Zahlenblocks, oder None."""
        found = re.search(rf"<tr><td>{re.escape(label)}</td><td[^>]*>([^<]*)</td>", out)
        return found.group(1) if found else None

    def test_the_numbers_come_from_the_monthly_series(self):
        out, err = _render(rb.sec_sea, self.run_with([
            self.month("2026-07", 800.0, 400, 3_054.0),
            self.month("2026-08", 1_200.0, 500, 4_600.0)]))
        self.assertEqual(self.value(out, "Kosten"), rb.num_de(2_000, 0, " €"))
        self.assertEqual(self.value(out, "Klicks"), rb.num_de(900))
        self.assertEqual(self.value(out, "Umsatz"), rb.num_de(7_654, 0, " €"))
        self.assertEqual(self.value(out, "ROAS"), rb.num_de(7_654 / 2_000, 2, " x"))
        # Die Warnung über eine tote Spalte war das einzige Zeichen des Fehlers.
        self.assertNotIn("Warnung", err)

    def test_only_the_months_of_the_audit_window_count(self):
        # Das Fenster läuft von 09/2025 bis 08/2026. Der Monat davor und der
        # angebrochene Monat danach bleiben draußen.
        out, _ = _render(rb.sec_sea, self.run_with([
            self.month("2025-08", 1_000.0, 100, 9_000.0),
            self.month("2025-09", 300.0, 30, 900.0),
            self.month("2026-08", 200.0, 20, 1_100.0),
            self.month("2026-09", 5_000.0, 500, 1.0)], window=True))
        self.assertEqual(self.value(out, "Kosten"), rb.num_de(500, 0, " €"))
        self.assertEqual(self.value(out, "Klicks"), rb.num_de(50))
        self.assertEqual(self.value(out, "Umsatz"), rb.num_de(2_000, 0, " €"))
        self.assertEqual(self.value(out, "ROAS"), rb.num_de(4, 2, " x"))

    def test_roas_is_the_value_over_the_cost_not_the_mean_of_the_months(self):
        # Die Monate stehen bei 10,00 und 1,00, im Mittel 5,50. Über den
        # Zeitraum bringen 1.000 Kosten 1.900 Umsatz, also 1,90.
        out, _ = _render(rb.sec_sea, self.run_with([
            self.month("2026-07", 100.0, 10, 1_000.0),
            self.month("2026-08", 900.0, 90, 900.0)]))
        self.assertEqual(self.value(out, "ROAS"), rb.num_de(1.9, 2, " x"))

    def test_without_cost_the_roas_stays_unmeasured(self):
        # Ohne Ausgaben hat der Zeitraum keinen ROAS. Eine 0 läse sich als
        # "nichts eingebracht" (skills/pull-ads/SKILL.md, agents/audit-sea.md).
        out, _ = _render(rb.sec_sea, self.run_with([
            self.month("2026-08", 0.0, 0, 0.0)]))
        self.assertEqual(self.value(out, "Kosten"), rb.num_de(0, 0, " €"))
        self.assertEqual(self.value(out, "ROAS"), "nicht erhoben")

    def test_the_period_is_the_audit_window_as_a_range(self):
        out, _ = _render(rb.sec_sea, self.run_with([
            self.month("2026-08", 200.0, 20, 1_100.0)], window=True))
        self.assertIn("Zeitraum: 09/2025 bis 08/2026", out)

    def test_without_a_window_the_period_is_the_whole_snapshot(self):
        out, _ = _render(rb.sec_sea, self.run_with([
            self.month("2026-08", 200.0, 20, 1_100.0)]))
        self.assertIn("Zeitraum: 01.09.2024 bis 14.09.2026", out)

    def test_without_a_month_in_the_window_nothing_is_claimed(self):
        # Ein Snapshot, der das Fenster nicht abdeckt, sagt über das Fenster
        # nichts. Eine 0 behauptete zwölf Monate ohne Ausgaben.
        out, _ = _render(rb.sec_sea, self.run_with([
            self.month("2024-10", 300.0, 30, 900.0)],
            period=("2024-10-01", "2024-10-31"), window=True))
        for label in ("Kosten", "Klicks", "Umsatz", "ROAS"):
            with self.subTest(label=label):
                self.assertEqual(self.value(out, label), "nicht erhoben")


class TestTextfelder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pfad = Path(self.tmp.name) / "report-text.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_ein_leeres_feld_bricht_ab(self):
        """Ein Dokument mit leerem Einstieg geht nie an einen Kunden."""
        doc = {k: "gefüllt" for k in rb.TEXT_FIELDS}
        doc["intro"] = "   "
        _schreibe(self.pfad, doc)
        with self.assertRaises(SystemExit) as ctx:
            rb.text_laden(self.pfad)
        self.assertIn("intro", str(ctx.exception))

    def test_alle_felder_haben_einen_hinweis(self):
        """Wer die Vorlage füllt, braucht zu jedem Feld die Regel daneben."""
        self.assertEqual(set(rb.TEXT_FIELDS), set(rb.TEMPLATE_HINTS))


if __name__ == "__main__":
    unittest.main()


class TestLesbarkeit(unittest.TestCase):
    """Die Messung ist ein Regressionstest, kein Qualitätsnachweis."""

    def test_kurzer_text_wird_nicht_gemessen(self):
        from audit import readability
        self.assertIsNone(readability.metrics("Zu kurz."))
        self.assertEqual(readability.check("Zu kurz."), [])

    def test_lange_saetze_werden_gemeldet(self):
        from audit import readability
        text = (" ".join(["Verfuegbarkeitsproblematik"] * 40) + ". ") * 3
        meldungen = readability.check(text)
        self.assertTrue(any("Satzlänge" in m for m in meldungen), meldungen)

    def test_tabellen_und_ueberschriften_zaehlen_nicht_mit(self):
        from audit import readability
        html = ("<h2>Eine Überschrift</h2><table><tr><td>Zahl</td></tr></table>"
                "<p>Dies ist der Fließtext, den die Messung sehen soll.</p>")
        raus = readability.text_aus_html(html)
        self.assertIn("Fließtext", raus)
        self.assertNotIn("Überschrift", raus)
        self.assertNotIn("Zahl", raus)


class TestSektionVertrauen(unittest.TestCase):
    """Die Pflichtangaben-Sektion, und was sie über Abwesenheit sagen darf."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        self.run_id = "2026-10-01-audit"
        (self.ws / "reporting" / "data" / self.run_id).mkdir(parents=True)
        (self.ws / "reporting" / "runs" / self.run_id).mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _lauf(self, pages, url_count=None, budget=None):
        crawl = {"summary": {"url_count": url_count
                             if url_count is not None else len(pages)},
                 "pages": pages}
        (self.ws / "reporting" / "data" / self.run_id / "crawl.json").write_text(
            json.dumps(crawl), encoding="utf-8")
        config = {"brand": "Beispielshop"}
        if budget:
            config["crawl_max_urls"] = budget
        (self.ws / "reporting" / "config.json").write_text(
            json.dumps(config), encoding="utf-8")
        return rb.Run(self.ws, self.run_id)

    def test_a_found_page_is_listed_with_its_address(self):
        run = self._lauf([{"url": "https://beispielshop.test/pages/impressum",
                            "status": 200}])
        out = rb.sec_trust(run)
        self.assertIn("gefunden", out)
        self.assertIn("pages/impressum", out)

    def test_a_page_answering_with_an_error_says_so(self):
        run = self._lauf([{"url": "https://beispielshop.test/agb", "status": 404}])
        self.assertIn("antwortet mit 404", rb.sec_trust(run))

    def test_a_complete_crawl_may_say_a_page_was_not_found(self):
        run = self._lauf([{"url": "https://beispielshop.test/", "status": 200}],
                          url_count=10, budget=3500)
        self.assertIn("im Crawl nicht gefunden", rb.sec_trust(run))

    def test_a_capped_crawl_may_not_claim_absence(self):
        # Der belegte Fall: das Crawl-Budget war ausgeschöpft, gut die
        # Hälfte der Sitemap blieb unbesucht, die Rechtstexte lagen
        # jenseits der Grenze. "Nicht gefunden" hätte dort wie "gibt es nicht"
        # gelesen, in einem Dokument, das der Kunde seinem Anwalt zeigt.
        run = self._lauf([{"url": "https://beispielshop.test/", "status": 200}],
                          url_count=3500, budget=3500)
        out = rb.sec_trust(run)
        self.assertIn("nicht in den erfassten Seiten", out)
        self.assertNotIn("im Crawl nicht gefunden", out)
        self.assertIn("Budget ausgeschöpft", out)

    def test_the_legal_disclaimer_is_always_there(self):
        run = self._lauf([{"url": "https://beispielshop.test/impressum",
                            "status": 200}])
        self.assertIn("keine juristische Prüfung", rb.sec_trust(run))

    def test_english_paths_count_for_a_second_market(self):
        run = self._lauf([{"url": "https://beispielshop.test/en/pages/imprint",
                            "status": 200}])
        self.assertIn("en/pages/imprint", rb.sec_trust(run))

    def test_without_a_crawl_the_section_names_the_reason(self):
        (self.ws / "reporting" / "config.json").write_text("{}", encoding="utf-8")
        out = rb.sec_trust(rb.Run(self.ws, self.run_id))
        self.assertIn("nicht erhoben", out)


class TestErklaerungUndEinordnung(unittest.TestCase):
    """Die zwei Felder, die einen Befund lesbar machen."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        self.run_id = "2026-10-01-audit"
        (self.ws / "reporting" / "data" / self.run_id).mkdir(parents=True)
        self.findings = self.ws / "reporting" / "runs" / self.run_id / "findings"
        self.findings.mkdir(parents=True)
        (self.ws / "reporting" / "config.json").write_text(
            json.dumps({"brand": "Beispielshop"}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _render(self, **felder):
        finding = {"id": "CRO-01", "statement": "Nur 4,7 Prozent führen zum Warenkorb.",
                   "evidence": "ga4.json > funnel", "severity": "hoch",
                   "confidence": "confirmed", "effort": "small"}
        finding.update(felder)
        (self.findings / "conversion.json").write_text(json.dumps(
            {"discipline": "cro", "run_id": self.run_id, "findings": [finding]}),
            encoding="utf-8")
        return rb.finding_blocks(rb.Run(self.ws, self.run_id), "conversion")

    def test_the_explanation_is_rendered(self):
        out = self._render(explanation="Die Add-to-Cart-Rate ist der Anteil der "
                                       "Sessions mit Produktansicht.")
        self.assertIn("Add-to-Cart-Rate ist der Anteil", out)

    def test_the_explanation_survives_a_metrics_table(self):
        # Der Fehler, den diese Felder beheben: bis zum 09.09.2026 verschwand
        # jeder Fliesstext, sobald ein Befund Zahlen trug. Uebrig blieb ein
        # nackter Titel ueber einer Tabelle.
        out = self._render(
            explanation="Die Add-to-Cart-Rate misst den Uebergang zum Warenkorb.",
            metrics=[{"label": "Sessions", "value": "1.500.000", "context": "12 Monate"}])
        self.assertIn("Add-to-Cart-Rate misst", out)
        self.assertIn("1.500.000", out)

    def test_the_explanation_stands_above_the_table(self):
        """Erst erklaeren, dann belegen. Andersherum liest niemand die Tabelle."""
        out = self._render(explanation="ERKLAERUNG",
                           metrics=[{"label": "x", "value": "1", "context": "y"}])
        self.assertLess(out.index("ERKLAERUNG"), out.index("<table"))

    def test_the_benchmark_becomes_its_own_block(self):
        out = self._render(benchmark="Der Median vergleichbarer Shops liegt bei 1,4 Prozent.")
        self.assertIn('class="benchmark"', out)
        self.assertIn("Median vergleichbarer Shops", out)
        self.assertIn("Einordnung", out)

    def test_a_finding_without_the_new_fields_still_renders(self):
        # Snapshots aus der Zeit vor dem 09.09.2026 muessen unveraendert gehen.
        out = self._render(why="Der Uebergang verliert 95 von 100 Sessions.")
        self.assertIn("Was daraus folgt", out)
        self.assertNotIn('class="benchmark"', out)

    def test_without_explanation_the_old_fallback_applies(self):
        """Ohne `explanation` und ohne Tabelle traegt der Rest des statement."""
        out = self._render(statement="Erster Satz. Zweiter Satz mit Erklaerung.")
        self.assertIn("Zweiter Satz", out)


class TestMassnahmenMitStatus(unittest.TestCase):
    """Eine erledigte oder hinfällige Maßnahme steht nicht mehr als Aufgabe im Report."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        self.run_id = "2026-10-01-audit"
        (self.ws / "reporting" / "data" / self.run_id).mkdir(parents=True)
        findings = self.ws / "reporting" / "runs" / self.run_id / "findings"
        findings.mkdir(parents=True)
        (self.ws / "reporting" / "config.json").write_text(
            json.dumps({"brand": "Beispielshop"}), encoding="utf-8")
        (findings / "conversion.json").write_text(json.dumps(
            {"discipline": "cro", "run_id": self.run_id, "findings": [
                {"id": "CRO-01", "statement": "Nur 4,7 Prozent führen zum Warenkorb.",
                 "evidence": "ga4.json > funnel", "severity": "hoch",
                 "confidence": "confirmed", "effort": "small",
                 "fix": "Kein Eingriff nötig."}]}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *statuses):
        measures = [{"id": f"M-{i:03d}", "title": f"Maßnahme {status}",
                     "discipline": "cro", "evidence": "ga4.json > funnel",
                     "confidence": "confirmed", "leverage": "high", "effort": "small",
                     "responsible": "Customer", "data_source": "Shopify-Theme",
                     "check_rule": "Frage an den Kunden: erledigt?",
                     "finding_ref": "CRO-01", "type": "measure", "status": status,
                     "history": [{"status": status, "date": "2026-10-01"}]}
                    for i, status in enumerate(statuses, 1)]
        (self.ws / "reporting" / "measures.json").write_text(json.dumps(
            {"next_id": len(measures) + 1, "measures": measures}), encoding="utf-8")
        return rb.Run(self.ws, self.run_id)

    def test_closed_measures_leave_the_finding(self):
        out = rb.finding_blocks(self._run("implemented", "obsolete", "rejected"),
                                "conversion")
        self.assertNotIn('class="measure"', out)
        # Ohne anstehende Maßnahme sagt der Befund selbst, was zu tun ist.
        self.assertIn("Kein Eingriff nötig.", out)

    def test_open_and_running_measures_stay(self):
        out = rb.finding_blocks(self._run("open", "in_progress", "obsolete"),
                                "conversion")
        self.assertIn("Maßnahme open", out)
        self.assertIn("Maßnahme in_progress", out)
        self.assertNotIn("Maßnahme obsolete", out)
        self.assertNotIn("Kein Eingriff nötig.", out)

    def test_the_plan_counts_only_what_is_left(self):
        out = rb.measures_overview(self._run("open", "implemented", "obsolete"),
                                   "Beispielshop")
        self.assertIn("1 Einträge", out)
        self.assertNotIn("Maßnahme implemented", out)


class TestPhaseVierBautBeideFassungen(unittest.TestCase):
    """Ein Aufruf, beide Fassungen. Sonst fehlt eine, und der Lauf sieht fertig aus."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        # Der Schluss liest die Einstellungen des Betreibers. Die zentrale Datei
        # ist eine Test-Datei: auf dem Rechner eines Betreibers stehen in der
        # echten Werte, auch der Pfad zu seiner Schlussseite.
        self.central = self.ws / "operator-central.env"
        for patcher in (mock.patch.object(env, "CENTRAL", self.central),
                        mock.patch.dict(os.environ)):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ["PTAI_ENV_FILE"] = str(self.central)
        os.environ["HOME"] = str(self.ws)
        for name in CLOSING_SETTINGS:
            os.environ.pop(name, None)
        self.run_id = "2026-10-01-audit"
        run = self.ws / "reporting" / "runs" / self.run_id
        (run / "findings").mkdir(parents=True)
        (self.ws / "reporting" / "data" / self.run_id).mkdir(parents=True)
        (self.ws / "reporting" / "config.json").write_text(
            json.dumps({"brand": "Beispielshop", "domain": "https://beispielshop.test"}),
            encoding="utf-8")
        (run / "state.json").write_text(json.dumps({
            "run_id": self.run_id, "cadence": "audit", "period": None,
            "phases": {p: "done" for p in
                       ("0-setup", "1-raw-data", "2-analyses", "3-synthesis",
                        "4-deliverables")},
            "sources": {}}), encoding="utf-8")
        (run / "findings" / "conversion.json").write_text(json.dumps({
            "discipline": "cro", "run_id": self.run_id, "findings": [{
                "id": "CRO-01", "statement": "Nur 4,7 Prozent führen zum Warenkorb.",
                "explanation": "Die Add-to-Cart-Rate misst den Übergang.",
                "benchmark": "Keine Branchen-Benchmark, interner Vergleich.",
                "evidence": "ga4.json > funnel", "severity": "hoch",
                "confidence": "confirmed", "effort": "small"}]}), encoding="utf-8")
        self.text = run / "report-text.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _lauf(self, *extra):
        return rb.main(["--workspace", str(self.ws), "--run-id", self.run_id, *extra])

    def _text_fuellen(self):
        """Die Vorlage so fuellen, wie eine Sitzung sie fuellen wuerde.

        `text_laden` verlangt jedes Pflichtfeld, eine Kernaussage je Sektion
        und zwei bis vier Problem-Kacheln. Das ist Absicht: ein Report mit
        leeren Feldern soll gar nicht erst entstehen.
        """
        doc = json.loads(self.text.read_text(encoding="utf-8"))
        for feld in rb.TEXT_FIELDS:
            doc[feld] = f"Platzhalter für {feld}."
        doc[rb.KEY_MESSAGE] = {k: f"Kernaussage {k}." for k in rb.SECTIONS
                               if k not in rb.WITHOUT_KEY_MESSAGE}
        doc[rb.PROBLEM_FIELD] = [
            {"value": "4,7", "unit": "Prozent", "label": "Add-to-Cart-Rate",
             "detail": "Erste Funnel-Stufe.", "finding_ref": "CRO-01"},
            {"value": "12", "unit": "Dienste", "label": "eingebunden",
             "detail": "Drittanbieter im Quelltext.", "finding_ref": "CRO-01"},
        ]
        self.text.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    def test_a_missing_text_file_stops_with_a_template(self):
        self.assertEqual(self._lauf(), 2)
        self.assertTrue(self.text.exists())

    def test_both_versions_appear_in_one_call(self):
        self._lauf()          # legt die Vorlage an
        self._text_fuellen()  # eine Sitzung fuellt sie
        self.assertEqual(self._lauf(), 0)
        run = self.ws / "reporting" / "runs" / self.run_id
        self.assertTrue((run / "audit.html").exists(), "Druckfassung fehlt")
        self.assertTrue((run / "audit-web.html").exists(), "Web-Fassung fehlt")

    def test_no_web_leaves_the_web_version_out(self):
        self._lauf()
        self._text_fuellen()
        self._lauf("--no-web")
        run = self.ws / "reporting" / "runs" / self.run_id
        self.assertTrue((run / "audit.html").exists())
        self.assertFalse((run / "audit-web.html").exists())

    def test_both_versions_carry_the_same_finding(self):
        # Beide aus einem `content()`-Aufruf. Liefen sie getrennt, koennten
        # Zahlen auseinanderlaufen, ohne dass es jemand bemerkt.
        self._lauf()
        self._text_fuellen()
        self._lauf()
        run = self.ws / "reporting" / "runs" / self.run_id
        druck = (run / "audit.html").read_text(encoding="utf-8")
        web = (run / "audit-web.html").read_text(encoding="utf-8")
        for fassung in (druck, web):
            self.assertIn("Add-to-Cart-Rate misst", fassung)
            self.assertIn("Keine Branchen-Benchmark", fassung)

    def test_no_werkzeug_in_the_visible_text(self):
        # "Werkzeug" darf in keinem Kundentext stehen (Yves' Vorgabe). Der
        # BAUKASTEN-Kommentar ist beim Bauen schon raus, hier bleibt nur, was
        # ein Kunde tatsaechlich sieht.
        self._lauf()
        self._text_fuellen()
        self._lauf()
        run = self.ws / "reporting" / "runs" / self.run_id
        html = (run / "audit.html").read_text(encoding="utf-8")
        sichtbar = re.sub(r"<!--.*?-->", "", html, flags=re.S)
        sichtbar = re.sub(r"<[^>]+>", " ", sichtbar)
        self.assertNotIn("werkzeug", sichtbar.lower())


class TestClosingInTheAudit(unittest.TestCase):
    """Der Schluss im gebauten Audit kommt aus den Einstellungen (12.09.2026),
    die Schlussseite aus `PTAI_CLOSING_FILE` (15.09.2026).

    Fixture und Hilfen stammen aus `TestPhaseVierBautBeideFassungen`, ohne dass
    dessen Tests ein zweites Mal laufen. Die Fixture richtet auch die zentrale
    Test-Datei ein, `self.central`.
    """

    setUp = TestPhaseVierBautBeideFassungen.setUp
    tearDown = TestPhaseVierBautBeideFassungen.tearDown
    _lauf = TestPhaseVierBautBeideFassungen._lauf
    _text_fuellen = TestPhaseVierBautBeideFassungen._text_fuellen

    def _audit_html(self) -> str:
        self._lauf()
        self._text_fuellen()
        self.assertEqual(self._lauf("--no-web"), 0)
        text = (self.ws / "reporting" / "runs" / self.run_id / "audit.html").read_text(
            encoding="utf-8")
        self.assertNotIn("__CLOSING__", text)
        return text

    def _closing_panel(self) -> str:
        text = self._audit_html()
        start = text.index('<footer class="closing">')
        return text[start:text.index("</footer>", start)]

    def test_the_closing_file_replaces_the_panel(self):
        fragment = self.ws / "schlussseite.html"
        fragment.write_text(FRAGMENT, encoding="utf-8")
        self.central.write_text(f"PTAI_CLOSING_FILE={fragment}\n"
                                "PTAI_OPERATOR_CONTACT=Mara Beispiel\n", encoding="utf-8")
        text = self._audit_html()
        self.assertEqual(text.count(FRAGMENT), 1)
        for gone in ('<footer class="closing">', "Erstellt mit ptai-ecom", "Mara Beispiel"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, text)
        # Die Markierungen bleiben um die Seite stehen, ein zweites `apply` findet sie.
        self.assertIn(f"<!-- CLOSING:start -->\n{FRAGMENT}<!-- CLOSING:end -->", text)
        # Die letzte Seite: nach dem Inhalt, danach nur noch das Ende des Dokuments.
        self.assertLess(text.index("<!-- /.content -->"), text.index(FRAGMENT))
        self.assertEqual(text[text.index(FRAGMENT) + len(FRAGMENT):].split(),
                         ["<!--", "CLOSING:end", "-->", "</body>", "</html>"])

    def test_both_versions_build_with_a_closing_file(self):
        fragment = self.ws / "schlussseite.html"
        fragment.write_text(FRAGMENT, encoding="utf-8")
        self.central.write_text(f"PTAI_CLOSING_FILE={fragment}\n", encoding="utf-8")
        self._lauf()
        self._text_fuellen()
        self.assertEqual(self._lauf(), 0)
        run = self.ws / "reporting" / "runs" / self.run_id
        self.assertIn(FRAGMENT, (run / "audit.html").read_text(encoding="utf-8"))
        web = (run / "audit-web.html").read_text(encoding="utf-8")
        self.assertEqual(web.count(FRAGMENT), 1)
        self.assertNotIn('<footer class="closing">', web)

    def test_the_web_version_ends_neutral_without_a_closing_file(self):
        self.central.write_text("PTAI_OPERATOR_CONTACT=Mara Beispiel\n", encoding="utf-8")
        self._lauf()
        self._text_fuellen()
        self.assertEqual(self._lauf(), 0)
        web = (self.ws / "reporting" / "runs" / self.run_id / "audit-web.html").read_text(
            encoding="utf-8")
        self.assertNotIn("__CLOSING__", web)
        start = web.index('<footer class="closing">')
        panel = web[start:web.index("</footer>", start)]
        self.assertIn("Mara Beispiel", panel)
        self.assertIn("Erstellt mit ptai-ecom von", panel)

    def test_a_missing_closing_file_keeps_the_neutral_panel(self):
        self.central.write_text(f"PTAI_CLOSING_FILE={self.ws / 'fehlt.html'}\n"
                                "PTAI_OPERATOR_CONTACT=Mara Beispiel\n", encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            panel = self._closing_panel()
        self.assertIn("Mara Beispiel", panel)
        self.assertIn("Erstellt mit ptai-ecom von", panel)
        self.assertIn("PTAI_CLOSING_FILE", err.getvalue())

    def test_the_operator_closing_is_in_the_audit(self):
        self.central.write_text(
            "PTAI_OPERATOR_NAME=Beispiel GmbH\n"
            "PTAI_OPERATOR_CONTACT=Mara Beispiel\n"
            "PTAI_OPERATOR_EMAIL=kontakt@beispielshop.example\n"
            "PTAI_OPERATOR_BOOKING_URL=https://termine.example/30min\n", encoding="utf-8")
        panel = self._closing_panel()
        self.assertIn('<p class="eyebrow eyebrow--line">Kontakt</p>', panel)
        self.assertIn("Beispiel GmbH", panel)
        self.assertIn("Mara Beispiel", panel)
        self.assertIn('href="mailto:kontakt@beispielshop.example"', panel)
        self.assertIn('href="https://termine.example/30min">termine.example/30min</a>', panel)
        self.assertIn('Erstellt mit ptai-ecom von <a href="https://path-to-ai.com">Path to AI</a>.',
                      panel)
        self.assertIn('class="panel-footer"', panel)
        self.assertNotIn("Wie es weitergeht", panel)
        self.assertNotIn("Gespräch", panel)

    def test_without_settings_only_the_origin(self):
        panel = self._closing_panel()
        self.assertIn("Erstellt mit ptai-ecom von", panel)
        self.assertNotIn("Kontakt", panel)
        self.assertNotIn("mailto:", panel)
        self.assertNotIn('class="summary"', panel)
