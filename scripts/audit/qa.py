#!/usr/bin/env python3
"""Die Abnahme eines Audit-Laufs, maschinell geprüft.

**Warum das ein Script ist und keine Prüfliste in Prosa.** Das audit-light hat
ein Beleg-Gate und eine Übergabe-Checkliste, und beide haben dort Fehler
gefangen, bevor ein Kunde sie gesehen hat. Der grosse Audit hatte bis zum
08.09.2026 keins von beidem. Was er hatte, waren Regeln in der Skill, und die
gelten nur so weit, wie eine Sitzung sie liest. Am 07.09.2026 ist genau
deshalb ein Befund aus einem Parser-Fehler zur Schlagzeile geworden, obwohl
drei Regeln in der Skill ihn verboten haben.

Geprueft wird, was sich ohne Urteil pruefen laesst: Schema, Vollstaendigkeit,
Verweise, Vokabular, Datenlage. Was Urteil braucht, bleibt beim Menschen, und
die Ausgabe sagt, was das ist.

CLI:
    python3 -m audit.qa --workspace . --run-id 2026-10-01-audit [--phase 2|4]

Rueckgabewert 0 heisst sauber, 1 heisst mindestens ein Befund der Stufe
`fehler`. Warnungen allein brechen nichts ab: sie sind eine Bitte hinzusehen.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from audit import context
from audit import report_build as rb

#: Felder, die ein Befund im erweiterten Schema tragen muss.
REQUIRED = ("id", "statement", "evidence", "severity", "confidence", "effort")

#: Felder, die ihn beauftragbar machen. Fehlen sie, ist das eine Warnung:
#: ein reiner Beobachtungs-Befund braucht kein `fix`.
DESIRED = ("metrics", "why", "fix")

#: Unsere Pipeline-Interna, die in keinem Feld stehen duerfen, das der Kunde
#: liest. `evidence` ist ausgenommen, dort gehoeren sie hin.
#:
#: **"Crawler" stand hier bis zum 09.09.2026 und ist raus.** Das ist ein
#: Fachbegriff, den jeder E-Commerce-Verantwortliche kennt, und das Verbot hat
#: die Analysen auf Laienwoerter ausweichen lassen. Verboten ist, was unsere
#: Werkzeugkette betrifft, nicht was die Sache benennt.
TOOL_WORDS = re.compile(
    r"\b(?:\w+\.json|ShopifyQL|GraphQL|DataForSEO|Pull|Snapshot|"
    r"jq|API-Fehler|Column Not Found|run-id|state\.json)\b", re.I)

#: Laienwoerter: Umschreibungen, wo ein Fachbegriff oder eine Zahl hingehoert.
#: Jedes davon ist einmal in einem fertigen Report gestanden.
#:
#: **Warum das ein Fehler ist und keine Stilfrage.** Am 08.09.2026 stand
#: "Auf allen geprueften Seiten laeuft ein Werkzeug fuer Preis- und
#: Angebotstests", waehrend der Produktname (Intelligems) in der Tabelle
#: darunter stand. Yves dazu: *"Das ist wirklich einfach knallhart nicht
#: nutzbar."* Der Leser ist Geschaeftsfuehrer, kein Laie: er kennt seine Tools,
#: und er merkt, wenn jemand um einen Begriff herumredet. Das Vokabular steht
#: in der Skill `ptai-ecom:ecom-language`.
LAY_WORDS = (
    (re.compile(r"\b(?:Test)?[Ww]erkzeuge?[ns]?\b"),
     "den Produktnamen nennen oder die Kategorie (A/B-Testing-Tool, "
     "E-Mail-Marketing-Tool)"),
    (re.compile(r"\b(?:echte[nrs]? )?Menschen\b"),
     "Sessions, Unique Visitors oder Nutzer, je nachdem was gezaehlt wurde"),
    (re.compile(r"\bTrichter\b"), "Funnel"),
    (re.compile(r"\bSkripte fremder Anbieter\b"),
     "Drittanbieter-Dienste oder Third-Party-Scripts"),
    (re.compile(r"\bSuchmaschinen-Vorschautext\b"), "Meta-Description"),
)

#: Mengenangaben ohne Zahl. Kontextabhaengig richtig, deshalb Warnung statt
#: Fehler: "mehrere Wettbewerber" kann stimmen, "mehrere Skripte fehlen" nicht,
#: wenn die Zahl eine Zeile tiefer in der Tabelle steht.
VAGUE_QUANTITIES = re.compile(
    r"\b(?:mehrere|einige|zahlreiche|viele|etliche|diverse|"
    r"praktisch alle|fast alle|ein Grossteil)\b", re.I)

#: ae/oe/ue statt echter Umlaute. Der haeufigste Rueckfall der Analysen.
ASCII_UMLAUTS = re.compile(
    r"\b(?:fuer|ueber|koennen|muessen|waehrend|zuruecke?|"
    r"moeglich|naechste|hoehe|groesse|laeuft|faellt|haelt|"
    r"gruende?|pruefen|erhoeht|verfuegbar|zusaetzlich|"
    r"ausserdem|massnahme|schliesse|gemaess)\w*", re.I)


class Finding:
    def __init__(self, stufe: str, wo: str, text: str):
        self.stufe, self.wo, self.text = stufe, wo, text

    def __str__(self):
        return f"[{self.stufe:8s}] {self.wo}: {self.text}"


def _text_felder(f: dict) -> str:
    """Alles, was der Kunde von einem Befund liest. Ohne `evidence`."""
    parts = [str(f.get(k) or "") for k in ("statement", "effect", "why", "fix")]
    for m in f.get("metrics") or []:
        parts += [str(m.get(k) or "") for k in ("label", "value", "context")]
    return " ".join(parts)


def check_findings(run: rb.Run) -> list[Finding]:
    """Schema, Vokabular und Umlaute in allen Befund-Dateien."""
    out = []
    if not run.findings:
        return [Finding("fehler", "Befunde", "Keine einzige Befund-Datei "
                                            "gefunden. Phase 2 lief nicht.")]
    for filename, doc in sorted(run.findings.items()):
        findings = doc.get("findings") or []
        if not findings:
            out.append(Finding("warnung", filename, "keine Befunde in dieser Datei"))
        for i, f in enumerate(findings, 1):
            identifier = f.get("id") or f"#{i}"
            wo = f"{filename} {identifier}"
            fehlt = [k for k in REQUIRED if not f.get(k)]
            if fehlt:
                out.append(Finding("fehler", wo,
                                  f"Pflichtfelder fehlen: {', '.join(fehlt)}"))
            empty = [k for k in DESIRED if not f.get(k)]
            if empty:
                out.append(Finding("warnung", wo,
                                  f"ohne {', '.join(empty)}. Ein Befund ohne "
                                  "diese Felder ist eine Beobachtung, keine "
                                  "Grundlage für eine Maßnahme"))
            if f.get("severity") and f["severity"] not in ("hoch", "mittel", "gering"):
                out.append(Finding("fehler", wo,
                                  f"severity {f['severity']!r} ist keine der "
                                  "drei Stufen hoch, mittel, gering"))
            if len(str(f.get("statement") or "")) > 200:
                out.append(Finding("warnung", wo,
                                  f"statement ist {len(f['statement'])} Zeichen "
                                  "lang. Die Regel sagt ein Satz, höchstens 90"))
            text = _text_felder(f)
            treffer = set(ASCII_UMLAUTS.findall(text))
            if treffer:
                out.append(Finding("fehler", wo,
                                  "Ersatzumlaute statt ä, ö, ü: "
                                  + ", ".join(sorted(treffer)[:5])))
            tool_label = set(TOOL_WORDS.findall(text))
            if tool_label:
                out.append(Finding("warnung", wo,
                                  "Werkzeugsprache in einem Feld, das der Kunde "
                                  "liest: " + ", ".join(sorted(tool_label)[:4])
                                  + ". Das gehört in evidence"))
            for muster, statt in LAY_WORDS:
                treffer = muster.search(text)
                if treffer:
                    out.append(Finding("fehler", wo,
                                       f"Laienwort {treffer.group(0)!r}. "
                                       f"Dort gehört hin: {statt}. "
                                       "Vokabular: ptai-ecom:ecom-language"))
            vage = VAGUE_QUANTITIES.search(text)
            if vage:
                out.append(Finding("warnung", wo,
                                   f"Mengenangabe {vage.group(0)!r} ohne Zahl. "
                                   "Steht die Zahl in metrics, gehört sie auch "
                                   "in den Satz"))
    return out


def check_measures(run: rb.Run) -> list[Finding]:
    """Jede Massnahme muss auf einen Befund zeigen, den es gibt."""
    out = []
    idx = rb.finding_index(run)
    massnahmen = run.backlog.get("measures") or []
    if not massnahmen:
        return [Finding("warnung", "Maßnahmen", "der Backlog ist leer")]
    for m in massnahmen:
        wo = f"Maßnahme {m.get('id')}"
        ref = m.get("finding_ref")
        if ref and ref not in idx:
            out.append(Finding("fehler", wo,
                              f"verweist auf Befund {ref}, den es nicht gibt"))
        if not m.get("check_rule"):
            out.append(Finding("fehler", wo, "ohne Prüfregel. Eine Maßnahme, "
                                            "deren Umsetzung sich nie "
                                            "feststellen lässt, bleibt für "
                                            "immer offen"))
        text = f"{m.get('title','')} {m.get('check_rule','')} {m.get('data_source','')}"
        if TOOL_WORDS.search(text):
            out.append(Finding("warnung", wo, "Werkzeugsprache im Titel, in der "
                                             "Prüfregel oder im Ort der Arbeit"))
        if ASCII_UMLAUTS.search(text):
            out.append(Finding("fehler", wo, "Ersatzumlaute statt ä, ö, ü"))
    return out


def check_source_status(run: rb.Run) -> list[Finding]:
    """Was der Crawl ueber sich selbst meldet, und was fehlt."""
    out = []
    crawl = run.snap("crawl.json") or {}
    s = crawl.get("summary") or {}
    for note in s.get("self_check") or []:
        out.append(Finding("fehler", "Crawl", note))
    gesamt = s.get("url_count") or 0
    fehlend = s.get("throttled_pages") or 0
    if fehlend:
        out.append(Finding("warnung", "Crawl",
                          f"{fehlend} von {gesamt} Seiten blieben gedrosselt "
                          "und fehlen. Jeder Anteil aus dem Crawl bezieht sich "
                          "auf die übrigen"))
    abgewiesen = s.get("bot_challenge_pages") or 0
    if abgewiesen:
        out.append(Finding("warnung", "Crawl",
                          f"{abgewiesen} von {gesamt} Seiten hat die "
                          "Bot-Erkennung des Shops abgewiesen und fehlen. Das "
                          "ist keine Drosselung: erst eine Ausnahme in der WAF "
                          "macht diesen Teil des Shops messbar"))
    ga4 = run.snap("ga4.json") or {}
    prop = ga4.get("property") or {}
    if prop.get("note"):
        out.append(Finding("warnung", "Analytics",
                          "Die Mess-IDs der Property sind unbekannt, ein "
                          "Abgleich mit dem Quelltext ist nicht möglich"))
    elif prop.get("measurement_ids"):
        crawl_ids = {k for k in ((crawl.get("findings_index") or {})
                                 .get("inline_tag_ids") or {}) if k.startswith("G-")}
        eigene = set(prop["measurement_ids"])
        fremd = crawl_ids - eigene
        if fremd:
            out.append(Finding("fehler", "Analytics",
                              f"Der Shop lädt {', '.join(sorted(fremd))}, was "
                              "nicht zur gezogenen Property gehört. Ein Teil "
                              "der Bestellungen kann woanders ankommen"))
    return out


def check_document(run: rb.Run) -> list[Finding]:
    """Das fertige HTML: Platzhalter, Vokabular, Lesbarkeit."""
    from audit import readability
    out = []
    pfad = run.run / "audit.html"
    if not pfad.exists():
        return [Finding("fehler", "Dokument", "audit.html gibt es nicht")]
    html = pfad.read_text(encoding="utf-8")
    offen = sorted(set(re.findall(r"__[A-Z_]{3,}__", html)))
    if offen:
        out.append(Finding("fehler", "Dokument",
                          "Platzhalter im fertigen Dokument: " + ", ".join(offen)))
    fliess = readability.text_aus_html(html)
    for m in readability.check(fliess):
        out.append(Finding("warnung", "Lesbarkeit", m))
    if ASCII_UMLAUTS.search(fliess):
        out.append(Finding("fehler", "Dokument",
                          "Ersatzumlaute im Fließtext: "
                          + ", ".join(sorted(set(ASCII_UMLAUTS.findall(fliess)))[:5])))
    return out


#: Was ein Mensch entscheiden muss, weil es Urteil braucht. Wird immer
#: ausgegeben, nie geprueft.
FOR_HUMANS = (
    "Jede Zahl auf Seite eins gegen die Wirklichkeit halten, nicht nur gegen "
    "das Quellfeld. Ein Abruf der Seite reicht meist.",
    "Trägt jeder Befund in Einstieg, Erkenntnissen und Problem-Kacheln seine "
    "Kennung, und stimmt sie?",
    "Steht in jedem Kapitel auch, was gut ist, oder nur, was fehlt?",
    "Würdest du jeden Satz laut sagen, wenn du dem Kunden den Report über den "
    "Tisch schiebst?",
    "Passt alles ins A4-Layout, nichts abgeschnitten, keine Tabelle über den "
    "Seitenrand?",
)


#: Woerter, die in jedem zweiten Satz stehen und deshalb nichts belegen.
_STOPP = frozenset("""
der die das den dem des ein eine einer eines einem einen und oder aber
nicht kein keine ist sind war waren wird werden wurde wurden hat haben
sich auch nur noch schon mehr sehr aller alle allen als bei von zu im in
an auf aus fuer mit nach ueber unter vor durch gegen ohne um dass wenn
weil damit sodass sondern dann dort hier man es sie er wir ihr ihre
""".split())


def _shorten_text(text: str, n: int) -> str:
    """Kuerzt an einer Wortgrenze, damit die Meldung eine Zeile bleibt."""
    text = " ".join(str(text).split())
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0] + " ..."


def _covers(text: str, aussage: str) -> bool:
    """Kommt die Sache des Kundenwissens im Befund vor?

    Gemessen an den bedeutungstragenden Woertern der Kundenaussage: mindestens
    die Haelfte davon, wenigstens zwei, muessen im Befund stehen. Das ist grob
    und soll es sein. Die Pruefung entscheidet nicht, ob die Einengung richtig
    ist, sie unterscheidet nur "hat es beruecksichtigt" von "hat es
    uebergangen", und im Zweifel darf sie durchlassen: sie ist eine Warnung,
    kein Tor.
    """
    if not aussage:
        return False
    ziel = {w for w in re.findall(r"[a-zA-ZäöüÄÖÜß]{4,}", aussage.lower())
            if w not in _STOPP}
    if len(ziel) < 2:
        return False
    vorhanden = {w for w in re.findall(r"[a-zA-ZäöüÄÖÜß]{4,}", text.lower())}
    treffer = ziel & vorhanden
    return len(treffer) >= max(2, len(ziel) // 2)


def check_customer_context(run: rb.Run, workspace: Path) -> list[Finding]:
    """Prueft, ob die Analysen das beruecksichtigt haben, was der Kunde zu
    frueheren Befunden gesagt hat.

    Das ist die einzige Stelle, an der auffaellt, dass eine Kundenaussage ins
    Leere lief. Ein Subagent, der `reporting/context.json` im Prompt hatte und
    den Befund trotzdem unveraendert wieder stellt, hat die Regel ignoriert,
    und ohne diese Pruefung merkt das niemand ausser dem Kunden selbst, im
    naechsten Termin.

    Die Pruefung urteilt nicht darueber, **ob** die Einengung richtig ist. Sie
    stellt nur fest, dass der Befund unveraendert wiederkommt, und bittet um
    einen Blick. Deshalb Warnung, nicht Fehler: es gibt den legitimen Fall,
    dass die Zahlen der Kundenaussage widersprechen, und dann gehoert der
    Befund stehen zu bleiben, nur mit dem Widerspruch darin.
    """
    out = []
    try:
        entries = context.load(str(workspace))
    except ValueError as exc:
        return [Finding("fehler", "Kundenwissen", str(exc))]
    if not entries:
        return out
    for errors in context.validate(entries):
        out.append(Finding("fehler", "Kundenwissen", errors))

    for filename, doc in sorted(run.findings.items()):
        for f in doc.get("findings") or []:
            identifier = f.get("id")
            if not identifier:
                continue
            treffer = context.for_finding(entries, identifier)
            if not treffer:
                continue
            # **Alle sechs Felder, nicht vier.** `explanation` und `benchmark`
            # kamen am 09.09.2026 dazu, und die Analysen arbeiten das
            # Kundenwissen bevorzugt dort ein, weil es dorthin gehoert: es
            # erklaert den Zustand, statt ihn zu bewerten. Wer nur die alten
            # vier durchsucht, meldet einen sauber eingeengten Befund als
            # ignoriert.
            text = " ".join(str(f.get(k) or "") for k in
                            ("statement", "explanation", "benchmark",
                             "why", "effect", "fix"))
            # Klar erkennbar eingearbeitet ist ein Eintrag, wenn seine Kennung
            # dasteht oder seine Woerter im Befund vorkommen. Die Kennung im
            # Kundendokument waere unsere Buchfuehrung, verlangt wird nur, dass
            # die Aussage angekommen ist.
            erwaehnt = any(e["id"] in text or _covers(text, e.get("statement", ""))
                           for e in treffer)
            if not erwaehnt:
                # **Diese Pruefung entscheidet nicht, sie zeigt hin.** Eine
                # Einengung muss die Worte des Kunden nicht wiederholen: auf
                # "nicht kaufbare Produkte sind meist ausverkauft" antwortet
                # "31 nie verkaufte, nicht kaufbare Produkte" vollkommen
                # richtig, ohne ein Wort davon zu nennen. Am 09.09.2026 hat die
                # Meldung deshalb bei zwei von drei Befunden falsch angeschlagen,
                # und ihr alter Wortlaut behauptete dabei etwas, das sie nicht
                # wissen kann ("der Befund steht unveraendert").
                #
                # Sie nennt jetzt die Kundenaussage im Klartext daneben. Damit
                # kostet ein Blick zwei Sekunden statt eines Umwegs ueber
                # context.json, und das Urteil bleibt, wo es hingehoert.
                for e in treffer:
                    out.append(Finding(
                        "warnung", f"{filename} {identifier}",
                        f"Kundenwissen {e['id']} betrifft diesen Befund: "
                        f"\u201e{_shorten_text(e.get('statement', ''), 90)}\u201c "
                        "Pruefen, ob er es beruecksichtigt: einengen, den "
                        "Widerspruch hineinschreiben, oder so lassen"))
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", default=".")
    p.add_argument("--run-id", required=True)
    p.add_argument("--phase", choices=("2", "4"), default="4",
                   help="2 prüft Befunde und Datenlage, 4 zusätzlich Maßnahmen "
                        "und das fertige Dokument")
    a = p.parse_args(argv)

    run = rb.Run(Path(a.workspace).resolve(), a.run_id)
    if not run.state:
        raise SystemExit(f"Kein Lauf {a.run_id} unter {a.workspace}")

    findings = (check_findings(run) + check_source_status(run)
               + check_customer_context(run, Path(a.workspace).resolve()))
    if a.phase == "4":
        findings += check_measures(run) + check_document(run)

    errors = [b for b in findings if b.stufe == "fehler"]
    warnungen = [b for b in findings if b.stufe == "warnung"]
    for b in errors + warnungen:
        print(b)
    print(f"\n{len(errors)} Fehler, {len(warnungen)} Warnungen.")
    print("\nWas ein Mensch prüfen muss, weil es Urteil braucht:")
    for row in FOR_HUMANS:
        print(f"  [ ] {row}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
