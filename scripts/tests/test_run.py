"""Lauf-IDs, Zeiträume und Fälligkeit."""
import unittest
from datetime import date, timedelta

from audit import run


class TestRunId(unittest.TestCase):
    def test_builds_id_from_date_and_cadence(self):
        self.assertEqual(run.run_id(date(2026, 10, 1), "month"), "2026-10-01-month")

    def test_reads_id_back(self):
        self.assertEqual(run.parse_run_id("2026-10-05-week"), (date(2026, 10, 5), "week"))

    def test_old_id_without_cadence_stays_readable(self):
        # Ordner aus der Zeit vor dieser Spec tragen nur das Datum.
        self.assertEqual(run.parse_run_id("2026-07-01"), (date(2026, 7, 1), None))

    def test_unknown_cadence_raises(self):
        with self.assertRaises(ValueError):
            run.run_id(date(2026, 10, 1), "quarter")


class TestPeriod(unittest.TestCase):
    def test_month_is_the_last_full_month(self):
        self.assertEqual(
            run.period("month", date(2026, 10, 5)),
            {"start": "2026-09-01", "end": "2026-09-30", "granularity": "month"},
        )

    def test_month_at_the_year_boundary(self):
        self.assertEqual(
            run.period("month", date(2026, 1, 3)),
            {"start": "2025-12-01", "end": "2025-12-31", "granularity": "month"},
        )

    def test_week_is_monday_to_sunday_before(self):
        # 2026-10-07 ist ein Mittwoch, die letzte volle Woche endet am 04.10.
        self.assertEqual(
            run.period("week", date(2026, 10, 7)),
            {"start": "2026-09-28", "end": "2026-10-04", "granularity": "week"},
        )

    def test_week_on_a_monday(self):
        # An einem Montag ist die letzte volle Woche die unmittelbar davor.
        self.assertEqual(
            run.period("week", date(2026, 10, 5)),
            {"start": "2026-09-28", "end": "2026-10-04", "granularity": "week"},
        )

    def test_audit_has_no_fixed_period(self):
        self.assertIsNone(run.period("audit", date(2026, 10, 5)))


class TestPreviousYear(unittest.TestCase):
    def test_period_id_lies_outside_the_run_namespace(self):
        self.assertEqual(
            run.period_id(date(2025, 10, 1), date(2025, 10, 31)),
            "zeitraum-2025-10-01-2025-10-31",
        )

    def test_previous_year_shifts_by_one_year(self):
        self.assertEqual(
            run.previous_year(date(2026, 9, 1), date(2026, 9, 30)),
            (date(2025, 9, 1), date(2025, 9, 30)),
        )

    def test_previous_year_catches_february_29(self):
        # 2028 ist ein Schaltjahr, 2027 nicht.
        self.assertEqual(
            run.previous_year(date(2028, 2, 1), date(2028, 2, 29)),
            (date(2027, 2, 1), date(2027, 2, 28)),
        )


class TestIsDue(unittest.TestCase):
    def test_source_every_run_is_always_due(self):
        self.assertTrue(run.is_due("ga4", "week", last_pulled=date(2026, 10, 4), today=date(2026, 10, 5)))

    def test_monthly_source_not_due_in_a_weekly_run(self):
        self.assertFalse(run.is_due("crawl", "week", last_pulled=date(2026, 10, 1), today=date(2026, 10, 5)))

    def test_monthly_source_due_once_a_month_has_passed(self):
        self.assertTrue(run.is_due("crawl", "week", last_pulled=date(2026, 8, 20), today=date(2026, 10, 5)))

    def test_never_pulled_source_is_always_due(self):
        self.assertTrue(run.is_due("backlinks", "week", last_pulled=None, today=date(2026, 10, 5)))

    def test_audit_pulls_everything(self):
        self.assertTrue(run.is_due("backlinks", "audit", last_pulled=date(2026, 10, 4), today=date(2026, 10, 5)))

    def test_state_in_the_future_pulls_instead_of_skipping(self):
        # Uhrzeit-Versatz. Ein negativer Abstand darf die Quelle nicht still
        # überspringen, sonst stehen alte Zahlen als neue im Report.
        self.assertTrue(run.is_due("ga4", "week", last_pulled=date(2026, 10, 6), today=date(2026, 10, 5)))

    def test_monthly_source_not_due_twice_at_month_end(self):
        # Am 01. und am 28. desselben Monats: genau einmal fällig.
        self.assertFalse(run.is_due("dfs_rankings", "week", last_pulled=date(2026, 10, 1), today=date(2026, 10, 28)))

    def test_monthly_source_due_in_the_next_calendar_month(self):
        self.assertTrue(run.is_due("dfs_rankings", "week", last_pulled=date(2026, 10, 28), today=date(2026, 11, 2)))

    def test_quarterly_source_not_due_in_the_same_quarter(self):
        self.assertFalse(run.is_due("backlinks", "month", last_pulled=date(2026, 7, 1), today=date(2026, 9, 30)))

    def test_quarterly_source_due_in_the_next_quarter(self):
        self.assertTrue(run.is_due("backlinks", "month", last_pulled=date(2026, 9, 30), today=date(2026, 10, 1)))

    def test_unknown_source_falls_back_to_every_run(self):
        # Sicherheitsrichtung: lieber einmal zu viel ziehen.
        self.assertTrue(run.is_due("gibt_es_nicht", "week", last_pulled=date(2026, 10, 4), today=date(2026, 10, 5)))

    def test_config_overrides_the_cadence(self):
        # ga4 ist sonst "run". Als Monatsquelle konfiguriert nicht fällig.
        self.assertFalse(run.is_due("ga4", "week", last_pulled=date(2026, 10, 1),
                                     today=date(2026, 10, 5), cadences={"ga4": "month"}))

    def test_force_all_pulls_even_what_is_not_due(self):
        self.assertTrue(run.is_due("backlinks", "week", last_pulled=date(2026, 10, 4),
                                    today=date(2026, 10, 5), force_all=True))

    def test_unknown_source_cadence_raises(self):
        with self.assertRaises(ValueError):
            run.is_due("ga4", "week", last_pulled=date(2026, 10, 1),
                       today=date(2026, 10, 5), cadences={"ga4": "täglich"})

    def test_empty_override_raises_instead_of_silently_applying(self):
        # Ein leerer Wert ist ein kaputter Eintrag, kein fehlender.
        with self.assertRaises(ValueError):
            run.is_due("ga4", "week", last_pulled=date(2026, 10, 1),
                       today=date(2026, 10, 5), cadences={"ga4": ""})

    def test_monthly_source_across_the_year_boundary(self):
        self.assertTrue(run.is_due("dfs_rankings", "week",
                                    last_pulled=date(2025, 12, 20), today=date(2026, 1, 2)))


def _sequence(source: str, start_state, since, until):
    """Eine Folge täglicher Prüfungen: der eigene Termin wird zum letzten Stand."""
    state, hits, tag = start_state, [], since
    while tag <= until:
        if run.is_due(source, "week", state, tag):
            hits.append(tag)
            state = tag
        tag += timedelta(days=1)
    return hits


class TestIsDueOverTime(unittest.TestCase):
    """Sichert die Aussage im Docstring von is_due ab.

    Die Einzeltests oben prüfen je einen Aufruf. Der Fehler, den diese Klasse
    fängt, entsteht erst über mehrere Läufe: ein Tagesabstand statt einer
    Kalendergrenze lässt den Termin mit jedem Zyklus nach vorn wandern, und
    das sieht man einem Einzelaufruf nicht an.
    """

    def test_monthly_source_fires_twelve_times_a_year(self):
        hits = _sequence("dfs_rankings", None, date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual(len(hits), 12)
        self.assertTrue(all(t.day == 1 for t in hits))

    def test_quarterly_source_fires_four_times_a_year(self):
        hits = _sequence("backlinks", None, date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual(len(hits), 4)

    def test_state_on_the_last_of_the_month_settles_in(self):
        # Der dokumentierte Randfall: Stand am 31.01., am 01.02. wieder fällig.
        # Danach liegt der Termin auf dem Monatsersten und bleibt dort.
        hits = _sequence("dfs_rankings", date(2026, 1, 31), date(2026, 2, 1), date(2026, 12, 31))
        self.assertEqual(hits[0], date(2026, 2, 1))
        self.assertEqual(len(hits), 11)
        self.assertTrue(all(t.day == 1 for t in hits))


if __name__ == "__main__":
    unittest.main()
