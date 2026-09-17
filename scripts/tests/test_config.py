"""Config-Prüfung für den Audit-Lauf."""
import unittest

from audit import config

MINIMAL = {
    "brand": "Beispielshop", "domain": "https://beispielshop.example",
    "shopify_store": "beispielshop.myshopify.com", "ga4_property_id": "1",
    "gsc_site": "sc-domain:beispielshop.example", "cwv_urls": [],
    "sources": {}, "account_slug": "beispielshop",
    "drive_path": "/pfad/zum/kundenordner/beispielshop",
    "market": {"location_code": 2276, "language_code": "de"},
}


class TestConfig(unittest.TestCase):
    def test_complete_config_is_ok(self):
        self.assertEqual(config.validate(MINIMAL), [])

    def test_missing_account_slug_is_reported(self):
        without = {k: v for k, v in MINIMAL.items() if k != "account_slug"}
        self.assertIn("account_slug", " ".join(config.validate(without)))

    def test_missing_drive_path_is_reported(self):
        without = {k: v for k, v in MINIMAL.items() if k != "drive_path"}
        self.assertIn("drive_path", " ".join(config.validate(without)))

    def test_relative_drive_path_is_reported(self):
        # Ein relativer Pfad landet relativ zum Workspace, also im Kunden-Repo.
        errors = config.validate({**MINIMAL, "drive_path": "kunden/beispielshop"})
        self.assertIn("drive_path", " ".join(errors))

    def test_tilde_drive_path_is_reported(self):
        # Eine Tilde in einem JSON-Wert löst keine Shell mehr auf, und
        # check_env.sh lehnt sie ebenso ab.
        errors = config.validate({**MINIMAL, "drive_path": "~/ptai-ecom/accounts/beispielshop"})
        self.assertIn("absolut", " ".join(errors))

    def test_budget_cap_has_a_conservative_default(self):
        self.assertEqual(config.budget_cap(MINIMAL), config.BUDGET_DEFAULT)

    def test_budget_cap_from_the_config_wins(self):
        self.assertEqual(config.budget_cap({**MINIMAL, "dfs_budget_usd": 12.5}), 12.5)

    def test_negative_budget_cap_is_reported(self):
        self.assertIn("dfs_budget_usd", " ".join(config.validate({**MINIMAL, "dfs_budget_usd": -1})))

    def test_old_euro_field_is_an_error_not_a_silent_default(self):
        # Ein Workspace mit dem alten Feldnamen liefe sonst mit dem
        # Vorgabewert weiter, also faktisch ohne den gesetzten Deckel.
        errors = config.validate({**MINIMAL, "dfs_budget_eur": 10.0})
        self.assertIn("dfs_budget_usd", " ".join(errors))


class TestMarket(unittest.TestCase):
    def test_market_is_required(self):
        # Ohne Markt misst jeder DataForSEO-Aufruf irgendein Land. Das
        # Ergebnis sieht plausibel aus und gehört zu einem anderen Shop.
        without = {k: v for k, v in MINIMAL.items() if k != "market"}
        self.assertIn("market", " ".join(config.validate(without)))

    def test_market_needs_both_fields(self):
        errors = config.validate({**MINIMAL, "market": {"location_code": 2276}})
        self.assertIn("language_code", " ".join(errors))

    def test_location_code_must_be_a_number(self):
        # DataForSEO nimmt einen numerischen Standortcode. "Deutschland" lässt
        # die Abfrage scheitern, nachdem sie bezahlt ist.
        errors = config.validate({**MINIMAL, "market": {"location_code": "Deutschland",
                                                         "language_code": "de"}})
        self.assertIn("location_code", " ".join(errors))

    def test_boolean_is_not_a_location_code(self):
        # True ist in Python ein int. Ohne die Zusatzprüfung ginge es durch.
        errors = config.validate({**MINIMAL, "market": {"location_code": True,
                                                         "language_code": "de"}})
        self.assertIn("location_code", " ".join(errors))

    def test_language_code_must_be_a_short_code(self):
        errors = config.validate({**MINIMAL, "market": {"location_code": 2276,
                                                         "language_code": "Deutsch"}})
        self.assertIn("language_code", " ".join(errors))

    def test_market_must_be_an_object(self):
        errors = config.validate({**MINIMAL, "market": "Deutschland"})
        self.assertIn("market", " ".join(errors))

    def test_accessor_returns_the_pair(self):
        self.assertEqual(config.market(MINIMAL), (2276, "de"))

    def test_accessor_raises_instead_of_defaulting(self):
        # Kein Vorgabewert. Ein Pull, der ohne Markt startet, soll abbrechen,
        # bevor er zahlt, nicht stillschweigend Deutschland messen.
        with self.assertRaises(ValueError):
            config.market({})

    def test_accessor_raises_on_a_half_filled_market(self):
        with self.assertRaises(ValueError):
            config.market({"market": {"location_code": 2276}})


class TestPageTypes(unittest.TestCase):
    def test_page_types_have_all_six_defaults(self):
        # Der Zweck der Funktion ist die Vollständigkeit, nicht ein Schlüssel.
        self.assertEqual(set(config.page_types(MINIMAL)),
                         {"start", "collection", "product", "cart", "search", "blog"})

    def test_unconfigured_page_type_is_none(self):
        self.assertIsNone(config.page_types(MINIMAL)["product"])

    def test_misspelled_page_type_is_reported(self):
        # produkte statt product: derselbe stille Fehler wie bei cadences,
        # der Seitentyp bliebe für immer unkonfiguriert.
        errors = config.validate({**MINIMAL, "page_types": {"produkte": "https://x.de/p"}})
        self.assertTrue(any("produkte" in f for f in errors))

    def test_config_is_not_an_object(self):
        # Eine handgeschriebene JSON-Datei kann oben eine Liste sein.
        # validate verspricht, nie zu werfen, also gilt das auch hier.
        for broken in (None, [], "text", 42):
            self.assertTrue(config.validate(broken))

    def test_cadences_is_not_an_object(self):
        self.assertTrue(config.validate({**MINIMAL, "cadences": "month"}))

    def test_cadences_key_is_not_text(self):
        # Über eine JSON-Datei nicht erreichbar, aber der Docstring verspricht
        # "wirft nie", und difflib erwartet einen String.
        self.assertTrue(config.validate({**MINIMAL, "cadences": {1: "month"}}))

    def test_budget_is_not_a_number(self):
        self.assertTrue(config.validate({**MINIMAL, "dfs_budget_usd": "zehn"}))

    def test_misspelled_cadence_key_is_reported(self):
        # dfs_ranking statt dfs_rankings ist ohne Prüfung nicht von "kein
        # Eintrag" zu unterscheiden: die Quelle liefe still mit ihrer
        # Voreinstellung weiter, und niemand merkt, dass die Config nie griff.
        errors = config.validate({**MINIMAL, "cadences": {"dfs_ranking": "month"}})
        self.assertTrue(any("dfs_ranking" in f for f in errors))

    def test_invalid_cadence_value_is_reported(self):
        errors = config.validate({**MINIMAL, "cadences": {"dfs_rankings": "täglich"}})
        self.assertTrue(any("täglich" in f for f in errors))

    def test_empty_competitors_is_not_reported(self):
        """Der Audit findet die Wettbewerber selbst, über die Überschneidung
        in den Suchergebnissen. Eine leere Liste ist kein halbfertiges Setup."""
        self.assertFalse(any("Wettbewerber" in h for h in config.hints(MINIMAL)))


class TestSourceFields(unittest.TestCase):
    """Ein Feld einer Quelle ist Pflicht, solange nicht alle ihre Lauf-Quellen aus sind."""

    def config(self, drop, **sources):
        return {**{k: v for k, v in MINIMAL.items() if k != drop}, "sources": sources}

    def test_ga4_field_not_needed_when_switched_off(self):
        self.assertEqual(config.validate(self.config("ga4_property_id", ga4=False)), [])

    def test_ga4_field_needed_when_on(self):
        errors = config.validate(self.config("ga4_property_id", ga4=True))
        self.assertIn("ga4_property_id", " ".join(errors))

    def test_missing_sources_entry_means_on(self):
        errors = config.validate(self.config("gsc_site"))
        self.assertIn("gsc_site", " ".join(errors))

    def test_shopify_alone_off_is_not_enough(self):
        # Katalog und Shop-Technik brauchen shopify_store genauso.
        errors = config.validate(self.config("shopify_store", shopify=False))
        self.assertIn("shopify_store", " ".join(errors))

    def test_shopify_all_three_off(self):
        cfg = self.config("shopify_store", shopify=False, catalogue=False, shop_tech=False)
        self.assertEqual(config.validate(cfg), [])

    def test_switched_off_reads_only_false(self):
        self.assertFalse(config.source_switched_off({"sources": {"ga4": None}}, "ga4"))
        self.assertTrue(config.source_switched_off({"sources": {"ga4": False}}, "ga4"))


if __name__ == "__main__":
    unittest.main()


class TestEmptyRequiredFields(unittest.TestCase):
    """Anwesenheit allein reicht nicht: ein leerer Pflichtwert ist ein Fehler."""

    def test_empty_string_is_reported(self):
        config_with_gap = dict(MINIMAL, gsc_site="")
        self.assertIn("gsc_site", " ".join(config.validate(config_with_gap)))

    def test_whitespace_only_is_reported(self):
        config_with_gap = dict(MINIMAL, ga4_property_id="   ")
        self.assertIn("ga4_property_id", " ".join(config.validate(config_with_gap)))

    def test_none_is_reported(self):
        config_with_gap = dict(MINIMAL, brand=None)
        self.assertIn("brand", " ".join(config.validate(config_with_gap)))

    def test_an_empty_list_stays_allowed(self):
        # Eine leere cwv_urls-Liste ist ein zulässiger Anfangsstand, kein Fehler.
        self.assertEqual(config.validate(dict(MINIMAL, cwv_urls=[])), [])


class TestKaufweg(unittest.TestCase):
    """Die Aufnahme legt einen echten Testwarenkorb im Produktivshop an.

    Das ist eine Entscheidung, aber eine fuer das Setup und einmal je Kunde.
    Am 08.09.2026 fragte der Audit stattdessen mitten in Phase 1 danach.
    """

    def test_fehlendes_feld_ist_keine_stille_zusage(self):
        self.assertIsNone(config.checkout_capture({}))

    def test_und_keine_stille_absage(self):
        """`None` heisst offen, nicht False: der Unterschied entscheidet, ob
        der Report eine Luecke ausweist oder so tut, als sei nichts."""
        self.assertIsNot(config.checkout_capture({}), False)

    def test_ein_gesetzter_wert_gilt(self):
        self.assertIs(config.checkout_capture({"checkout_capture": True}), True)
        self.assertIs(config.checkout_capture({"checkout_capture": False}), False)

    def test_ein_unsinniger_wert_gilt_als_offen(self):
        for value in ("ja", 1, None, []):
            with self.subTest(value=value):
                self.assertIsNone(config.checkout_capture({"checkout_capture": value}))

    def test_das_setup_wird_darauf_hingewiesen(self):
        hinweise = config.hints({})
        self.assertTrue(any("checkout_capture" in h for h in hinweise))

    def test_mit_gesetztem_feld_kein_hinweis(self):
        hinweise = config.hints({"checkout_capture": False})
        self.assertFalse(any("checkout_capture" in h for h in hinweise))


class TestKeineErfundenenLuecken(unittest.TestCase):
    """Ein Hinweis, der zu Arbeit auffordert, die niemand liest, macht ein
    fertiges Setup unfertig.

    Bis zum 08.09.2026 mahnte `hints()` leere Wettbewerber- und
    Keyword-Seed-Listen an. Beide Felder wurden von genau einer Stelle
    gelesen, naemlich von diesem Hinweis.
    """

    def test_leere_wettbewerber_sind_kein_hinweis(self):
        self.assertFalse(any("ettbewerb" in h for h in config.hints({})))

    def test_leere_keyword_seeds_sind_kein_hinweis(self):
        self.assertFalse(any("eyword" in h.lower() for h in config.hints({})))

    def test_eine_vollstaendige_config_erzeugt_keinen_hinweis(self):
        self.assertEqual(config.hints({"checkout_capture": True}), [])


class TestVergleichsProperties(unittest.TestCase):
    """Ein Shop kann denselben Kauf in mehrere GA4-Properties senden.

    Am 07.09.2026 meldete die gezogene Property vier Monate ohne einen
    einzigen Kauf, und der Report schrieb "die Kaufmessung ist ausgefallen".
    Die Bestellungen standen die ganze Zeit in der zweiten Property.
    """

    def test_ohne_feld_leere_liste(self):
        self.assertEqual(config.compare_properties(MINIMAL), [])

    def test_die_liste_kommt_durch(self):
        c = dict(MINIMAL, ga4_compare_properties=["987654321", "123"])
        self.assertEqual(config.compare_properties(c), ["987654321", "123"])

    def test_die_hauptproperty_faellt_raus(self):
        """Gegen sich selbst zu vergleichen ergibt nur Rauschen."""
        c = dict(MINIMAL, ga4_property_id="1",
                 ga4_compare_properties=["1", "987654321"])
        self.assertEqual(config.compare_properties(c), ["987654321"])

    def test_zahlen_werden_zu_text(self):
        c = dict(MINIMAL, ga4_compare_properties=[987654321])
        self.assertEqual(config.compare_properties(c), ["987654321"])

    def test_ein_unsinniger_wert_bricht_nicht(self):
        self.assertEqual(config.compare_properties(
            dict(MINIMAL, ga4_compare_properties="987654321")), [])


class TestCrawlBudget(unittest.TestCase):
    """Der Umfang haengt am Shop, nicht am Lauf, und gehoert deshalb in die
    Config statt in den Prompt."""

    def test_ohne_felder_gelten_die_vorgaben(self):
        self.assertEqual(config.crawl_budget({}),
                         (config.CRAWL_MAX_URLS_DEFAULT,
                          config.CRAWL_DELAY_DEFAULT))

    def test_gesetzte_werte_gewinnen(self):
        c = dict(MINIMAL, crawl_max_urls=3500, crawl_delay_sec=0.5)
        self.assertEqual(config.crawl_budget(c), (3500, 0.5))

    def test_ein_text_faellt_auf_die_vorgabe_zurueck(self):
        c = dict(MINIMAL, crawl_max_urls="viele", crawl_delay_sec="langsam")
        self.assertEqual(config.crawl_budget(c),
                         (config.CRAWL_MAX_URLS_DEFAULT,
                          config.CRAWL_DELAY_DEFAULT))

    def test_eine_zahl_als_text_wird_gelesen(self):
        c = dict(MINIMAL, crawl_max_urls="3500", crawl_delay_sec="0.5")
        self.assertEqual(config.crawl_budget(c), (3500, 0.5))

    def test_unsinnige_werte_bremsen_nie_den_crawl_aus(self):
        """Null URLs oder eine negative Pause duerfen keinen Lauf erzeugen,
        der nichts holt oder sofort losrast."""
        c = dict(MINIMAL, crawl_max_urls=0, crawl_delay_sec=-1)
        self.assertEqual(config.crawl_budget(c),
                         (config.CRAWL_MAX_URLS_DEFAULT,
                          config.CRAWL_DELAY_DEFAULT))

    def test_die_rueckgabe_ist_immer_ein_paar(self):
        """Nie None: ein Aufrufer soll den Crawl nicht versehentlich
        ungebremst starten, weil ein Feld fehlt."""
        for c in ({}, MINIMAL, dict(MINIMAL, crawl_max_urls=None)):
            with self.subTest(config=c):
                umfang, pause = config.crawl_budget(c)
                self.assertIsInstance(umfang, int)
                self.assertIsInstance(pause, float)
