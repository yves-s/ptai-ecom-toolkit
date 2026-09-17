"""Katalog-Aggregation. Kein Test ruft die Shopify CLI."""
import json
import sys
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2] / "skills"
sys.path.insert(0, str(SKILLS / "pull-shopify-catalog" / "scripts"))
import catalog_build  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "shopify"


def product(handle="a", seo_title="T", seo_description="D", description="x" * 300,
            images=(("bild.jpg", "Alt"),), variants=((None, "12.00", "6.00"),),
            status="ACTIVE"):
    return {
        "handle": handle, "title": handle.upper(), "status": status,
        "productType": "Schmuck", "vendor": "Beispielshop",
        "description": description,
        "seo": {"title": seo_title, "description": seo_description},
        "images": {"nodes": [{"url": u, "altText": a} for u, a in images]},
        "variants": {"nodes": [
            {"sku": sku, "price": price,
             "inventoryItem": {"unitCost": {"amount": cost} if cost is not None else None}}
            for sku, price, cost in variants]},
    }


class TestFlatten(unittest.TestCase):
    def test_reduces_a_product_to_counts_not_text(self):
        # Die Beschreibung geht nie als Text in den Snapshot, nur ihre Länge.
        # Bei 2.000 Produkten ist das der Unterschied zwischen einem Snapshot,
        # den ein Analyse-Agent lesen kann, und einem, der ihn sprengt.
        flat = catalog_build.flatten(product(description="x" * 4200))
        self.assertEqual(flat["description_length"], 4200)
        self.assertNotIn("description", flat)

    def test_counts_images_with_and_without_alt(self):
        flat = catalog_build.flatten(product(images=(("a.jpg", "Alt"), ("b.jpg", ""),
                                                       ("c.jpg", None))))
        self.assertEqual((flat["images"], flat["images_with_alt"]), (3, 1))

    def test_empty_alt_text_counts_as_missing(self):
        # Ein leerer Alt-Text ist kein Alt-Text. Shopify liefert beides,
        # None und "", und beide bedeuten dasselbe.
        self.assertEqual(catalog_build.flatten(product(images=(("a.jpg", "   "),)))["images_with_alt"], 0)

    def test_counts_variants_without_sku_and_without_cost(self):
        flat = catalog_build.flatten(product(variants=(
            ("SKU-1", "10.00", "5.00"), (None, "20.00", None), ("", "30.00", "0.00"))))
        self.assertEqual(flat["variants"], 3)
        self.assertEqual(flat["variants_without_sku"], 2)
        self.assertEqual(flat["variants_without_cost"], 1)

    def test_cost_zero_counts_as_maintained(self):
        # 0,00 ist ein gepflegter Wert (Zugabe, Werbeartikel), None ist keiner.
        # Wer beides zusammenwirft, meldet eine zu hohe Lücke.
        self.assertEqual(catalog_build.flatten(product(variants=((None, "1.00", "0.00"),)))
                         ["variants_without_cost"], 0)

    def test_price_range_from_the_variants(self):
        flat = catalog_build.flatten(product(variants=(
            ("a", "10.00", None), ("b", "30.00", None), ("c", "20.00", None))))
        self.assertEqual((flat["price_min"], flat["price_max"]), (10.0, 30.0))

    def test_unparsable_price_is_skipped_not_zero(self):
        # Ein Preis, den niemand lesen kann, darf die Spanne nicht auf 0
        # ziehen. Dann sieht der Shop aus, als verschenke er Ware.
        flat = catalog_build.flatten(product(variants=(("a", "auf Anfrage", None),
                                                        ("b", "20.00", None))))
        self.assertEqual((flat["price_min"], flat["price_max"]), (20.0, 20.0))


class TestShapeCheck(unittest.TestCase):
    """Fehlt ein Feld in **allen** Produkten, ist die Abfrage falsch, nicht der
    Katalog leer. Ohne diese Prüfung meldet der Snapshot "kein Produkt hat
    SEO-Felder" für einen Shop, der sie pflegt."""

    def test_missing_seo_in_every_product_is_reported(self):
        products = [{"handle": "a", "images": {"nodes": []}, "variants": {"nodes": []}}
                    for _ in range(3)]
        notes = catalog_build.check_shape(products)
        self.assertIn("seo", " ".join(notes))

    def test_missing_variants_in_every_product_is_reported(self):
        products = [{"handle": "a", "seo": {"title": "T"}, "images": {"nodes": []}}
                    for _ in range(3)]
        self.assertIn("variants", " ".join(catalog_build.check_shape(products)))

    def test_a_complete_query_reports_nothing(self):
        self.assertEqual(catalog_build.check_shape([product()]), [])

    def test_one_product_with_the_field_is_enough(self):
        # Ein Shop darf einzelne Produkte ohne SEO-Felder haben. Gemeldet wird
        # nur, wenn das Feld nirgends vorkommt, denn dann fehlt es in der
        # Abfrage.
        products = [product(), {"handle": "b", "images": {"nodes": []},
                                 "variants": {"nodes": []}}]
        self.assertEqual(catalog_build.check_shape(products), [])

    def test_empty_catalogue_reports_nothing(self):
        self.assertEqual(catalog_build.check_shape([]), [])


class TestSummary(unittest.TestCase):
    def flat(self, products):
        return [catalog_build.flatten(p) for p in products]

    def test_counts_products_and_seo_gaps(self):
        summary = catalog_build.build(self.flat([
            product(handle="a"), product(handle="b", seo_title=""),
            product(handle="c", seo_title="", seo_description=None)]), [])["summary"]
        self.assertEqual(summary["products_total"], 3)
        self.assertEqual(summary["products_without_seo_title"], 2)
        self.assertEqual(summary["products_without_seo_description"], 1)

    def test_alt_share_is_over_all_images_not_all_products(self):
        summary = catalog_build.build(self.flat([
            product(handle="a", images=(("x", "Alt"),) * 9),
            product(handle="b", images=(("y", None),))]), [])["summary"]
        self.assertAlmostEqual(summary["share_images_with_alt"], 0.9)

    def test_share_without_images_is_none_not_zero(self):
        # Ein Katalog ohne Bilder hat keinen Alt-Text-Anteil. Eine 0 läse sich
        # als "kein Bild hat einen Alt-Text" und wäre ein erfundener Befund.
        self.assertIsNone(catalog_build.build([], [])["summary"]["share_images_with_alt"])

    def test_description_length_percentiles_instead_of_a_threshold(self):
        # Der Pull fällt kein Urteil über "dünn". Er liefert die Verteilung,
        # die Schwelle steht im Kennzahlen-Katalog und gehört zur Analyse.
        flats = self.flat([product(handle=str(i), description="x" * (i * 100))
                           for i in range(1, 11)])
        summary = catalog_build.build(flats, [])["summary"]
        self.assertIn("description_length_p50", summary)
        self.assertIn("description_length_p10", summary)
        self.assertEqual(summary["products_without_description"], 0)

    def test_products_without_description_are_counted(self):
        summary = catalog_build.build(self.flat([product(description=""),
                                                  product(handle="b")]), [])["summary"]
        self.assertEqual(summary["products_without_description"], 1)

    def test_lists_are_capped_and_marked(self):
        flats = self.flat([product(handle=str(i), seo_title="")
                           for i in range(catalog_build.MAX_LIST + 20)])
        built = catalog_build.build(flats, [])
        self.assertEqual(len(built["products_without_seo_title"]), catalog_build.MAX_LIST)
        self.assertTrue(built["products_without_seo_title_truncated"])
        self.assertEqual(built["summary"]["products_without_seo_title"],
                         catalog_build.MAX_LIST + 20)

    def test_no_cost_anywhere_is_a_note(self):
        # Spec Abschnitt 19: Marge nur, wenn cost per item gepflegt ist. Der
        # Pull sagt das einmal, statt dass die Analyse es errät.
        flats = self.flat([product(variants=(("a", "10.00", None),))])
        self.assertIn("Marge", " ".join(catalog_build.build(flats, [])["notes"]))

    def test_partial_cost_is_no_note(self):
        flats = self.flat([product(handle="a", variants=(("a", "10.00", "5.00"),)),
                           product(handle="b", variants=(("b", "10.00", None),))])
        self.assertNotIn("Marge", " ".join(catalog_build.build(flats, [])["notes"]))

    def test_collections_are_counted(self):
        collections = [{"handle": "c1", "description": "Text"},
                       {"handle": "c2", "description": ""}]
        summary = catalog_build.build(self.flat([product()]), collections)["summary"]
        self.assertEqual(summary["collections_total"], 2)
        self.assertEqual(summary["collections_without_description"], 1)


class TestFixture(unittest.TestCase):
    def test_reads_a_graphql_page(self):
        page = json.loads((FIX / "catalog-page.json").read_text(encoding="utf-8"))
        products = catalog_build.products_from_pages([page])
        self.assertEqual(len(products), 3)
        built = catalog_build.build([catalog_build.flatten(p) for p in products], [])
        self.assertEqual(built["summary"]["products_total"], 3)
        self.assertEqual(built["summary"]["products_without_seo_title"], 1)

    def test_pagination_across_two_pages(self):
        page = json.loads((FIX / "catalog-page.json").read_text(encoding="utf-8"))
        self.assertEqual(len(catalog_build.products_from_pages([page, page])), 6)


class TestAntwortform(unittest.TestCase):
    """Die Nahtstelle zwischen Pull und Rechenteil.

    Bis 07.09.2026 hat kein Test die Funktionen geprüft, die eine echte
    API-Antwort einlesen. `products_from_pages()` erwartete eine `data`-Hülle,
    die `shopify store execute --json` nicht liefert, und gab für jede echte
    CLI-Antwort eine leere Liste zurück. Das Script meldete trotzdem Erfolg.
    Der Fehler lief durch 668 grüne Tests, weil alle nur mit bereits flachen
    Produkt-Dicts arbeiteten.
    """

    #: So antwortet `shopify store execute --json`: ohne Hülle.
    CLI = {"products": {"pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [{"handle": "a", "title": "A",
                                   "images": {"nodes": []},
                                   "variants": {"nodes": []}}]}}
    #: So antwortet ein roher GraphQL-Aufruf über HTTP: mit Hülle.
    HTTP = {"data": CLI}

    def test_cli_antwort_ohne_huelle_liefert_produkte(self):
        self.assertEqual(len(catalog_build.products_from_pages([self.CLI])), 1)

    def test_http_antwort_mit_huelle_liefert_produkte(self):
        self.assertEqual(len(catalog_build.products_from_pages([self.HTTP])), 1)

    def test_beide_formen_gemischt(self):
        self.assertEqual(len(catalog_build.products_from_pages([self.CLI, self.HTTP])), 2)

    def test_collections_ebenso(self):
        cli = {"collections": {"nodes": [{"handle": "c", "title": "C"}]}}
        self.assertEqual(len(catalog_build.collections_from_pages([cli])), 1)
        self.assertEqual(len(catalog_build.collections_from_pages([{"data": cli}])), 1)

    def test_unbrauchbare_seite_wirft_nicht(self):
        for kaputt in (None, [], "text", {}, {"data": None}):
            self.assertEqual(catalog_build.products_from_pages([kaputt]), [])


if __name__ == "__main__":
    unittest.main()


class TestMargenschwelle(unittest.TestCase):
    """Der Hinweis hängt am Anteil, nicht an der Gleichheit.

    Am 07.09.2026 lag bei einem echten Shop jede Variante bis auf eine ohne
    Einkaufspreis, und der Hinweis fiel aus, weil diese eine einen trug. Die Marge war trotzdem nicht berechenbar.
    """

    def flat(self, products):
        return [catalog_build.flatten(p) for p in products]

    def _notes(self, mit_kosten, ohne_kosten):
        varianten = [(f"m{i}", "10.00", "5.00") for i in range(mit_kosten)]
        varianten += [(f"o{i}", "10.00", None) for i in range(ohne_kosten)]
        flats = self.flat([product(variants=tuple(varianten))])
        return " ".join(catalog_build.build(flats, [])["notes"])

    def test_fast_alle_ohne_kosten_ist_ein_hinweis(self):
        self.assertIn("Marge", self._notes(1, 199))

    def test_der_hinweis_nennt_den_anteil(self):
        self.assertIn("199 von 200", self._notes(1, 199))

    def test_die_haelfte_ohne_kosten_ist_kein_hinweis(self):
        self.assertNotIn("Marge", self._notes(100, 100))

    def test_knapp_unter_der_schwelle_ist_kein_hinweis(self):
        self.assertNotIn("Marge", self._notes(11, 89))

    def test_fast_alle_runden_nie_auf_hundert_prozent(self):
        """99,99 Prozent sind nicht 100, und der Satz steht im Kundenreport.

        Am 08.09.2026 meldete der Hinweis bei jeder Variante bis auf eine
        "100.0 Prozent", weil `.1f` kaufmaennisch rundet. Das behauptet eine
        Vollerhebung, die es nicht gibt: die eine gepflegte Variante ist der
        Unterschied zwischen "nicht berechenbar" und "niemand hat es je
        gepflegt". Abgerundet ist der Anteil nie zu hoch.
        """
        notes = self._notes(1, 8399)
        self.assertIn("8399 von 8400", notes)
        self.assertNotIn("100.0 Prozent", notes)
        self.assertIn("99.9 Prozent", notes)

    def test_wirklich_alle_ohne_kosten_nennen_keinen_anteil(self):
        """Ist keine einzige gepflegt, sagt der Satz das, statt 100 zu rechnen."""
        notes = self._notes(0, 500)
        self.assertIn("Keine einzige Variante", notes)
        self.assertNotIn("Prozent", notes)
