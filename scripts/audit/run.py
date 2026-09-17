#!/usr/bin/env python3
"""Lauf-ID, Kadenz, Zeiträume und Fälligkeit eines Laufs.

Die Lauf-ID trägt immer die Kadenz, sonst kollidieren ein Wochen- und ein
Monatslauf am selben Tag still miteinander (Spec Abschnitt 3). Ordner aus der
Zeit davor tragen nur das Datum und bleiben lesbar.
"""
import calendar
from datetime import date, timedelta

CADENCES = ("audit", "week", "month")

#: Kadenz je Quelle, Spec Abschnitt 3. "run" heißt: bei jedem Lauf.
SOURCE_CADENCE = {
    "shopify": "run", "ga4": "run", "gsc": "run", "ads": "run",
    "esp": "run", "meta": "run", "cwv": "run", "measures": "run",
    "crawl": "month", "catalogue": "month", "cwv_lab": "month",
    "dfs_rankings": "month", "dfs_keywords": "month", "geo": "month",
    "reviews": "month", "screens": "month",
    "backlinks": "quarter", "competitors": "quarter",
    "shopping": "quarter", "shop_tech": "quarter",
}

#: Erlaubte Kadenzen einer Quelle.
SOURCE_CADENCES = ("run", "month", "quarter")


def run_id(day: date, cadence: str) -> str:
    """`2026-10-01-month`. Unbekannte Kadenz ist ein Fehler, keine Warnung."""
    if cadence not in CADENCES:
        raise ValueError(f"unbekannte Kadenz: {cadence!r}, erlaubt sind {CADENCES}")
    return f"{day.isoformat()}-{cadence}"


def parse_run_id(value: str) -> tuple[date, str | None]:
    """Zerlegt eine Lauf-ID. Alte Ordner ohne Kadenz geben None zurück."""
    parts = value.split("-")
    day = date.fromisoformat("-".join(parts[:3]))
    if len(parts) == 3:
        return day, None
    cadence = "-".join(parts[3:])
    if cadence not in CADENCES:
        raise ValueError(f"unbekannte Kadenz in {value!r}: {cadence!r}")
    return day, cadence


def period(cadence: str, today: date) -> dict | None:
    """Der Berichtszeitraum als Block. Ein Audit hat keinen, er zieht je Quelle maximal.

    Der Block hat dieselbe Form wie in jeder Snapshot-Datei, `start`, `end` und
    `granularity`, die Daten als ISO-Text. Genau dorthin geht er auch: in
    `state.json` und als `--start`/`--end` in die Pulls. Ein Tupel aus
    `date`-Objekten wäre für die Rechnung bequemer, überlebt `json.dumps` aber
    nicht, und die Umwandlung müsste dann jeder Aufrufer selbst machen oder
    eine Ebene tiefer geraten werden.

    Gerechnet wird trotzdem auf `date`: `previous_year()` und `period_id()`
    nehmen und liefern `date`. Wer aus einem Block dorthin zurück will, holt
    sich die beiden Werte mit `date.fromisoformat()`.
    """
    if cadence == "audit":
        return None
    if cadence == "month":
        last_of_previous_month = today.replace(day=1) - timedelta(days=1)
        first = last_of_previous_month.replace(day=1)
        return _block(first, last_of_previous_month, "month")
    if cadence == "week":
        # Montag dieser Woche, davon eine Woche zurück.
        monday = today - timedelta(days=today.weekday())
        start = monday - timedelta(days=7)
        return _block(start, start + timedelta(days=6), "week")
    raise ValueError(f"unbekannte Kadenz: {cadence!r}")


def _block(start: date, end: date, granularity: str) -> dict:
    """Der eine Ort, an dem ein Zeitraum-Block gebaut wird."""
    return {"start": start.isoformat(), "end": end.isoformat(),
            "granularity": granularity}


def previous_year(start: date, end: date) -> tuple[date, date]:
    """Derselbe Zeitraum ein Jahr früher, mit Schaltjahr-Klemmung."""
    return _minus_one_year(start), _minus_one_year(end)


def _minus_one_year(day: date) -> date:
    year = day.year - 1
    last_day = calendar.monthrange(year, day.month)[1]
    return date(year, day.month, min(day.day, last_day))


def period_id(start: date, end: date) -> str:
    """Ablage-ID für nachträglich gezogene Vergleichszeiträume.

    Bewusst außerhalb des Lauf-Namensraums: eine Lauf-ID ist nach dem
    Lauf-Datum benannt, und ein Lauf am 01.10. berichtet über den September.
    """
    return f"zeitraum-{start.isoformat()}-{end.isoformat()}"


def is_due(source: str, cadence: str, last_pulled: date | None, today: date,
           cadences: dict[str, str] | None = None, force_all: bool = False) -> bool:
    """Ist die Quelle in diesem Lauf zu ziehen?

    Ein Audit zieht immer alles, `force_all=True` erzwingt dasselbe für einen
    Report. Sonst entscheidet die Kadenz der Quelle. Eine nie gezogene Quelle
    ist fällig.

    `cadences` überschreibt die Voreinstellung je Quelle, so wie es
    `config.json > cadences` erlaubt. Ohne Eintrag gilt `SOURCE_CADENCE`, und
    für eine dort unbekannte Quelle "run": lieber einmal zu viel ziehen als
    still mit altem Stand berichten.

    Gerechnet wird gegen Kalendergrenzen, nicht gegen einen Tagesabstand.
    28 Tage sind kein Monat: eine Monatsquelle würde damit 14 Mal im Jahr
    fällig statt 12, eine Quartalsquelle 5 Mal statt 4, weil sich der Termin
    mit jedem Zyklus nach vorn schiebt. Bei bezahlten Quellen ist das bares
    Geld gegen den Budgetdeckel.

    Am Rand eines Kalenderzeitraums wird dafür bewusst einmal zu viel gezogen:
    eine Quelle, deren letzter Stand auf dem 31. Januar liegt, ist am 1.
    Februar wieder fällig. Das trifft je Fehlausrichtung genau einmal zu, im
    Regelfall beim ersten Lauf eines Kunden, und richtet sich danach von selbst
    auf den Monatsersten aus. Eine Mindestwartezeit dagegen wäre ein zweiter
    Mechanismus samt Schwellenwert für eine Regel, die sonst in einem Satz
    gilt; den Kostenfall fängt der Budgetdeckel aus Spec Abschnitt 13. Wer das
    ändert, dreht es leicht in die Drift zurück.
    """
    if force_all or cadence == "audit":
        return True
    if last_pulled is None:
        return True
    if last_pulled > today:
        # Uhrzeit-Versatz oder ein falsch geschriebener Stand. Ein negativer
        # Abstand würde die Quelle still überspringen, also lieber ziehen.
        return True
    if cadences and source in cadences:
        # Kein `or`: ein leerer Wert ist ein kaputter Eintrag und muss auffallen,
        # statt still als fehlender Eintrag durchzugehen.
        source_cadence = cadences[source]
    else:
        source_cadence = SOURCE_CADENCE.get(source, "run")
    if source_cadence not in SOURCE_CADENCES:
        raise ValueError(f"unbekannte Quellen-Kadenz: {source_cadence!r}")
    if source_cadence == "run":
        return True
    if source_cadence == "month":
        return (last_pulled.year, last_pulled.month) < (today.year, today.month)
    return _quarter(last_pulled) < _quarter(today)


def _quarter(day: date) -> tuple[int, int]:
    """Jahr und Quartalsnummer, vergleichbar als Tupel."""
    return day.year, (day.month - 1) // 3 + 1
