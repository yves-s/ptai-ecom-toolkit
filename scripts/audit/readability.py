#!/usr/bin/env python3
"""Lesbarkeit des Fliesstexts messen, in drei etablierten deutschen Massen.

**Was diese Datei kann und was nicht.** Lesbarkeitsformeln messen Wort- und
Satzlaenge, sonst nichts. Sie korrelieren mit Verstaendlichkeit, sie messen
sie nicht (Bailin und Grafstein, Language & Communication 2001: reine
statistische Korrelate ohne Lesetheorie, blind fuer Wortschatz, Kohaerenz und
Vorwissen). Ein Text laesst sich formelkonform machen, indem man Saetze
mechanisch zerhackt, ohne dass ein Leser mehr versteht.

Der Nutzen liegt deshalb woanders: **als Regressionstest gegen
Verschlechterung.** Wenn der Einstieg eines Laufs deutlich schwerer liest als
der des letzten, ist das ein Signal. Ein guter Wert ist kein Qualitaetsnachweis.

Gemessen wird ausschliesslich Fliesstext. Tabellen, Ueberschriften und
Diagramm-Beschriftungen haben andere Satzlaengen, und wer sie mitmisst, misst
Rauschen.

Die Formeln:

* **Wiener Sachtextformel 1** (Bamberger und Vanecek 1984), Ergebnis ist eine
  Schulstufe von 4 (sehr leicht) bis 15 (sehr schwer).
* **LIX** (Bjoernsson 1968), mittlere Satzlaenge plus Anteil langer Woerter.
  Unter 40 Kinderbuch, 40 bis 50 Belletristik, 50 bis 60 Sachliteratur,
  ueber 60 Fachliteratur.
* **Flesch-Reading-Ease, deutsche Adaption** (Amstad 1978), 0 bis 100,
  hoch ist leicht.

Die Zielbaender unten sind **abgeleitet, nicht gemessen**: einen validierten
Zielwert fuer "Fachdokument an eine Geschaeftsfuehrung ohne Fachsprache" gibt
es im Deutschen nicht. Validiert sind nur die Werte fuer Leichte und Einfache
Sprache, und die sind fuer diesen Zweck zu niedrig.
"""
from __future__ import annotations

import re
import unicodedata

VOWELS = "aeiouyäöüáàâéèêíìîóòôúùû"

#: Zielbaender je Textsorte. Abgeleitet aus den Gattungsankern der Formeln,
#: nicht gemessen. Der Einstieg soll leichter lesen als eine Fachsektion.
BANDS = {
    "einstieg": {"wstf": (7.0, 11.0), "lix": (38, 50)},
    "fliesstext": {"wstf": (8.0, 12.5), "lix": (42, 58)},
}


def _syllables(wort: str) -> int:
    """Silben naeherungsweise ueber Vokalgruppen.

    Kein Woerterbuch: der Fehler liegt bei deutschen Texten im niedrigen
    einstelligen Prozentbereich und wirkt auf alle Laeufe gleich, und darum
    geht es bei einem Regressionstest.
    """
    w = unicodedata.normalize("NFC", wort.lower())
    gruppen = re.findall(f"[{VOWELS}]+", w)
    return max(1, len(gruppen))


def metrics(text: str) -> dict | None:
    """Die drei Masse plus die Rohgroessen. `None`, wenn zu wenig Text da ist."""
    saetze = [t for t in re.split(r"[.!?]+(?:\s|$)", text) if t.strip()]
    woerter = re.findall(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß-]*", text)
    if len(woerter) < 30 or not saetze:
        return None
    n = len(woerter)
    silben = [_syllables(w) for w in woerter]
    asl = n / len(saetze)
    asw = sum(silben) / n
    ms = 100 * sum(1 for x in silben if x >= 3) / n
    iw = 100 * sum(1 for w in woerter if len(w) > 6) / n
    es = 100 * sum(1 for x in silben if x == 1) / n
    return {
        "woerter": n, "saetze": len(saetze),
        "satzlaenge": round(asl, 1),
        "wstf": round(0.1935 * ms + 0.1672 * asl + 0.1297 * iw - 0.0327 * es - 0.875, 1),
        "lix": round(asl + iw, 1),
        "flesch": round(180 - asl - 58.5 * asw, 1),
    }


def check(text: str, sorte: str = "fliesstext") -> list[str]:
    """Meldungen, wo der Text aus seinem Band faellt. Leer heisst unauffaellig."""
    k = metrics(text)
    if not k:
        return []
    band, meldungen = BANDS.get(sorte, BANDS["fliesstext"]), []
    lo, hi = band["wstf"]
    if k["wstf"] > hi:
        meldungen.append(
            f"Wiener Sachtextformel {k['wstf']} (Ziel bis {hi}): der Text liest "
            f"sich schwerer als vorgesehen, mittlere Satzlänge "
            f"{k['satzlaenge']} Wörter")
    lo, hi = band["lix"]
    if k["lix"] > hi:
        meldungen.append(
            f"LIX {k['lix']} (Ziel bis {hi}): viele lange Wörter oder lange "
            "Sätze. Ab 60 gilt ein Text als Fachliteratur")
    if k["satzlaenge"] > 22:
        meldungen.append(
            f"Mittlere Satzlänge {k['satzlaenge']} Wörter. AR 25-50 nennt "
            "etwa 15 als Richtwert für Text, der beim ersten Lesen sitzt")
    return meldungen


def text_aus_html(html_text: str) -> str:
    """Nur den Fliesstext aus dem Dokument, ohne Tabellen und Ueberschriften."""
    ohne = re.sub(r"<(script|style|table|figure)[^>]*>.*?</\1>", " ",
                  html_text, flags=re.S | re.I)
    ohne = re.sub(r"<h[1-6][^>]*>.*?</h[1-6]>", " ", ohne, flags=re.S | re.I)
    ohne = re.sub(r'<p class="(eyebrow|evidence|meta|label|caption|value)[^"]*">'
                  r".*?</p>", " ", ohne, flags=re.S | re.I)
    ohne = re.sub(r"<!--.*?-->", " ", ohne, flags=re.S)
    return " ".join(re.sub(r"<[^>]+>", " ", ohne).split())
