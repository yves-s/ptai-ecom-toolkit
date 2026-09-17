"""Die shape()-Funktionen der DataForSEO-Pulls, gegen die echte Antwortform.

Geprüft wird, was eine Zahl erzeugt: Zähler, Aggregate, Kürzung. Die Struktur
stammt aus aufgezeichneten Produktiv-Antworten (Endpoint-Bewertung vom
12.08.2026), die Werte hier sind neutral: die
Aufnahmen selbst sind Kundendaten und gehören nicht in ein öffentliches Repo.
"""
import sys
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2] / "skills"
sys.path.insert(0, str(SKILLS / "pull-dfs-rankings" / "scripts"))
import rankings_pull  # noqa: E402

sys.path.insert(0, str(SKILLS / "pull-dfs-competitors" / "scripts"))
import competitors_pull  # noqa: E402

sys.path.insert(0, str(SKILLS / "pull-dfs-shopping" / "scripts"))
import shopping_pull  # noqa: E402

sys.path.insert(0, str(SKILLS / "pull-dfs-keywords" / "scripts"))
import keywords_pull  # noqa: E402

sys.path.insert(0, str(SKILLS / "pull-dfs-backlinks" / "scripts"))
import backlinks_pull  # noqa: E402

META = {"source": "dfs_rankings"}

#: Die Positionsverteilung, wie `metrics.organic` sie liefert. Disjunkt, nicht
#: kumulativ: pos_2_3 enthält pos_1 nicht.
BANDS = {"pos_1": 125, "pos_2_3": 16, "pos_4_10": 75, "pos_11_20": 53,
         "pos_21_30": 52, "pos_31_40": 37, "pos_41_50": 22, "pos_51_60": 8,
         "pos_61_70": 3, "pos_71_80": 4, "pos_81_90": 1, "pos_91_100": 0}


def block(total=396, delivered=20, metrics=None, items=None):
    """Ein Labs-Ergebnisblock in der echten Verschachtelung.

    `result` ist eine Liste mit genau einem Block, die Zeilen liegen darin
    unter `items`, daneben stehen `total_count`, `items_count` und `metrics`.
    """
    organic = {**BANDS, "etv": 13857.4, "count": 396,
               "is_new": 215, "is_up": 57, "is_down": 20, "is_lost": 0}
    return [{
        "total_count": total, "items_count": delivered,
        "metrics": metrics if metrics is not None else {"organic": organic},
        "items": items if items is not None else [],
    }]


def item(keyword="a", rank=1, kind="organic", etv=3009.6, volume=9900,
         updated="2026-07-11 16:54:03 +00:00"):
    return {
        "keyword_data": {"keyword": keyword,
                          "keyword_info": {"search_volume": volume, "cpc": 2.11,
                                           "competition_level": "HIGH"}},
        "ranked_serp_element": {
            "last_updated_time": updated,
            "serp_item": {"type": kind, "rank_absolute": rank, "rank_group": rank,
                           "etv": etv, "url": f"https://beispielshop.example/{keyword}"},
        },
    }


class TestRankings(unittest.TestCase):
    def test_total_comes_from_total_count_not_from_the_delivered_rows(self):
        # 396 im Bestand, 20 geliefert. len(items) wäre hier 20 und stünde
        # als Bestand im Report.
        shaped = rankings_pull.shape(
            block(total=396, delivered=20, items=[item(f"k{i}") for i in range(20)]), META)
        self.assertEqual(shaped["summary"]["ranked_keywords_total"], 396)
        self.assertEqual(shaped["summary"]["ranked_keywords_delivered"], 20)

    def test_bands_come_from_metrics_not_from_the_rows(self):
        # Aus 20 gelieferten Zeilen gezählt kämen 20 heraus. Die API kennt
        # den vollen Bestand: 125 + 16 = 141 in den Top 3.
        summary = rankings_pull.shape(block(items=[item()]), META)["summary"]
        self.assertEqual(summary["top_3"], 141)
        self.assertEqual(summary["top_10"], 216)
        self.assertEqual(summary["top_100"], 396)

    def test_bands_are_cumulative_although_the_api_is_disjoint(self):
        summary = rankings_pull.shape(block(), META)["summary"]
        self.assertLessEqual(summary["top_3"], summary["top_10"])
        self.assertLessEqual(summary["top_10"], summary["top_100"])

    def test_top_100_matches_the_reported_total(self):
        # Die Bänder summieren sich auf den Bestand. Weicht das ab, liest
        # der Code die falsche Metrik.
        summary = rankings_pull.shape(block(), META)["summary"]
        self.assertEqual(summary["top_100"], summary["ranked_keywords_total"])

    def test_missing_metrics_gives_none_not_zero(self):
        # Keine Metriken heißt "nicht gemessen". Eine 0 läse sich als "kein
        # einziges Keyword in den Top 3" und wäre ein erfundener Befund.
        summary = rankings_pull.shape(block(metrics={}), META)["summary"]
        self.assertIsNone(summary["top_3"])

    def test_etv_is_read_from_the_serp_item(self):
        # etv sitzt auf serp_item, nicht auf ranked_serp_element. Eine Ebene
        # daneben liefert None für jede Zeile.
        shaped = rankings_pull.shape(block(items=[item(etv=3009.6)]), META)
        self.assertAlmostEqual(shaped["top_keywords"][0]["etv"], 3009.6)

    def test_keyword_info_fields_are_carried_over(self):
        row = rankings_pull.shape(block(items=[item()]), META)["top_keywords"][0]
        self.assertEqual(row["search_volume"], 9900)
        self.assertEqual(row["competition_level"], "HIGH")

    def test_last_updated_time_travels_with_each_keyword(self):
        # rank_absolute ist ein Datenbankwert, kein Live-Messwert. Ohne das
        # Datum liest die Analyse ihn als tagesaktuelle Position. Belegt: am
        # 12.08.2026 wich die Labs-Position von der Live-SERP ab.
        row = rankings_pull.shape(block(items=[item()]), META)["top_keywords"][0]
        self.assertEqual(row["last_updated_time"], "2026-07-11 16:54:03 +00:00")

    def test_list_is_capped_and_marked(self):
        many = [item(f"k{i}") for i in range(rankings_pull.MAX_KEYWORDS + 25)]
        shaped = rankings_pull.shape(block(items=many), META)
        self.assertEqual(len(shaped["top_keywords"]), rankings_pull.MAX_KEYWORDS)
        self.assertTrue(shaped["top_keywords_truncated"])

    def test_short_list_is_not_marked_truncated(self):
        self.assertFalse(rankings_pull.shape(block(items=[item()]), META)["top_keywords_truncated"])

    def test_serp_features_are_named_as_a_sample(self):
        # Der Feldname sagt, dass über die gelieferten Zeilen gezählt wird,
        # nicht über den Bestand.
        shaped = rankings_pull.shape(
            block(items=[item("a", kind="organic"), item("b", kind="shopping"),
                          item("c", kind="shopping")]), META)
        self.assertEqual(shaped["summary"]["serp_features_in_sample"],
                         {"organic": 1, "shopping": 2})

    def test_empty_answer_is_a_shop_without_rankings(self):
        shaped = rankings_pull.shape([], META)
        self.assertEqual(shaped["summary"]["ranked_keywords_total"], 0)
        self.assertEqual(shaped["top_keywords"], [])


class TestShareOfVoice(unittest.TestCase):
    def test_reads_etv_and_count_per_domain(self):
        rows = [{"items": [
            {"target": "beispielshop.example",
             "metrics": {"organic": {"etv": 562.7, "count": 39}}},
            {"target": "wettbewerb-a.example",
             "metrics": {"organic": {"etv": 13998.0, "count": 4300}}}]}]
        sov = rankings_pull.shape_traffic(rows, META)["share_of_voice"]
        self.assertEqual(sov[0], {"domain": "beispielshop.example",
                                   "etv": 562.7, "ranked_keywords": 39})

    def test_domain_without_metrics_gives_none_not_zero(self):
        # Eine Domain ohne Messwert ist ungemessen. Eine 0 stünde im Report
        # als "keine Sichtbarkeit".
        rows = [{"items": [{"target": "x.example", "metrics": {}}]}]
        self.assertIsNone(rankings_pull.shape_traffic(rows, META)["share_of_voice"][0]["etv"])


class TestVisibilityHistory(unittest.TestCase):
    def test_history_is_one_row_per_month(self):
        rows = [{"items": [
            {"year": 2026, "month": 8, "metrics": {"organic": {"count": 120, "etv": 300.5}}},
            {"year": 2026, "month": 9, "metrics": {"organic": {"count": 140, "etv": 355.0}}}]}]
        history = rankings_pull.shape_history(rows, META)["visibility_history"]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0], {"month": "2026-08", "ranked_keywords": 120, "etv": 300.5})

    def test_history_is_sorted_by_month(self):
        rows = [{"items": [
            {"year": 2026, "month": 9, "metrics": {"organic": {"count": 1, "etv": 1}}},
            {"year": 2025, "month": 12, "metrics": {"organic": {"count": 2, "etv": 2}}}]}]
        self.assertEqual(
            [r["month"] for r in rankings_pull.shape_history(rows, META)["visibility_history"]],
            ["2025-12", "2026-09"])

    def test_month_is_zero_padded(self):
        # "2026-8" sortiert als Text falsch und bricht jeden späteren
        # Vergleich gegen denselben Kalendermonat der Baseline.
        rows = [{"items": [{"year": 2026, "month": 8,
                             "metrics": {"organic": {"count": 1, "etv": 1}}}]}]
        self.assertEqual(
            rankings_pull.shape_history(rows, META)["visibility_history"][0]["month"], "2026-08")

    def test_row_without_a_month_is_skipped(self):
        rows = [{"items": [{"metrics": {"organic": {"count": 1, "etv": 1}}}]}]
        self.assertEqual(rankings_pull.shape_history(rows, META)["visibility_history"], [])

    def test_all_empty_metrics_is_flagged_as_a_finding(self):
        # Eine Reihe voller None sieht aus wie ein fehlgeschlagener Pull, ist
        # aber ein Befund: die Domain hat keine Sichtbarkeit.
        rows = [{"items": [{"year": 2026, "month": m, "metrics": {"organic": None}}
                            for m in (3, 4, 5)]}]
        shaped = rankings_pull.shape_history(rows, META)
        self.assertEqual(len(shaped["visibility_history"]), 3)
        self.assertIn("Befund", " ".join(shaped["notes_history"]))

    def test_a_series_with_data_gets_no_such_note(self):
        rows = [{"items": [{"year": 2026, "month": 3,
                             "metrics": {"organic": {"count": 5, "etv": 10}}}]}]
        self.assertNotIn("notes_history", rankings_pull.shape_history(rows, META))

    def test_empty_history_is_an_empty_list(self):
        self.assertEqual(rankings_pull.shape_history([], META)["visibility_history"], [])


class TestPayload(unittest.TestCase):
    def test_payload_carries_target_and_market(self):
        class Args:
            target = "beispielshop.example"
            location_code = 2276
            language_code = "de"
        task = rankings_pull.payload(Args())
        self.assertEqual(task["target"], "beispielshop.example")
        self.assertEqual(task["location_code"], 2276)
        self.assertEqual(task["limit"], rankings_pull.API_LIMIT)


if __name__ == "__main__":
    unittest.main()


def competitor_block(items, total=None):
    return [{"seed_keywords": ["outdoorjacke"], "total_count": total or len(items),
             "items_count": len(items), "items": items}]


class TestCompetitors(unittest.TestCase):
    def sample(self):
        return competitor_block([
            {"domain": "wettbewerb-a.example", "avg_position": 1.5, "median_position": 1,
             "rating": 197, "etv": 792.78, "keywords_count": 2, "visibility": 1.9},
            {"domain": "wettbewerb-b.example", "avg_position": 22.0, "median_position": 20,
             "rating": 40, "etv": 500.0, "keywords_count": 8, "visibility": 0.2}])

    def test_reads_the_serp_competitor_fields(self):
        first = competitors_pull.shape(self.sample(), META)["competitors"][0]
        self.assertEqual(first["domain"], "wettbewerb-a.example")
        self.assertEqual(first["avg_position"], 1.5)
        self.assertEqual(first["keywords_count"], 2)
        self.assertEqual(first["etv"], 792.78)

    def test_total_comes_from_total_count(self):
        shaped = competitors_pull.shape(competitor_block(
            [{"domain": f"d{i}.example", "avg_position": 1.0} for i in range(20)],
            total=84), META)
        self.assertEqual(shaped["summary"]["competitors_found"], 84)

    def test_delivered_count_sits_next_to_the_total(self):
        # 84 gefunden, 20 geliefert, 20 gelistet, nicht von uns gekürzt.
        # Ohne die mittlere Zahl liest sich das wie ein Widerspruch.
        shaped = competitors_pull.shape(competitor_block(
            [{"domain": f"d{i}.example", "avg_position": 1.0} for i in range(20)],
            total=84), META)
        self.assertEqual(shaped["summary"]["competitors_found"], 84)
        self.assertEqual(shaped["summary"]["competitors_delivered"], 20)
        self.assertFalse(shaped["competitors_truncated"])

    def test_sorted_by_average_position_not_by_api_order(self):
        # Der Audit will die stärksten zuerst. Wer sich auf die Reihenfolge
        # der API verlässt, bekommt sie irgendwann anders und merkt es nicht.
        rows = competitor_block([{"domain": "schwach.example", "avg_position": 30.0},
                                  {"domain": "stark.example", "avg_position": 2.0}])
        self.assertEqual([c["domain"] for c in competitors_pull.shape(rows, META)["competitors"]],
                         ["stark.example", "schwach.example"])

    def test_competitor_without_position_sorts_last(self):
        rows = competitor_block([{"domain": "ohne.example"},
                                  {"domain": "mit.example", "avg_position": 12.0}])
        self.assertEqual(competitors_pull.shape(rows, META)["competitors"][-1]["domain"],
                         "ohne.example")

    def test_own_domain_is_dropped(self):
        # Der Endpunkt liefert das Ziel selbst mit, sobald es für die
        # Seed-Keywords rankt. Bliebe es drin, stünde der Shop im Report als
        # sein eigener Wettbewerber.
        rows = competitor_block([{"domain": "beispielshop.example", "avg_position": 8.0},
                                  {"domain": "wettbewerb-a.example", "avg_position": 2.0}])
        shaped = competitors_pull.shape(rows, {**META, "target": "beispielshop.example"})
        self.assertEqual([c["domain"] for c in shaped["competitors"]], ["wettbewerb-a.example"])

    def test_own_domain_match_ignores_www_and_case(self):
        rows = competitor_block([{"domain": "WWW.Beispielshop.example", "avg_position": 1.0}])
        shaped = competitors_pull.shape(rows, {**META, "target": "beispielshop.example"})
        self.assertEqual(shaped["competitors"], [])

    def test_platform_domains_are_flagged_not_dropped(self):
        # Dass ein Marktplatz auf den Kategorie-Keywords vor der Brand steht,
        # ist selbst ein Befund. Löschen versteckt ihn.
        rows = competitor_block([{"domain": "instagram.com", "avg_position": 4.0},
                                  {"domain": "wettbewerb-a.example", "avg_position": 2.0}])
        flags = {c["domain"]: c["is_platform"]
                 for c in competitors_pull.shape(rows, META)["competitors"]}
        self.assertTrue(flags["instagram.com"])
        self.assertFalse(flags["wettbewerb-a.example"])

    def test_summary_counts_shops_separately(self):
        rows = competitor_block([{"domain": "instagram.com", "avg_position": 4.0},
                                  {"domain": "wettbewerb-a.example", "avg_position": 2.0}])
        summary = competitors_pull.shape(rows, META)["summary"]
        self.assertEqual(summary["competitors_found"], 2)
        self.assertEqual(summary["competitors_without_platforms"], 1)

    def test_only_platforms_is_a_note(self):
        # Genau der Fall, an dem der domain-seeded Endpunkt gescheitert ist.
        rows = competitor_block([{"domain": "instagram.com", "avg_position": 4.0},
                                  {"domain": "facebook.com", "avg_position": 6.0}])
        self.assertIn("Seed-Keywords", " ".join(competitors_pull.shape(rows, META)["notes"]))

    def test_list_is_capped(self):
        rows = competitor_block([{"domain": f"d{i}.example", "avg_position": float(i)}
                                  for i in range(competitors_pull.MAX_COMPETITORS + 3)])
        shaped = competitors_pull.shape(rows, META)
        self.assertEqual(len(shaped["competitors"]), competitors_pull.MAX_COMPETITORS)
        self.assertTrue(shaped["competitors_truncated"])


class TestKeywordGaps(unittest.TestCase):
    """intersections=false liefert Keywords, für die **target1** rankt und
    target2 nicht. Für eine Content-Lücke ist target1 also der Wettbewerber
    und target2 die eigene Domain, und gelesen wird die Position aus
    `first_domain_serp_element`."""

    def gap_rows(self):
        return [{"target1": "wettbewerb-a.example", "target2": "beispielshop.example",
                 "total_count": 436, "items_count": 2, "items": [
                     {"keyword_data": {"keyword": "outdoorjacke herren",
                                        "keyword_info": {"search_volume": 9900}},
                      "first_domain_serp_element": {"rank_absolute": 1,
                                                     "url": "https://wettbewerb-a.example/x"},
                      "second_domain_serp_element": None},
                     {"keyword_data": {"keyword": "regenjacke",
                                        "keyword_info": {"search_volume": 320}},
                      "first_domain_serp_element": {"rank_absolute": 7,
                                                     "url": "https://wettbewerb-a.example/y"},
                      "second_domain_serp_element": None}]}]

    def test_gap_task_puts_the_competitor_first(self):
        # Die Reihenfolge entscheidet, was die Liste bedeutet. Vertauscht
        # liefert sie die eigenen Stärken unter der Ueberschrift Lücke.
        task = competitors_pull.gap_payload("beispielshop.example", "wettbewerb-a.example",
                                             location_code=2276, language_code="de")
        self.assertEqual(task["target1"], "wettbewerb-a.example")
        self.assertEqual(task["target2"], "beispielshop.example")
        self.assertFalse(task["intersections"])

    def test_rank_comes_from_the_first_domain(self):
        # second_domain_serp_element ist bei intersections=false immer None,
        # weil die eigene Domain dort gerade nicht rankt. Wer es liest,
        # bekommt eine Spalte, die immer leer ist.
        gaps = competitors_pull.shape_gaps(self.gap_rows(), META)["keyword_gaps"]
        self.assertEqual(gaps[0]["competitor_rank"], 1)
        self.assertEqual(gaps[1]["competitor_rank"], 7)

    def test_keyword_and_volume_are_carried_over(self):
        gaps = competitors_pull.shape_gaps(self.gap_rows(), META)["keyword_gaps"]
        self.assertEqual(gaps[0]["keyword"], "outdoorjacke herren")
        self.assertEqual(gaps[0]["search_volume"], 9900)

    def test_gaps_are_sorted_by_volume(self):
        gaps = competitors_pull.shape_gaps(self.gap_rows(), META)["keyword_gaps"]
        self.assertEqual([g["search_volume"] for g in gaps], [9900, 320])

    def test_summary_counts_the_full_set(self):
        shaped = competitors_pull.shape_gaps(self.gap_rows(), META)
        self.assertEqual(shaped["summary_gaps"]["keyword_gaps_found"], 436)
        self.assertEqual(shaped["summary_gaps"]["keyword_gaps_delivered"], 2)
        self.assertEqual(shaped["summary_gaps"]["compared_against"], "wettbewerb-a.example")

    def test_keyword_without_volume_sorts_last(self):
        rows = self.gap_rows()
        rows[0]["items"].append({"keyword_data": {"keyword": "ohne", "keyword_info": {}},
                                  "first_domain_serp_element": {"rank_absolute": 3}})
        gaps = competitors_pull.shape_gaps(rows, META)["keyword_gaps"]
        self.assertEqual(gaps[-1]["keyword"], "ohne")


def offer(seller="wettbewerb-a", price=89.0, rank=1, title="Jacke", kind="google_shopping_serp"):
    return {"type": kind, "title": title, "price": price, "currency": "EUR",
            "seller": seller, "rank_absolute": rank}


def shopping_block(items, keyword="outdoorjacke"):
    return [{"keyword": keyword, "items_count": len(items), "items": items}]


class TestShoppingOffers(unittest.TestCase):
    def test_carousel_entries_are_not_offers(self):
        # google_shopping_carousel sind Kategoriekacheln ohne Preis und
        # Verkäufer. Mitgezählt blähen sie die Angebotszahl auf und
        # verwässern die Aussage "kein eigenes Angebot".
        rows = shopping_block([offer(), offer(seller="wettbewerb-b"),
                                offer(seller=None, price=None, kind="google_shopping_carousel")])
        shaped = shopping_pull.shape(rows, {"brand": "beispielshop"})
        self.assertEqual(shaped["summary"]["offers_total"], 2)
        self.assertEqual(shaped["summary"]["carousel_entries"], 1)

    def test_own_and_foreign_offers_are_counted_separately(self):
        rows = shopping_block([offer(seller="beispielshop"), offer(seller="wettbewerb-a"),
                                offer(seller="wettbewerb-b")])
        summary = shopping_pull.shape(rows, {"brand": "beispielshop"})["summary"]
        self.assertEqual(summary["own_offers"], 1)
        self.assertEqual(summary["competitor_offers"], 2)

    def test_brand_match_is_case_insensitive_and_partial(self):
        rows = shopping_block([offer(seller="Beispielshop GmbH")])
        self.assertEqual(shopping_pull.shape(rows, {"brand": "beispielshop"})["summary"]["own_offers"], 1)

    def test_no_own_offer_is_a_finding_not_an_error(self):
        rows = shopping_block([offer(seller="wettbewerb-a"), offer(seller="wettbewerb-b")])
        shaped = shopping_pull.shape(rows, {"brand": "beispielshop"})
        self.assertEqual(shaped["summary"]["own_offers"], 0)
        self.assertEqual(shaped["summary"]["competitor_offers"], 2)

    def test_price_position_needs_an_own_offer(self):
        # Ohne eigenes Angebot gibt es keinen Preisabstand. Eine 0 läse sich
        # als "gleich teuer wie der Markt".
        rows = shopping_block([offer(seller="wettbewerb-a"), offer(seller="wettbewerb-b")])
        shaped = shopping_pull.shape(rows, {"brand": "beispielshop"})
        self.assertIsNone(shaped["keywords"][0]["own_price_vs_median"])

    def test_price_delta_against_the_median_of_the_others(self):
        rows = shopping_block([offer(seller="beispielshop", price=89.9),
                                offer(seller="wettbewerb-a", price=79.0),
                                offer(seller="wettbewerb-b", price=99.0)])
        shaped = shopping_pull.shape(rows, {"brand": "beispielshop"})
        self.assertAlmostEqual(shaped["keywords"][0]["own_price_vs_median"], 0.9, places=2)

    def test_cheapest_own_offer_counts(self):
        rows = shopping_block([offer(seller="beispielshop", price=120.0),
                                offer(seller="beispielshop", price=80.0),
                                offer(seller="wettbewerb-a", price=100.0)])
        shaped = shopping_pull.shape(rows, {"brand": "beispielshop"})
        self.assertAlmostEqual(shaped["keywords"][0]["own_price_vs_median"], -20.0, places=2)

    def test_currency_is_carried_and_mixed_currencies_are_a_note(self):
        # Ein Preisvergleich über zwei Währungen ist keine Zahl.
        rows = shopping_block([offer(price=89.0), dict(offer(price=95.0), currency="CHF")])
        shaped = shopping_pull.shape(rows, {"brand": "beispielshop"})
        self.assertIn("Währungen", " ".join(shaped["notes"]))
        self.assertEqual(shaped["summary"]["currencies"], ["CHF", "EUR"])

    def test_offer_list_per_keyword_is_capped(self):
        rows = shopping_block([offer(seller=f"s{i}", rank=i)
                                for i in range(shopping_pull.MAX_OFFERS + 5)])
        shaped = shopping_pull.shape(rows, {"brand": "beispielshop"})
        self.assertEqual(len(shaped["keywords"][0]["offers"]), shopping_pull.MAX_OFFERS)
        self.assertTrue(shaped["keywords"][0]["offers_truncated"])

    def test_several_keywords_end_up_side_by_side(self):
        rows = shopping_block([offer()], keyword="a") + shopping_block([offer()], keyword="b")
        shaped = shopping_pull.shape(rows, {"brand": "beispielshop"})
        self.assertEqual([k["keyword"] for k in shaped["keywords"]], ["a", "b"])
        self.assertEqual(shaped["summary"]["keywords_checked"], 2)


class TestShoppingTasks(unittest.TestCase):
    def test_task_ids_are_read_from_the_post_response(self):
        payload = {"status_code": 20000, "tasks": [
            {"status_code": 20100, "id": "abc", "data": {"keyword": "outdoorjacke"}}]}
        self.assertEqual(shopping_pull.task_ids(payload), [("abc", "outdoorjacke")])

    def test_a_rejected_task_is_skipped_not_polled(self):
        # Eine abgelehnte Aufgabe hat keine Ergebnisse und würde trotzdem
        # dreißigmal abgefragt, wenn man ihren Status nicht liest.
        payload = {"status_code": 20000, "tasks": [
            {"status_code": 40501, "id": "abc", "status_message": "Invalid Field"}]}
        self.assertEqual(shopping_pull.task_ids(payload), [])

    def test_several_tasks_keep_their_keywords(self):
        payload = {"status_code": 20000, "tasks": [
            {"status_code": 20100, "id": "a", "data": {"keyword": "eins"}},
            {"status_code": 20100, "id": "b", "data": {"keyword": "zwei"}}]}
        self.assertEqual(shopping_pull.task_ids(payload), [("a", "eins"), ("b", "zwei")])


class TestKeywordCollection(unittest.TestCase):
    def test_seeds_and_gsc_queries_are_merged(self):
        gsc = {"top_queries": [{"query": "outdoorjacke damen"}, {"query": "regenjacke"}]}
        self.assertEqual(keywords_pull.collect(["regenjacke", "softshell"], gsc),
                         ["outdoorjacke damen", "regenjacke", "softshell"])

    def test_deduplicates_case_insensitively(self):
        # "Regenjacke" und "regenjacke" sind für den Endpunkt dasselbe
        # Keyword und würden in zwei Blöcken zweimal bezahlt.
        self.assertEqual(keywords_pull.collect(["Regenjacke"],
                                                {"top_queries": [{"query": "regenjacke"}]}),
                         ["regenjacke"])

    def test_drops_empty_and_overlong_terms(self):
        # Der Endpunkt nimmt 80 Zeichen je Keyword. Ein längeres ließe die
        # ganze Anfrage scheitern, also nach der Bezahlung.
        self.assertEqual(keywords_pull.collect(["", "  ", "x" * 81, "ok"], {}), ["ok"])

    def test_missing_gsc_snapshot_is_not_an_error(self):
        self.assertEqual(keywords_pull.collect(["regenjacke"], None), ["regenjacke"])

    def test_gsc_without_queries_is_not_an_error(self):
        self.assertEqual(keywords_pull.collect(["regenjacke"], {"totals": {}}), ["regenjacke"])


class TestKeywordBatches(unittest.TestCase):
    def test_batches_are_capped_at_the_api_limit(self):
        batches = keywords_pull.batches([f"k{i}" for i in range(2500)])
        self.assertEqual([len(b) for b in batches], [1000, 1000, 500])

    def test_one_keyword_is_one_batch(self):
        self.assertEqual(keywords_pull.batches(["regenjacke"]), [["regenjacke"]])

    def test_no_keywords_means_no_call(self):
        # Eine leere Anfrage kostet genauso viel wie eine volle. Sie wird
        # deshalb gar nicht gestellt.
        self.assertEqual(keywords_pull.batches([]), [])


class TestKeywordShape(unittest.TestCase):
    def test_result_is_read_flat_not_nested(self):
        # Anders als die Labs-Endpunkte liefert search_volume die Zeilen
        # direkt in `result`, nicht unter result[0].items. Wer hier unwrap()
        # benutzt, findet nichts und schreibt null Keywords.
        rows = [{"keyword": "a", "search_volume": 100}]
        self.assertEqual(len(keywords_pull.shape(rows, META)["keywords"]), 1)

    def test_summary_counts_terms_with_and_without_volume(self):
        rows = [{"keyword": "a", "search_volume": 1000, "competition_index": 40, "cpc": 0.5},
                {"keyword": "b", "search_volume": 0},
                {"keyword": "c", "search_volume": None}]
        summary = keywords_pull.shape(rows, META)["summary"]
        self.assertEqual(summary["keywords_returned"], 3)
        self.assertEqual(summary["keywords_with_volume"], 1)
        self.assertEqual(summary["search_volume_total"], 1000)

    def test_volume_none_is_not_counted_as_zero_volume(self):
        # None heißt "Google liefert dafür keine Zahl", 0 heißt "kein
        # Suchvolumen". Der Unterschied entscheidet, ob ein Begriff als tot
        # oder als ungemessen im Report steht.
        shaped = keywords_pull.shape([{"keyword": "c", "search_volume": None}], META)
        self.assertEqual(shaped["summary"]["keywords_without_data"], 1)
        self.assertEqual(shaped["summary"]["search_volume_total"], 0)

    def test_zero_volume_is_measured_not_missing(self):
        shaped = keywords_pull.shape([{"keyword": "b", "search_volume": 0}], META)
        self.assertEqual(shaped["summary"]["keywords_without_data"], 0)
        self.assertEqual(shaped["summary"]["keywords_with_volume"], 0)

    def test_keeps_the_monthly_series_sorted_and_padded(self):
        rows = [{"keyword": "a", "search_volume": 10, "monthly_searches": [
            {"year": 2026, "month": 9, "search_volume": 8},
            {"year": 2026, "month": 8, "search_volume": 12}]}]
        monthly = keywords_pull.shape(rows, META)["keywords"][0]["monthly"]
        self.assertEqual([m["month"] for m in monthly], ["2026-08", "2026-09"])

    def test_monthly_entry_without_a_month_is_skipped(self):
        rows = [{"keyword": "a", "search_volume": 10,
                 "monthly_searches": [{"search_volume": 5}]}]
        self.assertEqual(keywords_pull.shape(rows, META)["keywords"][0]["monthly"], [])

    def test_keywords_are_sorted_by_volume(self):
        rows = [{"keyword": "klein", "search_volume": 10},
                {"keyword": "gross", "search_volume": 9900}]
        shaped = keywords_pull.shape(rows, META)
        self.assertEqual([k["keyword"] for k in shaped["keywords"]], ["gross", "klein"])

    def test_keyword_without_volume_sorts_last(self):
        rows = [{"keyword": "ohne", "search_volume": None},
                {"keyword": "mit", "search_volume": 10}]
        shaped = keywords_pull.shape(rows, META)
        self.assertEqual(shaped["keywords"][-1]["keyword"], "ohne")

    def test_list_is_capped_but_the_summary_counts_everything(self):
        rows = [{"keyword": f"k{i}", "search_volume": 1} for i in range(keywords_pull.MAX_ROWS + 20)]
        shaped = keywords_pull.shape(rows, META)
        self.assertEqual(len(shaped["keywords"]), keywords_pull.MAX_ROWS)
        self.assertTrue(shaped["keywords_truncated"])
        self.assertEqual(shaped["summary"]["keywords_returned"], keywords_pull.MAX_ROWS + 20)

    def test_two_batches_end_up_in_one_list(self):
        shaped = keywords_pull.shape([{"keyword": "a", "search_volume": 10}],
                                      META, previous=[{"keyword": "b", "search_volume": 20}])
        self.assertEqual(shaped["summary"]["search_volume_total"], 30)


def backlink_block(items):
    """Die echte Form: result[0].items, bestaetigt am 07.09.2026."""
    return [{"target": "beispielshop.example", "total_count": len(items),
             "items_count": len(items), "items": items}]


class TestBacklinksSummary(unittest.TestCase):
    def test_reads_the_first_result_row(self):
        rows = [{"backlinks": 4200, "referring_domains": 310,
                 "referring_main_domains": 280, "rank": 41,
                 "broken_backlinks": 12, "referring_links_types": {"anchor": 4000}}]
        summary = backlinks_pull.shape(rows, META)["summary"]
        self.assertEqual(summary["backlinks"], 4200)
        self.assertEqual(summary["referring_domains"], 310)
        self.assertEqual(summary["broken_backlinks"], 12)

    def test_empty_result_is_a_note_not_a_crash(self):
        # Eine Domain ohne Backlinks ist ein Befund, kein Fehler.
        shaped = backlinks_pull.shape([], META)
        self.assertEqual(shaped["summary"]["backlinks"], 0)
        self.assertIn("keine Daten", " ".join(shaped["notes"]))


class TestReferringDomains(unittest.TestCase):
    def test_list_is_capped_and_marked(self):
        many = backlink_block([{"domain": f"d{i}.example", "backlinks": i, "rank": 10}
                                for i in range(backlinks_pull.MAX_DOMAINS + 5)])
        shaped = backlinks_pull.shape_domains(many, META)
        self.assertEqual(len(shaped["referring_domains_top"]), backlinks_pull.MAX_DOMAINS)
        self.assertTrue(shaped["referring_domains_truncated"])
        self.assertEqual(shaped["summary_domains"]["referring_domains_returned"],
                         backlinks_pull.MAX_DOMAINS + 5)

    def test_dofollow_share_is_computed_over_all_rows_not_the_capped_list(self):
        # Die Quote muss über die volle Menge gehen. Über die gekürzte Liste
        # gerechnet wäre sie eine andere Zahl mit demselben Namen.
        many = backlink_block([{"domain": f"d{i}.example", "referring_pages": 2,
                                 "referring_pages_nofollow": 2 if i % 2 else 0}
                                for i in range(backlinks_pull.MAX_DOMAINS + 100)])
        shaped = backlinks_pull.shape_domains(many, META)
        self.assertAlmostEqual(shaped["summary_domains"]["dofollow_share"], 0.5, places=2)

    def test_a_domain_counts_as_dofollow_if_any_page_follows(self):
        # Das Feld "dofollow" gibt es nicht. Die Items fuehren referring_pages
        # und referring_pages_nofollow; eine Domain folgt, wenn mindestens
        # eine ihrer Seiten folgt.
        rows = backlink_block([{"domain": "a.example", "referring_pages": 5,
                                 "referring_pages_nofollow": 4}])
        self.assertEqual(backlinks_pull.shape_domains(rows, META)["summary_domains"]["dofollow_share"], 1.0)

    def test_a_fully_nofollow_domain_does_not_count(self):
        rows = backlink_block([{"domain": "a.example", "referring_pages": 3,
                                 "referring_pages_nofollow": 3}])
        self.assertEqual(backlinks_pull.shape_domains(rows, META)["summary_domains"]["dofollow_share"], 0.0)

    def test_missing_page_counts_are_not_silently_dofollow(self):
        # Fehlen beide Felder, ist die Quote nicht berechenbar. Eine 1.0 waere
        # eine Behauptung, eine 0.0 eine andere.
        rows = backlink_block([{"domain": "a.example"}])
        self.assertIsNone(backlinks_pull.shape_domains(rows, META)["summary_domains"]["dofollow_share"])

    def test_no_domains_gives_no_share_not_zero(self):
        # Ohne verweisende Domains gibt es keine Dofollow-Quote. Eine 0 läse
        # sich als "keine einzige folgt".
        self.assertIsNone(backlinks_pull.shape_domains([], META)["summary_domains"]["dofollow_share"])


class TestAuthorityAndSpam(unittest.TestCase):
    def test_authority_is_read_per_domain(self):
        rows = [{"items": [{"target": "beispielshop.example", "rank": 154},
                            {"target": "wettbewerb-a.example", "rank": 391}]}]
        entry = backlinks_pull.shape_ranks(rows, META)["authority"][1]
        self.assertEqual(entry["domain"], "wettbewerb-a.example")
        self.assertEqual(entry["rank"], 391)

    def test_unexpected_shape_gives_an_empty_list_not_a_crash(self):
        # Die Form ist seit dem 07.09.2026 festgeschrieben: result[0].items.
        # Eine andere Antwort darf den Pull nicht abbrechen, aber sie darf
        # auch nicht stillschweigend als Daten durchgehen.
        self.assertEqual(backlinks_pull.shape_ranks(["kaputt"], META)["authority"], [])

    def test_spam_score_is_read_per_domain(self):
        rows = [{"items": [{"target": "beispielshop.example", "spam_score": 20}]}]
        self.assertEqual(
            backlinks_pull.shape_spam(rows, META)["spam_score"][0]["spam_score"], 20)

    def test_missing_score_stays_none(self):
        # 0 heißt "sauber", None heißt "nicht gemessen". Der Unterschied
        # entscheidet, ob eine Disavow-Empfehlung im Report steht.
        rows = [{"items": [{"target": "x.example"}]}]
        self.assertIsNone(
            backlinks_pull.shape_spam(rows, META)["spam_score"][0]["spam_score"])

    def test_own_domain_is_marked_in_the_comparison(self):
        # Der eigene Score ohne Vergleichswert ist keine Aussage. Damit die
        # Analyse ihn findet, ist die eigene Domain markiert.
        rows = [{"items": [{"target": "beispielshop.example", "rank": 154},
                            {"target": "wettbewerb-a.example", "rank": 391}]}]
        shaped = backlinks_pull.shape_ranks(rows, {**META, "target": "beispielshop.example"})
        self.assertTrue(shaped["authority"][0]["own"])
        self.assertFalse(shaped["authority"][1]["own"])


class TestAnchors(unittest.TestCase):
    def test_anchors_are_capped(self):
        many = backlink_block([{"anchor": f"a{i}", "backlinks": i}
                                for i in range(backlinks_pull.MAX_ANCHORS + 3)])
        shaped = backlinks_pull.shape_anchors(many, META)
        self.assertEqual(len(shaped["anchors_top"]), backlinks_pull.MAX_ANCHORS)
        self.assertTrue(shaped["anchors_truncated"])
