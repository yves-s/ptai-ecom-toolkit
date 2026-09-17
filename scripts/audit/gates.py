#!/usr/bin/env python3
"""Sperren, die vor dem Einfrieren eines Baseline-Blocks greifen.

Ein Block ist unveränderlich, sobald er steht. Manche Zahlen dürfen aber gar
nicht erst eingefroren werden, weil der Shop zum Messzeitpunkt in einem
Zustand war, den die Zahl nicht abbildet. Der belegte Fall ist der laufende
Preistest: teilt ein A/B-Werkzeug die Besucher auf zwei Preise auf, ist die
gemessene Conversion Rate der Mittelwert zweier Shops, und jeder spätere
Vergleich rechnet gegen einen Nullpunkt, den es nie gab.

Diese Regel stand bisher nur als Satz im Ablauf der Orchestrator-Skill.
Ein Satz in einer Prosa-Anleitung wird im Lauf übersprungen; deshalb hier.
"""

#: Kennungen, an denen ein Preistest-Werkzeug im Seitenquelltext sichtbar
#: wird. Bewusst kurz und durch Beobachtung gewachsen, nicht geraten: hier
#: steht nur, was tatsächlich einmal in einem Crawl gesehen oder in der Spec
#: benannt wurde (Abschnitt 8 nennt Intelligems). Wer ein weiteres Werkzeug
#: antrifft, ergänzt es hier und schreibt den Shop dazu.
PRICE_TEST_MARKERS = (
    "intelligems",
)


def _inline_tag_counts(crawl: dict) -> dict:
    """ID zu Seitenzahl, bevorzugt aus dem findings_index.

    `pages[]` ist bei 300 Seiten schon 2,7 MB und wird nur gelesen, wenn der
    Index fehlt, also bei Crawls aus der Zeit vor dem Index.
    """
    indexed = ((crawl.get("findings_index") or {}).get("inline_tag_ids") or {})
    if indexed:
        return dict(indexed)
    counts: dict = {}
    for page in crawl.get("pages") or []:
        for tag_id in page.get("inline_tag_ids") or []:
            counts[tag_id] = counts.get(tag_id, 0) + 1
    return counts


def _script_host_counts(crawl: dict) -> dict:
    indexed = ((crawl.get("findings_index") or {}).get("script_hosts") or {})
    if indexed:
        return dict(indexed.get("counts") or indexed)
    counts: dict = {}
    for page in crawl.get("pages") or []:
        for source in page.get("scripts") or []:
            counts[str(source)] = counts.get(str(source), 0) + 1
    return counts


def price_test_signals(crawl: dict | None) -> list[str]:
    """Belege für ein laufendes Preistest-Werkzeug, je einer als Satz.

    Gesucht wird in den inline eingebauten Kennungen und in den geladenen
    Fremdskripten des Crawls. Die Seitenzahl steht im Beleg, weil sie den
    Unterschied macht: eine Kennung auf drei von 300 Seiten ist ein Rest, eine
    auf allen Seiten ist ein laufender Test.
    """
    if not crawl:
        return []
    signals = []
    for source, entries in (("Tag", _inline_tag_counts(crawl)),
                             ("Skript", _script_host_counts(crawl))):
        for name, pages in entries.items():
            lowered = str(name).lower()
            if any(marker in lowered for marker in PRICE_TEST_MARKERS):
                signals.append(f"{source} {name} auf {pages} Seiten")
    return signals


def finding_signals(findings: list | None) -> list[str]:
    """Belege aus der Datenqualitäts-Analyse.

    Der Crawl sieht nur, was im Seitenquelltext steht. Ein Preistest, der
    server-seitig ausgespielt wird, hinterlässt dort nichts, und dann ist der
    Agent die einzige Quelle: `audit-data-quality` sucht in Kernfrage 6
    ausdrücklich nach laufenden A/B- und Preistests. Am 06.09.2026 lief genau
    so ein Test site-weit über den gesamten Messzeitraum.
    """
    signals = []
    for finding in findings or []:
        text = " ".join(str(finding.get(k) or "") for k in ("title", "evidence", "statement"))
        lowered = text.lower()
        if any(word in lowered for word in ("preistest", "price test", "a/b-test", "ab-test")):
            signals.append(f"Befund der Datenqualitäts-Analyse: {text.strip()[:180]}")
    return signals


def price_test_verdict(crawl: dict | None, findings: list | None = None) -> dict:
    """Das Ergebnis der Preistest-Prüfung, so wie `write_block()` es erwartet.

    Drei Felder, und `checked` ist das wichtigste: ohne Crawl wurde nicht
    geprüft, und das ist etwas anderes als "nichts gefunden". Der
    Conversion-Block darf auf eine ungeprüfte Lage nicht gebaut werden.

    **Ein negativer Befund ist kein Beweis.** Er heißt "kein bekanntes
    Werkzeug gefunden", nicht "kein Preistest". Die Markerliste ist durch
    Beobachtung gewachsen und kennt nicht jedes Werkzeug; der Beleg sagt das
    ausdrücklich, damit niemand eine Sicherheit hineinliest, die die Prüfung
    nicht hergibt.
    """
    # `None` heißt: es gab keinen Crawl. Ein leeres Dict heißt: der Crawl lief
    # und hat nichts gefunden. Wer beides über Falsiness zusammenwirft, meldet
    # einen ungeprüften Lauf als geprüft oder umgekehrt.
    if crawl is None and not findings:
        return {"checked": False, "running": False,
                "evidence": "Weder Crawl noch Analyse-Befunde im Lauf, "
                             "Preistest nicht geprüft."}
    signals = price_test_signals(crawl) + finding_signals(findings)
    if signals:
        return {"checked": True, "running": True,
                "evidence": "Preistest-Werkzeug gefunden: " + "; ".join(signals)}
    return {"checked": True, "running": False,
            "evidence": ("Kein bekanntes Preistest-Werkzeug im Crawl gefunden. "
                          "Das schließt ein unbekanntes Werkzeug nicht aus.")}
