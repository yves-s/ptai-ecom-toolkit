#!/usr/bin/env python3
"""Health Score je Sektion, je Bereich und gesamt.

Die Rechenweise ist bewusst dieselbe wie in `scripts/report/sales/score.mjs`,
der Engine des audit-light: 100 minus Strafpunkte je Befund, gewichtet nach
Schweregrad und Sicherheit, mit abnehmendem Ertrag. Zwei Engines fuer dieselbe
Frage waeren zwei Antworten, und beim ersten Widerspruch glaubt niemand mehr
einer von beiden.

**Woran der Score gemessen wird, und woran nicht.** Es gibt keinen belastbaren
oeffentlichen Benchmark fuer einen Shop dieser Groesse und dieses Sortiments;
die kursierenden Branchenzahlen stammen aus Aggregator-Blogs, und eine
gescrapte Zahl macht den Report angreifbar. Der Score vergleicht deshalb gegen
drei Dinge, die alle im Dokument selbst stehen:

1. **100**, also einen Shop ohne Befunde in diesem Bereich.
2. **Das Ziel**, also den Stand nach Umsetzung der gefundenen Massnahmen.
3. **Den letzten Lauf.** Das ist der eigentliche Zweck: die Baseline friert
   den heutigen Score ein, und der naechste Report misst dagegen.

**Der Deckel bei 92 ist Absicht.** Ein Audit prueft, was er pruefen kann; 100
wuerde behaupten, es gaebe nichts mehr zu finden. Der Boden bei 35 verhindert,
dass eine gruendlich geprueste Sektion allein durch die Menge ihrer Befunde
gegen null laeuft.

**Eine Sektion ohne Datengrundlage bekommt keinen Score, sondern `None`.** Sonst
sieht ein Bereich, den niemand pruefen konnte, aus wie ein Bereich ohne
Probleme. Ihr Gewicht wird auf die uebrigen verteilt.
"""
from __future__ import annotations

#: Sektion zu Bereich, plus Gewicht des Bereichs am Gesamtscore. Die
#: Gewichtung folgt der Umsatzgleichung: was den Kauf betrifft, wiegt am
#: schwersten, danach die Sichtbarkeit, die ihn ueberhaupt ermoeglicht.
#: `shop` speist keinen Score, das ist eine Bestandsaufnahme, keine Bewertung.
#: Die Bereichsnamen sind die der Disziplinen, nicht umschriebene. "Kaufen"
#: und "Gefunden werden" standen bis zum 07.09.2026 hier, waehrend die
#: Abschnitte darunter laengst Conversion Rate Optimierung und
#: Suchmaschinenoptimierung hiessen. Yves dazu: *"Warum haben die immer noch
#: diese fiktiven, selbst ausgedachten Titel?"*
#: **Die Namen sind die der Disziplin, nicht selbst gebaute.** Bis zum
#: 09.09.2026 hiessen sie "Conversion und Sortiment", "Sichtbarkeit und
#: Akquise", "Technische Performance" und "Tracking und Datenqualität".
#: Yves dazu: *"Warum stehen da schon wieder irgendwelche anderen
#: ausgedachten Headlines? Können wir nicht mal die Fachbegriffe verwenden."*
#: Die Vierteilung selbst ist Standard im E-Commerce-Audit (Acquisition,
#: Conversion, Technical Performance, Analytics), nur die Benennung war es
#: nicht. "Akquise" ist dabei die eingedeutschte Haelfte von Akquisition.
AREAS = {
    "conversion": {"label": "Conversion Rate Optimierung", "gewicht": 0.40,
                   "sektionen": ("conversion", "catalogue", "commerce",
                                 "trust")},
    "sichtbarkeit": {"label": "Akquisition", "gewicht": 0.30,
                     "sektionen": ("seo", "geo", "competition", "sea", "traffic")},
    "technik": {"label": "Web Performance", "gewicht": 0.15,
                "sektionen": ("tech",)},
    "tracking": {"label": "Tracking und Attribution", "gewicht": 0.15,
                 "sektionen": ("measurement",)},
}

#: Strafpunkte je Befund, nach Schweregrad. Dieselben Verhaeltnisse wie in
#: score.mjs (crit 14, warn 5, ok 0).
PENALTY = {"hoch": 14, "mittel": 5, "gering": 1}

#: Wie sicher der Befund ist, als Faktor auf die Strafe. Ein Verdacht kostet
#: weniger als eine Messung.
CERTAINTY = {"confirmed": 1.0, "plausible": 0.7, "hypothesis": 0.4}

FLOOR, DECKEL = 35, 92

#: Abnehmender Ertrag plus Deckel auf die mittleren Befunde: eine gruendlich
#: geprueste Sektion soll nicht allein durch die MENGE ihrer Befunde gegen den
#: Boden laufen. Schwere Befunde zaehlen alle, die sind selten. Von den
#: mittleren zaehlen die fuenf schwersten, sonst misst der Score die Pruefteife
#: statt die Shop-Qualitaet.
HIGH_DAMPING, MITTEL_DAEMPFUNG, MITTEL_DECKEL = 0.8, 0.55, 5


def section_score(findings: list[dict]) -> int:
    """100 minus Strafpunkte, gedeckelt und gebodet."""
    hoch, mittel, gering = [], [], []
    for f in findings:
        gewicht = CERTAINTY.get(f.get("confidence"), 0.7)
        {"hoch": hoch, "mittel": mittel}.get(f.get("_schwere"), gering).append(gewicht)
    hoch.sort(reverse=True)
    mittel.sort(reverse=True)
    strafe = sum(PENALTY["hoch"] * g * HIGH_DAMPING ** i
                 for i, g in enumerate(hoch))
    strafe += sum(PENALTY["mittel"] * g * MITTEL_DAEMPFUNG ** i
                  for i, g in enumerate(mittel[:MITTEL_DECKEL]))
    strafe += sum(PENALTY["gering"] * g for g in gering[:5])
    return max(FLOOR, min(DECKEL, round(100 - strafe)))


def target(score: int | None, findings: list[dict], massnahmen: list[dict]) -> int | None:
    """Der Stand, wenn alles umgesetzt ist, wofuer eine Massnahme existiert.

    **Das ist wortwoertlich gemeint, und der Wert liegt deshalb oft nahe am
    Deckel.** Bis zum 07.09.2026 war der Sprung auf 24 Punkte begrenzt, weil
    ein Ziel, das ueberall gleich aussieht, nichts aussagt. Das war der falsche
    Schluss aus einer richtigen Beobachtung: die Aussage steckt nicht in der
    Hoehe des Ziels, sondern im **Abstand**. Messung 38 auf 89 ist ein Sprung
    von 51 Punkten, Bezahlte Suche 86 auf 92 einer von sechs. Genau das soll
    der Leser sehen. Yves dazu: *"Wieso nur 53? Warum kann man nicht 100
    schaffen?"*

    Was bleibt, sind die Befunde ohne Massnahme: Beobachtungen, Luecken in der
    Datenlage, Dinge ausserhalb des eigenen Zugriffs. Die verschwinden nicht
    dadurch, dass jemand arbeitet, und deshalb ist das Ziel selten der Deckel.
    """
    if score is None:
        return None
    mit_massnahme = {m.get("finding_ref") for m in massnahmen
                     if m.get("finding_ref")}
    remainder = [f for f in findings if f.get("id") not in mit_massnahme]
    return max(score, section_score(remainder))


def compute(findings_by_section: dict, massnahmen: list[dict],
            ohne_daten: set = frozenset()) -> dict:
    """Scores je Sektion, je Bereich und gesamt, plus die Ziele.

    `findings_by_section` bildet Sektionsschluessel auf die Befundliste ab, jeder
    Befund mit `_schwere` und `confidence`. `ohne_daten` sind Sektionen, deren
    Quelle in diesem Lauf nichts geliefert hat: sie bekommen `None`.
    """
    sections_out, goals = {}, {}
    for bereich in AREAS.values():
        for key in bereich["sektionen"]:
            if key in ohne_daten:
                sections_out[key], goals[key] = None, None
                continue
            findings = findings_by_section.get(key)
            if findings is None:
                continue
            sections_out[key] = section_score(findings)
            goals[key] = target(sections_out[key], findings, massnahmen)

    bereiche, bereich_ziele = {}, {}
    for name, b in AREAS.items():
        values = [sections_out[k] for k in b["sektionen"]
                 if sections_out.get(k) is not None]
        zw = [goals[k] for k in b["sektionen"] if goals.get(k) is not None]
        bereiche[name] = round(sum(values) / len(values)) if values else None
        bereich_ziele[name] = round(sum(zw) / len(zw)) if zw else None

    return {"sektionen": sections_out, "sektion_ziele": goals,
            "bereiche": bereiche, "bereich_ziele": bereich_ziele,
            "gesamt": _weighted(bereiche), "gesamt_ziel": _weighted(bereich_ziele)}


def _weighted(values: dict) -> int | None:
    """Gewichteter Gesamtwert. Das Gewicht ausgefallener Bereiche wird auf die
    uebrigen verteilt, sonst faellt der Gesamtscore allein dadurch, dass etwas
    nicht messbar war."""
    gewertet = [(k, v) for k, v in values.items() if v is not None]
    if not gewertet:
        return None
    total = sum(AREAS[k]["gewicht"] for k, _ in gewertet)
    return round(sum(AREAS[k]["gewicht"] / total * v for k, v in gewertet))
