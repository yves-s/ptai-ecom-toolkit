#!/usr/bin/env python3
"""Das Audit-PDF aus den Snapshots bauen.

Bis zum 07.09.2026 hat Phase 4 dieses Dokument von Hand zusammengesetzt: die
Skill beschrieb in Prosa, welcher Platzhalter aus welchem Quellfeld kommt, und
jede Sitzung baute es neu. Das Ergebnis war jedes Mal ein anderes, und jeder
Fix an der Darstellung lebte nur in der Sitzung, die ihn gemacht hat.

Was hier drin steht, ist alles, was aus Daten folgt: die Zahlen je Sektion, die
Befunde, die Massnahmen, die Quellen. Was die Sitzung schreibt, sind die sechs
Textelemente in `report-text.json` (Cover-Headline, Einstieg, die fuenf Zeilen
der Zusammenfassung, die Erkenntnisse, der naechste Schritt). Diese Trennung ist
Absicht: Zahlen gehoeren in Code, damit sie nicht driften, und Text gehoert an
einen Menschen, damit er nicht generisch wird.

CLI:
    python3 -m audit.report_build --workspace . --run-id 2026-10-01-audit \\
        --text reporting/runs/<run-id>/report-text.json

Ohne `--text` schreibt das Script eine Vorlage an diesen Ort und bricht ab: die
Sitzung fuellt sie und ruft erneut auf.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

from audit import charts, gates
from audit import closing
from audit import ga4_variants
from audit import readability
from audit import measures as measures_mod
from audit import score as score_mod
from audit import window as window_mod

# ---------------------------------------------------------------- Konstanten

#: Kuerzel je Befund-Datei, verbindlich. Es steht in den Agent-Definitionen
#: genauso, aber ein Agent, der sich eigene Kuerzel ausdenkt, bricht jede
#: Verknuepfung zwischen Massnahme und Befund. Am 07.09.2026 hat der
#: Datenqualitaets-Agent "DQ-01" geschrieben, wo "MES-01" stand. Der Builder
#: normalisiert deshalb, statt zu vertrauen: die Nummer bleibt, das Kuerzel
#: kommt von hier.
PREFIXES = {"data-quality": "MES", "commerce": "HDL", "traffic": "TRF",
           "conversion": "CRO", "seo-technical": "TEC", "seo-content": "SEO",
           "geo": "GEO", "competition": "WBW", "content-brand": "CNT",
           "sea": "SEA", "trust": "TRS"}

#: Wie eine Quelle im Kundendokument heisst. Der Leser hat Fragen zu seinem
#: Shop, keine zu unseren Schluesseln: "dfs_keywords" ist kein Werkzeug, und
#: "shop_tech" steht auf keiner Rechnung. Am 07.09.2026 stand die rohe
#: Schluesselliste in der Quellen-Tabelle des ersten echten Reports.
TOOL = {
    "shopify": "Shopify Admin", "catalogue": "Shopify Katalog",
    "shop_tech": "Shopify Theme und Apps", "ga4": "Google Analytics",
    "gsc": "Google Search Console", "cwv": "Chrome-Nutzungsdaten (CrUX)",
    "cwv_lab": "PageSpeed-Messung", "crawl": "Eigener Durchgang durch den Shop",
    "screens": "Bildschirmaufnahmen", "geo": "AI-Systeme",
    "ads": "Google Ads", "shopping": "Google Shopping",
    "dfs_rankings": "Ranking-Bestand (DataForSEO)",
    "dfs_keywords": "Suchvolumen (DataForSEO)",
    "competitors": "Wettbewerber-Abgleich (DataForSEO)",
    "backlinks": "Linkprofil (DataForSEO)",
    "esp": "E-Mail-Versand", "meta": "Meta Ads", "reviews": "Bewertungen",
    "measures": "Maßnahmen-Backlog",
}


#: Die offiziellen deutschen GA4-Channelgruppen. Der Kunde sieht genau diese
#: Woerter in seinem eigenen Bericht.
CHANNEL = {"Direct": "Direkt", "Organic Search": "Organische Suche",
         "Paid Search": "Bezahlte Suche", "Organic Social": "Organisches Social",
         "Paid Social": "Bezahltes Social", "Referral": "Verweis",
         "Email": "E-Mail", "Display": "Display", "Affiliates": "Affiliates",
         "Organic Shopping": "Organisches Shopping",
         "Paid Shopping": "Bezahltes Shopping", "Unassigned": "Nicht zugeordnet",
         "Organic Video": "Organisches Video", "Cross-network": "Netzwerkübergreifend",
         "Audio": "Audio", "SMS": "SMS", "Mobile Push Notifications": "Push-Nachrichten"}

#: GA4 liefert die Geraetekategorie in englischen Kleinbuchstaben.
DEVICE = {"mobile": "Smartphone", "desktop": "Desktop", "tablet": "Tablet",
          "smart tv": "Smart-TV", "(other)": "Nicht zugeordnet"}

#: Wie eine AI-Plattform im Kundendokument heisst.
PLATFORM = {"chatgpt": "ChatGPT", "perplexity": "Perplexity",
             "google-ai": "Google AI (Gemini)", "claude": "Claude"}


def _short_reason(evidence: str) -> str:
    """Aus der Belegzeile einer ausgefallenen Abfrage einen lesbaren Grund.

    Die Rohzeile traegt den API-Wortlaut ("Your project has been denied
    access"), und der gehoert nicht ins Kundendokument.
    """
    t = str(evidence or "").lower()
    if "denied access" in t or "permission" in t or "403" in t:
        return "kein Zugang zur Schnittstelle"
    if "quota" in t or "rate" in t or "429" in t:
        return "Abfragegrenze der Schnittstelle erreicht"
    if "timeout" in t or "timed out" in t:
        return "Schnittstelle hat nicht geantwortet"
    return "Abfrage fehlgeschlagen"


def source_label(key: str, run=None) -> str:
    """Wie eine Quelle im Kundendokument heisst.

    Fuer die GEO-Quelle stehen die Systeme dahinter, die tatsaechlich gefragt
    wurden, nicht eine Umschreibung: "AI-Systeme (ChatGPT, Perplexity)" sagt
    einem Leser, was gemessen wurde, "AI-Antwortsysteme" ist ein gebautes Wort.
    Die Liste kommt aus dem Snapshot, nicht aus einer Konstanten, damit sie
    nicht behauptet, was in diesem Lauf gar nicht lief.
    """
    name = TOOL.get(key, key.replace("_", " "))
    if key == "geo" and run is not None:
        geo = run.snap("geo.json") or {}
        systeme = sorted({PLATFORM.get(q.get("platform"), q.get("platform"))
                          for q in (geo.get("queries") or [])
                          if q.get("platform")})
        if systeme:
            return f"{name} ({', '.join(systeme)})"
    return name


#: Welche Befund-Datei in welche Sektion gehoert.
SECTION_BY_FILE = {"data-quality": "measurement", "commerce": "commerce",
                     "traffic": "traffic", "conversion": "conversion",
                     "seo-content": "seo", "geo": "geo",
                     "seo-technical": "tech", "content-brand": "catalogue",
                     "trust": "trust",
                     "competition": "competition", "sea": "sea"}

#: Die Textelemente, die eine Sitzung schreibt. Jedes hat einen Platzhalter im
#: Template; ohne sie rendert das Dokument nicht.
TEXT_FIELDS = ("cover_headline", "intro", "summary_what", "summary_why",
              "summary_status", "summary_problem", "summary_possible",
              "takeaways", "next_step")

#: Die drei groessten Probleme als Zahl, nicht als Satz. Eigene Liste, weil
#: sie eine andere Form hat als die Textfelder: je Eintrag Zahl, Label und
#: eine Zeile Erklaerung plus die Kennung des Befunds dahinter.
PROBLEM_FIELD = "problems"

#: Je Sektion ein Satz, der sagt, was dieser Abschnitt gefunden hat. Die
#: Ueberschrift bleibt fest ("3 · Handel"), weil sie Navigation ist und der
#: Vokabular-Regel unterliegt. Darunter steht die Aussage.
#:
#: **Der Grund ist IBCS SA 3.2, "say message first", und ein Vergleich mit
#: einem eigenen Report, der funktioniert.** Im audit-light heisst eine Seite
#: "Den Preis traegt der Absender, nicht das Leder" und darunter steht die
#: Herleitung. Hier hiess sie bis zum 07.09.2026 nur "3 · Handel", also
#: Inhaltsverzeichnis statt Aussage. Yves dazu: *"Wieso schaffen wir es da auf
#: den ersten Seiten so eine gute und spannende Darstellung und hier nur so
#: eine trockene Kacke?"*
KEY_MESSAGE = "section_messages"

#: Diese Abschnitte erzeugt das Script vollstaendig selbst, sie brauchen keine
#: Kernaussage der Sitzung: sie beschreiben keinen Befund am Shop, sondern die
#: Datenlage, die Rechenweise und die Herkunft der Zahlen.
WITHOUT_KEY_MESSAGE = ("gaps", "method", "sources")

NBSP = " "
# Ein Währungscode wie USD ist eine Einheit wie das Euro-Zeichen, siehe
# currency_suffix.
NUMBER_RE = re.compile(r"^[<>~+-]?\s*[\d.,]+\s*(€|%|ms|x|Seiten|Punkte|[A-Z]{3})?$")
PLACEHOLDER = {"nicht erhoben", "ja", "nein", "keine", "keiner", "nicht messbar",
               "unverändert", "nicht möglich", "zu wenig Daten"}


# ------------------------------------------------------------- Formatierung

def esc(v) -> str:
    return html.escape(str(v), quote=False)


def num_de(n, dez=0, suf="") -> str:
    """Deutsche Zahl. `None` wird nie zu 0, sondern zu "nicht erhoben"."""
    if n is None:
        return "nicht erhoben"
    s = f"{n:,.{dez}f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    # Die Einheit haengt mit geschuetztem Leerzeichen an der Zahl: auf einer
    # schmalen Kachel rutscht das Euro-Zeichen sonst in die naechste Zeile.
    return s + (NBSP + suf.lstrip() if suf.startswith(" ") else suf)


def percent(n, dez=1) -> str:
    return "nicht erhoben" if n is None else num_de(n * 100, dez, " %")


def points(jetzt, vorher, dez=2) -> str:
    """Die Veraenderung einer Quote, in Prozentpunkten und mit Ausgangsniveau.

    Eine relative Angabe auf eine Quote vergroessert die wahrgenommene Wirkung
    systematisch: "Conversion -6,1 Prozent" klingt nach einem Einbruch, und
    gemeint sind 0,08 Prozentpunkte. Trevena et al. 2013 (BMC Medical
    Informatics and Decision Making) nennen genau das als vermeidbaren Fehler
    und verlangen absolute Differenz plus Ausgangsniveau. Deshalb steht hier
    nie eine relative Zahl allein.
    """
    if jetzt is None or vorher is None:
        return "kein Vergleichswert aus dem Vorjahr"
    diff = (jetzt - vorher) * 100
    richtung = "mehr" if diff >= 0 else "weniger"
    return (f"von {num_de(vorher * 100, dez)} auf {num_de(jetzt * 100, dez)} Prozent, "
            f"also {num_de(abs(diff), dez)} Prozentpunkte {richtung}")


def share(part, ganzes, dez=0) -> str:
    """"1.000 von 3.000 (33 %)".

    Beide Formen zusammen, und das ist keine Doppelung: die Haeufigkeit
    liefert die Bezugsgroesse mit, und genau die ist der belegte Wirkmechanismus
    (Trevena et al. 2013, Rosenbaum et al. 2010 zum Nutzertesting der
    Cochrane-Tabellen, wo die fehlende Bezugsklasse die Hauptfehlerquelle war).
    Der Prozentwert bleibt daneben, weil er den Vergleich zwischen Zeilen
    traegt.
    """
    if part is None or not ganzes:
        return num_de(part)
    return f"{num_de(part)} von {num_de(ganzes)} ({percent(part / ganzes, dez)})"


def delta(n, dez=1) -> str:
    """Veraenderung mit Vorzeichen. Ohne Vorzeichen liest sich ein Rueckgang
    wie ein Zuwachs."""
    if n is None:
        return "kein Vergleichswert"
    return ("+" if n >= 0 else "") + num_de(n * 100, dez, " %")


def nowrap(text) -> str:
    """Haelt zusammen, was in einer schmalen Spalte nicht getrennt werden darf.

    Zwei Faelle, beide am 07.09.2026 im PDF aufgetreten: "5 von 21" brach
    zwischen Zahl und Wort um, und ein ISO-Datum brach nach dem Monat
    ("2021-08-" / "22").
    """
    t = re.sub(r"(\d[\d.,]*) von (\d[\d.,]*)", rf"\1{NBSP}von{NBSP}\2", str(text))
    return re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b",
                  lambda m: "\u2011".join(m.groups()), t)


def _numeric_columns(header, rows) -> set:
    """Welche Spalten rechtsbuendig stehen, aus den Werten erkannt.

    Eine Angabe je Aufruf waere fehleranfaellig: eine Erklaerspalte, die
    versehentlich als Zahl markiert ist, setzt Fliesstext rechtsbuendig, und der
    Blick springt beim Lesen.
    """
    columns = set()
    for i in range(len(header)):
        values = []
        for z in rows:
            c = z[i] if i < len(z) else ""
            c = c[0] if isinstance(c, tuple) else c
            values.append(re.sub(r"<[^>]+>", "", str(c)).strip())
        gefuellt = [w for w in values if w]
        if not gefuellt:
            continue
        if all(NUMBER_RE.match(w.replace(NBSP, " ")) or w.lower() in PLACEHOLDER
               or re.match(r"^[\d.,]+ von [\d.,]+$", w.replace(NBSP, " "))
               for w in gefuellt):
            columns.add(i)
    return columns


def table(header, rows, num=None,
            empty="Für diesen Abschnitt liegen keine Zeilen vor.",
            leerspalten_ok=()) -> str:
    """Tabelle mit Kopf und Zeilen.

    Ohne Zeilen entsteht keine Tabelle, sondern der Satz aus `leer`: ein
    Tabellenkopf ohne Inhalt sieht aus wie ein Renderfehler, und der Leser
    kann nicht unterscheiden, ob nichts da ist oder etwas fehlt.
    """
    if not rows:
        return f"<p>{empty}</p>"
    _warn_on_dead_column(header, rows, leerspalten_ok)
    num = set(num) if num is not None else _numeric_columns(header, rows)
    th = "".join(f'<th{" class=\"num\"" if i in num else ""}>{esc(h)}</th>'
                 for i, h in enumerate(header))
    tr = []
    for z in rows:
        td = []
        for i, c in enumerate(z):
            cls = ""
            if isinstance(c, tuple):
                c, cls = c
            elif i in num:
                cls = "num"
            td.append(f'<td{f" class=\"{cls}\"" if cls else ""}>{nowrap(c)}</td>')
        tr.append("<tr>" + "".join(td) + "</tr>")
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(tr)}</tbody></table>"


def _warn_on_dead_column(header, rows, erlaubt=()) -> None:
    """Eine Spalte, in der jede Zelle "nicht erhoben" sagt, ist fast nie eine
    echte Luecke, sondern ein falsch gelesener Feldname.

    Am 07.09.2026 standen in der Wettbewerber-Tabelle zwei volle Spalten
    "nicht erhoben", weil der Builder `intersections` und `keywords` las,
    waehrend die Antwort `keywords_count` und `median_position` trug. Im
    fertigen PDF sah das aus wie eine fehlende Quelle. Ein Fehlgriff, der
    keinen Fehler wirft, muss wenigstens laut sein.
    """
    if len(rows) < 3:
        return
    for i, h in enumerate(header):
        if h in erlaubt:
            # In der Luecken-Tabelle ist "nicht erhoben" die Aussage der
            # Spalte, nicht ihr Ausfall.
            continue
        values = [(z[i][0] if isinstance(z[i], tuple) else z[i])
                 for z in rows if i < len(z)]
        if values and all(str(w).strip() == "nicht erhoben" for w in values):
            print(f"Warnung: Spalte {h!r} ist in allen {len(values)} Zeilen leer. "
                  "Meist ein falsch gelesener Feldname, nicht eine fehlende "
                  "Quelle.", file=sys.stderr)


def numbers_block(header, rows, zeitraum=None) -> str:
    """Die Zahlen einer Sektion, mit ihrem Zeitraum darunter.

    Der Zeitraum ist nicht optional. Eine Kennzahl ohne ihn ist keine Aussage:
    "1.200.000 Sessions" kann ein Monat oder fuenf Jahre sein.
    """
    fuss = f'<p class="evidence">Zeitraum: {esc(zeitraum)}</p>' if zeitraum else ""
    return ('<p class="eyebrow eyebrow--line">Die Zahlen</p>'
            + table(header, rows) + fuss)


def first_sentence(text, maxlen=170, hart=260):
    """Kernaussage als Kopf, Rest als Fliesstext.

    Nur noch Rueckfall: seit dem erweiterten Schema liefern die Analysen
    `statement` bereits als einen Satz. Fuer Snapshots von davor trennt das
    hier am Doppelpunkt, weil die Aussage dort fast immer davor stand.

    Ein ganzer Satz schlaegt einen kurzen. Bis `hart` wird deshalb weiter nach
    einem Satzende gesucht, auch wenn die Ueberschrift dabei laenger wird als
    `maxlen`; erst danach wird an einer Wortgrenze getrennt. Ein Kopf, der
    mitten im Satz endet ("... GA4 zaehlt 9.000" / "Transaktionen."), liest
    sich wie ein Renderfehler, und genau der stand am 07.09.2026 im PDF.
    """
    t = (text or "").strip()
    dp = t.find(": ")
    if 30 <= dp <= 130:
        return t[:dp], t[dp + 2:].strip()
    m = re.match(r"(.{25,%d}?[.!?])(\s+|$)" % hart, t, re.S)
    if m:
        return m.group(1), t[m.end():].strip()
    if len(t) <= maxlen:
        return t, ""
    schnitt = t.rfind(" ", 0, maxlen)
    schnitt = schnitt if schnitt > 40 else maxlen
    return t[:schnitt].rstrip(" ,;:"), t[schnitt:].strip()


# ------------------------------------------------------------------- Laden

class Run:
    """Alle Dateien eines Laufs, einmal gelesen."""

    def __init__(self, workspace: Path, run_id: str):
        self.ws, self.run_id = Path(workspace), run_id
        self.data = self.ws / "reporting" / "data" / run_id
        self.run = self.ws / "reporting" / "runs" / run_id
        self.config = self._j(self.ws / "reporting" / "config.json")
        self.state = self._j(self.run / "state.json")
        self.backlog = self._j(self.ws / "reporting" / "measures.json") or {"measures": []}
        self.findings = {p.stem: self._j(p)
                         for p in sorted((self.run / "findings").glob("*.json"))
                         if not p.stem.startswith("_")}
        self.fenster = None
        try:
            self.fenster = window_mod.build(self.data)
        except Exception as exc:              # noqa: BLE001
            print(f"Hinweis: kein Auswertungsfenster ({exc}). Die Kennzahlen "
                  f"tragen dann keinen Vorjahresvergleich.", file=sys.stderr)

    @staticmethod
    def _j(p: Path):
        try:
            return json.loads(Path(p).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def snap(self, name: str):
        """Ein Rohdaten-Snapshot, oder None wenn die Quelle ausgefallen ist."""
        return self._j(self.data / name)

    def quelle_ok(self, key: str) -> bool:
        return ((self.state or {}).get("sources", {}).get(key, {})
                .get("status") == "done")

    def reason(self, key: str) -> str:
        s = (self.state or {}).get("sources", {}).get(key, {})
        return s.get("reason") or "Quelle nicht erhoben"


# ------------------------------------------------------------------ Befunde

def finding_id(filename: str, raw, number: int) -> str:
    """Die Kennung eines Befunds, immer mit dem Kuerzel dieser Disziplin.

    Die laufende Nummer aus dem Agent bleibt erhalten, wenn er eine vergeben
    hat; nur das Kuerzel wird ersetzt. So bleibt "DQ-07" zu "MES-07" und nicht
    zu einer anderen Zeile.
    """
    kz = PREFIXES.get(filename, "BEF")
    m = re.search(r"(\d+)\s*$", str(raw or ""))
    return f"{kz}-{int(m.group(1)) if m else number:02d}"


#: Welche Maßnahmen der Report zeigt: die offenen und die laufenden. Eine
#: umgesetzte, verworfene oder hinfällige steht mit ihrem Status im Backlog
#: (`measures.md`, Portal), im Report nicht mehr. Der Block unter einem Befund
#: zeigt keinen Status, und am 12.09.2026 stand deshalb nach einem Neubau eine
#: beantwortete Frage weiter als offene Aufgabe unter ihrem Befund, daneben eine
#: Maßnahme, deren Annahme sich als falsch herausgestellt hatte.
SHOWN_STATUS = ("open", "in_progress")


def open_measures(backlog: dict) -> list[dict]:
    """Die Maßnahmen, die noch anstehen, in Prioritätsreihenfolge.

    Nur für die Anzeige: ein Befund ohne anstehende Maßnahme zeigt wieder
    seinen eigenen `fix`-Satz, und der Plan in Abschnitt 12 zählt nur, was
    noch zu tun ist. Der Score liest weiter den ganzen Backlog.
    """
    return [m for m in measures_mod.prioritize(backlog)
            if m.get("status", "open") in SHOWN_STATUS]


def measures_by_finding(run: Run) -> dict:
    """Welche anstehenden Massnahmen auf welchen Befund zeigen, in Prioritaetsreihenfolge."""
    idx = {}
    for m in open_measures(run.backlog):
        ref = m.get("finding_ref")
        if ref:
            idx.setdefault(ref, []).append(m)
    return idx


def finding_blocks(run: Run, filename: str) -> str:
    """Die Befunde einer Disziplin, in fester Feldreihenfolge.

    Die Bauform folgt der Vorlage aus dem IIA Audit Report Writing Toolkit:
    Titel plus Schweregrad, Zustand, Auswirkung, Empfehlung, Beleg. Immer
    dieselbe Reihenfolge, weil ein Leser sie nach dem dritten Befund kennt und
    danach nur noch die Zeile sucht, die ihn interessiert.

    **Erklaerung ja, Nacherzaehlung nein.** Bis zum 07.09.2026 stand unter jedem
    Befund der ganze Messtext, also der Rest des `statement` plus `effect`,
    beides eine Nacherzaehlung der Zahlen, die zwei Zentimeter darueber in der
    Tabelle stehen. Dagegen half die Regel "kein Fliesstext, sobald `metrics`
    da sind", und sie hat das Kind mit ausgeschuettet: seither stand ein Befund
    als nackter Titel ueber einer Tabelle, ohne dass irgendwo erklaert war, was
    die Zahl bedeutet. Yves am 08.09.2026 zu "Alle fuenf Schritte des Kaufwegs
    werden gemessen, keiner steht auf null": *"Weiss ich nicht, was ich damit
    anfangen soll."*

    Seit dem 09.09.2026 tragen zwei eigene Felder, was der GAO Yellow Book
    9.17f meint, wenn es *"extraneous detail"* verbietet und die Aussage
    trotzdem verlangt: `explanation` erklaert den Fachbegriff und die Messung,
    `benchmark` ordnet die Zahl ein. Beide sind kurz, beide stehen nie in der
    Tabelle, und beide sind optional: ein Snapshot aus der Zeit davor rendert
    unveraendert.
    """
    doc = run.findings.get(filename)
    if not doc:
        return ('<p class="eyebrow eyebrow--line">Befunde</p>'
                f'<p>Für diesen Bereich liegt keine Analyse vor: '
                f'{esc(run.reason(filename.replace("-", "_")))}</p>')
    # Die Massnahmen stehen bei ihrem Befund, nicht in einem eigenen Kapitel
    # weit hinten. Bis zum 07.09.2026 standen sie beides: der Befund sagte
    # "Was zu tun ist", und 25 Seiten spaeter stand dieselbe Handlung noch
    # einmal als Block. Yves dazu: *"Sind da dann nochmal weitere Massnahmen?"*
    # Nein, es waren dieselben.
    je_befund = measures_by_finding(run)
    brand = (run.config or {}).get("brand") or "der Shop"
    parts = ['<p class="eyebrow eyebrow--line">Befunde</p>']
    for i, f in enumerate(doc.get("findings") or [], 1):
        bid = finding_id(filename, f.get("id"), i)
        eigene = je_befund.get(bid, [])
        grad = severity_rank(dict(f, id=bid), run.backlog)
        header, remainder = first_sentence(f.get("statement"))
        metrics = f.get("metrics") or []
        tab = table(["Angabe", "Wert", "Bezug"],
                      [(esc(m.get("label", "")), esc(m.get("value", "")),
                        esc(m.get("context", ""))) for m in metrics]) if metrics else ""
        # Ohne `metrics` traegt nur der Fliesstext die Zahlen, dann bleibt er
        # stehen. Mit `metrics` ist er eine zweite Fassung derselben Zahlen.
        # `effect` steht entweder im Koerper oder unter "Was daraus folgt",
        # nie an beiden Stellen. Ohne diese Trennung erschien er bei alten
        # Snapshots zweimal wortgleich untereinander.
        warum = f.get("why") or f.get("effect") or ""
        # `explanation` ist die Erklaerung und steht immer. Fehlt sie (alte
        # Snapshots), traegt der Rest des `statement` den Text, aber nur wenn
        # keine Tabelle daneben steht: sonst waere es dieselbe Zahl zweimal.
        koerper = f.get("explanation") or ("" if metrics else remainder)
        einordnung = f.get("benchmark") or ""
        # Steht darunter eine Massnahme, sagt die, was zu tun ist, und zwar
        # vollstaendig: mit Zustaendigkeit und Pruefregel. Der `fix`-Satz waere
        # dann dieselbe Aussage in schwaecherer Form.
        wie = "" if eigene else (f.get("fix") or "")
        parts.append(
            f'<div class="finding-block finding-block--{grad}">'
            f'<p class="eyebrow">{esc(bid)} · Schweregrad {SEVERITY_LABEL[grad]}</p>'
            f"<h3>{esc(header)}</h3>"
            + (f"<p>{esc(_shorten(koerper, 460))}</p>" if koerper else "")
            + tab
            + (f'<div class="benchmark"><strong>Einordnung</strong>'
               f"{esc(_shorten(einordnung, 320))}</div>" if einordnung else "")
            + (f"<p><strong>Was daraus folgt:</strong> {esc(_shorten(warum, 400))}</p>"
               if warum else "")
            + (f"<p><strong>Was zu tun ist:</strong> {esc(_shorten(wie, 400))}</p>"
               if wie else "")
            + f'<p class="evidence">Beleg: '
              f'{esc(evidence_label(f.get("evidence")))}</p></div>'
            + "".join(_measure_block(m, brand, ref=None, workspace=run.ws) for m in eigene))
    return "".join(parts)


def finding_index(run: Run) -> dict:
    """Kennung auf Befund, damit eine Massnahme darauf verweisen kann."""
    idx = {}
    for filename, doc in run.findings.items():
        for i, f in enumerate(doc.get("findings") or [], 1):
            bid = finding_id(filename, f.get("id"), i)
            idx[bid] = dict(f, id=bid, filename=filename)
            # Auch unter der Kennung, die der Agent vergeben hat: eine
            # Massnahme, die noch auf "DQ-07" verweist, findet ihren Befund.
            if f.get("id") and f["id"] != bid:
                idx.setdefault(f["id"], idx[bid])
    return idx


# ---------------------------------------------------------------- Massnahmen

LABEL_DISCIPLINE = {"data_quality": "Messung", "commerce": "Handel",
                   "traffic": "Traffic", "cro": "Conversion",
                   "seo_technical": "Technik", "seo": "SEO", "geo": "GEO",
                   "sea": "Bezahlte Suche", "content": "Katalog und Content",
                   "tech": "Technik"}
LABEL_LEVERAGE = {"high": "hoch", "medium": "mittel", "low": "gering"}
LABEL_EFFORT = {"small": "klein", "medium": "mittel", "large": "groß"}


def _measure_block(m: dict, brand: str, ref: str | None,
                   workspace: str | Path = ".") -> str:
    """Eine Massnahme, so dass man sie beauftragen kann.

    `measures.json` traegt evidence, data_source, check_rule und responsible;
    bis zum 07.09.2026 zeigte der Report keines davon, und das sind genau die
    Felder, die eine Massnahme beauftragbar machen. Yves: *"Ich kann das doch
    jetzt nicht einfach in Auftrag geben, weil ich ja gar nicht verstehe: Wo
    wurde das gefunden?"*

    `ref` ist nur gesetzt, wenn der Block **nicht** direkt unter seinem Befund
    steht: dann braucht er die Zeile "Woraus". Steht er darunter, waere sie
    eine Wiederholung der Ueberschrift zwei Zentimeter darueber.
    """
    typ = " · Test statt Maßnahme" if m.get("type") == "test" else ""
    rows = ""
    if ref:
        rows += ('<div class="summary-row"><div class="summary-label">Woraus'
                   f'</div><div class="summary-value">{ref}</div></div>')
    for label, value in (("Wo", m.get("data_source")),
                        # Dieselbe Anzeige wie in measures.md. Der Name des
                        # Betreibers kommt aus dem Workspace dieses Laufs.
                        ("Wer", measures_mod.responsible_label(
                            m.get("responsible"), brand=brand, workspace=workspace)),
                        ("Erledigt, wenn", m.get("check_rule"))):
        if value:
            rows += ('<div class="summary-row"><div class="summary-label">'
                       f'{esc(label)}</div><div class="summary-value">'
                       f'{esc(value)}</div></div>')
    return (f'<div class="measure"><p class="eyebrow">Maßnahme {esc(m["id"])} · '
            f'Hebel {LABEL_LEVERAGE[m["leverage"]]} · '
            f'Aufwand {LABEL_EFFORT[m["effort"]]}{typ}</p>'
            f'<h3>{esc(m["title"])}</h3>'
            + (f'<div class="summary">{rows}</div>' if rows else "")
            + "</div>")


def measures_overview(run: Run, brand: str) -> str:
    """Abschnitt 12: die Reihenfolge, nicht die Massnahmen noch einmal.

    Seit dem 07.09.2026 steht jede Massnahme bei ihrem Befund, in der Sektion,
    in die sie gehoert. Dieses Kapitel ist deshalb der Plan: eine Zeile je
    Massnahme, in der Reihenfolge der Umsetzung, mit dem Abschnitt, in dem sie
    ausfuehrlich steht. Davor standen alle 73 Bloecke hier ein zweites Mal, und
    das waren 25 Seiten Wiederholung.
    """
    prio = open_measures(run.backlog)
    idx = finding_index(run)
    ohne_befund = []
    rows = []
    for nr, m in enumerate(prio, 1):
        ref = m.get("finding_ref")
        b = idx.get(ref) if ref else None
        if not b:
            ohne_befund.append(m)
            wo = "unten in diesem Abschnitt"
        else:
            sektion = SECTION_BY_FILE.get(b.get("datei"))
            number, title = SECTION_TITLES.get(sektion, (None, ""))
            wo = f"{number} · {title}" if number else ""
        rows.append((
            str(nr), m["title"],
            LABEL_LEVERAGE[m["leverage"]], LABEL_EFFORT[m["effort"]],
            f"{ref} in {wo}" if b else wo))
    out = table(["Nr.", "Maßnahme", "Hebel", "Aufwand", "Steht bei"], rows,
                  empty="Für diesen Lauf sind keine Maßnahmen entstanden.")
    tests = sum(1 for m in prio if m.get("type") == "test")
    out += (f"<p>{num_de(len(prio))} Einträge, davon {num_de(tests)} als Test statt als "
            "Maßnahme: dort ist die Ursache noch nicht belegt, und der Test "
            "klärt sie. Die Reihenfolge ist die der Umsetzung, zuerst die "
            "Messung, danach nach Hebel und Aufwand. Ausführlich steht jede "
            "Maßnahme bei dem Befund, aus dem sie folgt.</p>")
    if ohne_befund:
        out += ('<p class="eyebrow eyebrow--line">Ohne Befund am Shop</p>'
                "<p>Diese Einträge folgen aus einer Lücke in der Datenlage, "
                "nicht aus einer Messung am Shop. Sie haben deshalb keinen "
                "Abschnitt, in dem sie stehen könnten.</p>"
                + "".join(_measure_block(m, brand, ref="Lücke in der Datenlage",
                                         workspace=run.ws)
                          for m in ohne_befund))
    return out


# ------------------------------------------------------------- Kennzahlen

def _mit(note: str, test: dict) -> str:
    """Hängt den Preistest-Vorbehalt an eine Kachel-Notiz, wenn ein Test lief."""
    if not test.get("running"):
        return note
    return (f"{note}. Im Messzeitraum lief ein Preistest, der Wert ist ein "
            "Mischwert mehrerer Preisvarianten")


def key_figures(run: Run) -> dict:
    """Sechs Kacheln, drei mal zwei, jede mit ihrer Veränderung.

    Die Auswahl folgt der Umsatzgleichung (Shopify, "Ecommerce revenue
    growth"): Sitzungen mal Conversion Rate mal Bestellwert mal Kauffrequenz.
    Umsatz ist das Ergebnis, die vier Faktoren sind die Hebel. Bis zum
    07.09.2026 standen hier acht Kacheln, darunter Suchklicks (ein Kanal-Input
    eine Ebene tiefer, gehört ins SEO-Kapitel) und zwei Katalogzahlen (ein
    Bestandsfakt, kein Ergebnis).

    Der Zeitraum steht einmal über der Leiste statt in jeder Bildunterschrift.
    Die Notiz je Kachel trägt nur noch die Veränderung, und die ist Pflicht:
    eine Zahl ohne Vergleichswert ist ein Fakt, keine Aussage.
    """
    f = run.fenster
    shop, ga4 = run.snap("shopify.json"), run.snap("ga4.json")
    label = f["label"] if f else "gesamter erhobener Zeitraum"
    # Hat der GA4-Pull ein Bot-Profil erkannt, steckt es in jeder Monatszahl
    # von ga4.json. Ohne das Profil gibt es nur einen Block über den ganzen
    # Abfragezeitraum und keine Monatsreihe (ga4_view), also auch keine Zahl
    # für das Auswertungsfenster.
    bot_profile = bool(ga4_view(ga4 or {})["labels"])

    def gegen(key):
        if not f or f["delta"].get(key) is None:
            return "kein Vergleichswert aus dem Vorjahr"
        return f"{delta(f['delta'][key])} gegen das Vorjahr"

    if f:
        j = f["jetzt"]
        umsatz, best, aov = j["umsatz"], j["bestellungen"], j["aov"]
        ses, cr = j["sessions"], j["conversion"]
    else:
        t = (shop or {}).get("totals") or {}
        umsatz, best, aov = t.get("total_sales"), t.get("orders"), t.get("average_order_value")
        ses = ((ga4 or {}).get("totals") or {}).get("sessions")
        cr = (best / ses) if (best and ses) else None

    ses_note = gegen("sessions")
    cr_note = (points(f["jetzt"]["conversion"], f["vorjahr"]["conversion"])
               if f else "kein Vergleichswert aus dem Vorjahr")

    # Woher die Sitzungen kommen, steht auf der Kachel. Zählt der Shop selbst,
    # ist die Zahl um den automatisierten Verkehr bereinigt und die Conversion
    # Rate gilt; kommt sie aus Analytics, ist beides ungefiltert. Ohne diesen
    # Satz stehen zwei Sitzungszahlen im selben Dokument, die um ein Vielfaches
    # auseinanderliegen, und keine sagt, welche gilt.
    source = (f or {}).get("sessions_quelle", "analytics")
    ses_quelle = "shopify" if source == "shop" else "ga4"
    if source == "shop":
        herkunft = "Gezählt vom Shop, ohne automatisierten Verkehr"
        ga4_ses = (f or {}).get("jetzt", {}).get("ga4_sessions")
        if ga4_ses:
            herkunft += f". Analytics meldet für denselben Zeitraum {num_de(ga4_ses)}"
            if bot_profile:
                herkunft += ", darin ein auffälliges Bot-Profil"
        ses_note = f"{ses_note}. {herkunft}"
        cr_note = f"{cr_note}. Gerechnet gegen die Sitzungen des Shops"
    if f and f["bereinigt"]["ausgelassen"]:
        # Der rohe Vergleich teilt gegen aufgeblähte Sessions und meldet einen
        # Einbruch, der ein Messartefakt ist. Die Bereinigung wird ausgewiesen,
        # nie still gerechnet.
        b = f["bereinigt"]
        ohne = (f"ohne {len(b['ausgelassen'])} Monate, in denen die Messung "
                "gestört war")
        ses_note = f"{delta(b['sessions_delta'])} gegen das Vorjahr, {ohne}"
        # Die Conversion-Kachel zeigt in diesem Fall den bereinigten Wert, nicht
        # den ueber alle zwoelf Monate: der teilt echte Bestellungen durch
        # aufgeblaehte Sitzungen und ist zu niedrig. Wert und Notiz muessen
        # dieselbe Rechnung zeigen, sonst steht auf der Kachel 1,25 Prozent und
        # darunter "von 1,99 auf 1,87".
        cr = b["conversion"]
        cr_note = (f"{points(b['conversion'], b['conversion_vorjahr'])}. "
                   f"Gerechnet über die {b['monate']} Monate, in denen die "
                   "Messung durchlief")

    def kachel(value, note, source):
        return note if value is not None else run.reason(source)

    # Lief im Messzeitraum ein Preistest, sind Umsatz, Bestellungen,
    # Bestellwert und Conversion der Mittelwert mehrerer gleichzeitig
    # ausgespielter Preise. Die Baseline weigert sich aus genau diesem Grund,
    # diese Blöcke einzufrieren; das Deckblatt darf sie dann nicht ohne
    # denselben Vorbehalt zeigen.
    crawl = run.snap("crawl.json")
    test = gates.price_test_verdict(crawl) if crawl else {}

    values = {
        "__KPI_PERIOD__": f"Zeitraum {label}, verglichen mit den zwölf Monaten davor"
                          if f else label,
        "__KPI_REVENUE__": num_de(umsatz, 0, " €"),
        "__KPI_REVENUE_NOTE__": kachel(umsatz, _mit(gegen("umsatz"), test), "shopify"),
        "__KPI_ORDERS__": num_de(best),
        "__KPI_ORDERS_NOTE__": kachel(best, _mit(gegen("bestellungen"), test), "shopify"),
        "__KPI_AOV__": num_de(aov, 2, " €"),
        "__KPI_AOV_NOTE__": kachel(aov, _mit(gegen("aov"), test), "shopify"),
        "__KPI_CR__": percent(cr, 2),
        "__KPI_CR_NOTE__": kachel(cr, _mit(cr_note, test), "ga4"),
        "__KPI_SESSIONS__": num_de(ses),
        "__KPI_SESSIONS_NOTE__": kachel(ses, ses_note, ses_quelle),
    }
    if bot_profile and source == "analytics":
        # Kommen die Sitzungen aus Analytics, zählt das Bot-Profil in beiden
        # Kacheln mit, und die Conversion Rate teilte echte Bestellungen durch
        # aufgeblähte Sitzungen. Eine falsche Zahl auf dem Deckblatt wiegt
        # schwerer als eine fehlende, also nennen beide Kacheln den Grund.
        values.update({
            "__KPI_CR__": "nicht messbar",
            "__KPI_CR_NOTE__": ("Gerechnet gegen Sitzungen mit einem auffälligen "
                                "Bot-Profil stünde die Rate zu niedrig da, und ohne "
                                "das Profil gibt es für diesen Zeitraum keine Zahl"),
            "__KPI_SESSIONS__": "nicht messbar",
            "__KPI_SESSIONS_NOTE__": ("Analytics zählt ein auffälliges Bot-Profil mit, "
                                      "und ohne das Profil gibt es für diesen Zeitraum "
                                      "keine Zahl"),
        })
    sechste = _sixth_tile(run)
    # Eine fehlende Kennzahl wird gezeigt, aber nicht geschrien.
    sechste["__KPI_SIXTH_CLASS__"] = (
        "value--leer" if sechste["__KPI_SIXTH__"] == "nicht erhoben" else "")
    values.update(sechste)
    return values


def _sixth_tile(run: Run) -> dict:
    """Die vierte Variable der Umsatzgleichung, so weit die Quellen sie hergeben.

    Erste Wahl ist die Wiederkaufrate: sie ist der Hebel, der in fast jedem
    Shop-Report fehlt und ueber die Wirtschaftlichkeit mehr sagt als jede
    Sichtbarkeitszahl. Fehlt sie, ruecken Retourenquote und Rohertrag nach,
    beide margenrelevant. Ist keine davon erhoben, sagt die Kachel welche
    fehlt und warum. **Nie durch eine Zahl ersetzen, die gerade greifbar ist:**
    bis zum 07.09.2026 stand hier die Zahl der aktiven Produkte, ein
    Bestandsfakt ohne jede Aussage ueber das Geschaeft.
    """
    shop, cat = run.snap("shopify.json"), run.snap("catalog.json")

    ct = (shop or {}).get("customer_type")
    if ct:
        wieder = ct.get("returning_share") if isinstance(ct, dict) else None
        if wieder is not None:
            return {"__KPI_SIXTH_LABEL__": "Wiederkaufrate",
                    "__KPI_SIXTH__": percent(wieder),
                    "__KPI_SIXTH_NOTE__": "Anteil der Bestellungen von Kunden, "
                                          "die schon einmal gekauft haben"}
    ret = (shop or {}).get("returns")
    if isinstance(ret, dict) and ret.get("rate") is not None:
        return {"__KPI_SIXTH_LABEL__": "Retourenquote",
                "__KPI_SIXTH__": percent(ret["rate"]),
                "__KPI_SIXTH_NOTE__": "Anteil des Umsatzes, der zurückgeht"}
    cs = (cat or {}).get("summary") or {}
    if cs.get("variants_total") and cs.get("variants_without_cost") is not None:
        gepflegt = cs["variants_total"] - cs["variants_without_cost"]
        if gepflegt / cs["variants_total"] > 0.5:
            return {"__KPI_SIXTH_LABEL__": "Rohertrag",
                    "__KPI_SIXTH__": "siehe Handel",
                    "__KPI_SIXTH_NOTE__": "aus Einkaufspreisen und Umsatz gerechnet"}

    # Der Grund steht in Kundensprache, nicht im Wortlaut der Schnittstelle.
    # Auf dem Deckblatt hat "ShopifyQL meldet Column Not Found" nichts
    # verloren; der technische Wortlaut steht in der Lücken-Sektion.
    return {"__KPI_SIXTH_LABEL__": "Wiederkaufrate",
            "__KPI_SIXTH__": "nicht erhoben",
            "__KPI_SIXTH_NOTE__":
                ("Der Shop trennt Bestellungen nicht nach Neu- und "
                 "Bestandskunden. Mit diesem Zugang kommt der vierte Hebel "
                 "der Umsatzrechnung dazu.")}


def _shorten(text, n=150) -> str:
    """Kuerzt an einer Satzgrenze, nie mitten im Gedanken.

    Ein Absatz, der mit "... oder eine Verzerrung, weil ..." aufhoert, ist
    schlechter als ein Absatz, der zwanzig Zeichen laenger ist. Gibt es im
    erlaubten Bereich kein Satzende, bleibt der ganze Text stehen: ein
    abgeschnittener Satz sieht aus wie ein Fehler und liest sich auch so.
    """
    t = " ".join(str(text or "").split())
    if len(t) <= n:
        return t
    letztes = max(t.rfind(". ", 0, n + 60), t.rfind("! ", 0, n + 60),
                  t.rfind("? ", 0, n + 60))
    if letztes > n // 2:
        return t[:letztes + 1]
    return t


#: Wie eine Sektion im Report heisst, plus ihre Nummer im Inhalt.
#: Die Abschnitte tragen die eingefuehrten Namen ihrer Disziplin, nicht
#: umschriebene. "Shop und Conversion" heisst im Fach Conversion Rate
#: Optimierung, "Bezahlte Suche" heisst SEA. Yves dazu: *"Wir sind die
#: E-Com-Profis, wir brauchen keine erfundenen Worte."* Wo die Abkuerzung
#: gelaeufiger ist als das ausgeschriebene Wort, steht sie in Klammern
#: dahinter, damit beide Leser den Abschnitt finden.
#:
#: **Diese Tabelle und die <h2> im Template muessen uebereinstimmen.** Ein
#: Test prueft das, weil die Web-Navigation aus dieser Tabelle kommt und das
#: PDF aus dem Template: laufen sie auseinander, heisst derselbe Abschnitt an
#: zwei Stellen verschieden.
SECTION_TITLES = {
    "shop": (1, "Shop-Setup"),
    "measurement": (2, "Tracking und Datenqualität"),
    "commerce": (3, "Umsatz und Sortiment"),
    "traffic": (4, "Traffic und Kanäle"),
    "conversion": (5, "Conversion Rate Optimierung"),
    # Vertrauen steht direkt hinter der Conversion, weil es dieselbe Frage
    # beantwortet: was hält einen Menschen davon ab, hier zu kaufen. Ein
    # fehlendes Impressum ist kein Rechtsthema am Rand, es ist ein
    # Kaufhindernis mit Rechtsfolge.
    "trust": (6, "Trust und Compliance"),
    "seo": (7, "Suchmaschinenoptimierung (SEO)"),
    "geo": (8, "Generative Engine Optimization (GEO)"),
    "tech": (9, "Technisches SEO und Ladezeit"),
    "catalogue": (10, "Produktdaten und Content"),
    "competition": (11, "Wettbewerb"),
    "sea": (12, "Suchmaschinenwerbung (SEA)"),
}

#: Drei Schweregrade, hart definiert. Die Zahl der Stufen schreibt kein
#: Standard vor, die Definition und die durchgaengige Anwendung schon
#: (IIA Global Internal Audit Standards 14.3). Drei ist die Form, in der die
#: Nielsen Norman Group berichtet, sobald berichtet statt geforscht wird.
SEVERITY_ORDER = {"hoch": 0, "mittel": 1, "gering": 2}
SEVERITY_LABEL = {"hoch": "hoch", "mittel": "mittel", "gering": "gering"}


def severity_rank(finding: dict, backlog: dict) -> str:
    """Der Schweregrad eines Befunds.

    Erste Quelle ist das Feld `severity` aus der Analyse. Fehlt es (Snapshots
    vor dem 07.09.2026), wird es aus dem Hebel der Massnahmen abgeleitet, die
    auf diesen Befund verweisen: eine Massnahme mit hohem Hebel folgt aus
    einem schwerwiegenden Befund. Gibt es auch die nicht, entscheidet die
    Sicherheit der Analyse, und ein blosser Verdacht ist nie "hoch".

    **Schweregrad ist nicht Priorität.** Der Schweregrad sagt, wie schwer der
    Befund wiegt, die Reihenfolge der Umsetzung entsteht zusaetzlich aus dem
    Aufwand. Deshalb stehen beide getrennt im Dokument (CVSS v4.0 User Guide:
    Base Scores messen Schwere und taugen allein nicht zur Risikobewertung).
    """
    raw = str(finding.get("severity") or "").strip().lower()
    if raw in SEVERITY_ORDER:
        return raw
    hebel = {m.get("leverage") for m in (backlog.get("measures") or [])
             if m.get("finding_ref") == finding.get("id")}
    if "high" in hebel:
        return "hoch"
    if "medium" in hebel:
        return "mittel"
    if hebel:
        return "gering"
    return {"confirmed": "mittel", "plausible": "gering",
            "hypothesis": "gering"}.get(finding.get("confidence"), "gering")


def findings_by_section(run: Run) -> dict:
    """Alle Befunde, nach Sektion sortiert, mit Kennung und Schweregrad."""
    out = {}
    for filename, doc in run.findings.items():
        sektion = SECTION_BY_FILE.get(filename)
        if not sektion:
            continue
        items = []
        for i, f in enumerate(doc.get("findings") or [], 1):
            b = dict(f, id=finding_id(filename, f.get("id"), i))
            b["_schwere"] = severity_rank(b, run.backlog)
            items.append(b)
        out[sektion] = items
    return out


#: Sektionen, die ohne ihre eine Leitquelle nicht bewertbar sind. Der Abschnitt
#: traegt dann zwar Befunde aus Nachbarquellen, aber nicht die, um die es geht:
#: ohne Werbekonto kein Ausgabenverlauf, kein ROAS, kein Impression Share, keine
#: Verschwendung ueber Suchbegriffe. Am 08.09.2026 stand SEA deshalb auf 92 von
#: 100, dem hoechsten Wert des ganzen Laufs, weil vier Befunde aus der
#: Shopping-Stichprobe keinen schweren enthielten. Ein Bereich, in den niemand
#: hineinsehen konnte, darf nicht aussehen wie einer ohne Probleme.
LEAD_SOURCE = {"sea": "ads", "geo": "geo", "catalogue": "catalogue",
              "traffic": "ga4", "commerce": "shopify", "tech": "cwv",
              "trust": "crawl"}


def scores(run: Run) -> dict:
    """Die Health Scores dieses Laufs."""
    je_sektion = findings_by_section(run)
    # Eine Sektion ohne Datengrundlage bekommt keinen Score: sonst sieht ein
    # Bereich, den niemand pruefen konnte, aus wie einer ohne Probleme.
    ohne = {k for k in SECTIONS
            if k not in je_sektion and k not in ("gaps", "sources", "shop")}
    ohne |= {k for k, source in LEAD_SOURCE.items()
             if (run.state.get("sources", {}).get(source, {}).get("status")
                 not in ("done",))}
    return score_mod.compute(je_sektion, run.backlog.get("measures") or [], ohne)


def score_leiste(run: Run) -> str:
    """Gesamtscore plus Bereiche, als Einstieg in die Bewertung."""
    sc = scores(run)
    if sc["gesamt"] is None:
        return ("<p>Für diesen Lauf liegen zu wenige Befunde vor, um den Shop "
                "zu bewerten.</p>")
    kacheln = []
    for name, b in score_mod.AREAS.items():
        value, z = sc["bereiche"][name], sc["bereich_ziele"][name]
        if value is None:
            kacheln.append(
                f'<div class="score"><p class="label">{esc(b["label"])}</p>'
                '<p class="value value--leer">nicht bewertbar</p>'
                '<p class="caption">In diesem Bereich hat keine Quelle '
                "geliefert.</p></div>")
            continue
        width = max(0, min(100, value))
        ziel_pos = max(0, min(100, z or value))
        kacheln.append(
            f'<div class="score"><p class="label">{esc(b["label"])}</p>'
            f'<p class="value">{value}<span class="unit">/100</span></p>'
            f'<div class="scorebar"><span style="width:{width}%"></span>'
            f'<i style="left:{ziel_pos}%"></i></div>'
            f'<p class="caption">Ziel {z} nach Umsetzung der Maßnahmen '
            f"in diesem Bereich</p></div>")
    return (f'<div class="score-total"><p class="value">{sc["gesamt"]}'
            f'<span class="unit">/100</span></p>'
            f'<p class="arrow">{sc["gesamt_ziel"]} erreichbar</p>'
            '<p class="label">PTAI E-Com Score · heute und nach '
            "Umsetzung der Maßnahmen</p></div>"
            f'<div class="score-grid">{"".join(kacheln)}</div>'
            "<p>Der Score fasst alle Befunde dieses Laufs zu einer Zahl "
            "zusammen, gewichtet nach Schweregrad und danach, wie sicher der "
            "Befund belegt ist. 100 hieße: in keinem geprüften Punkt etwas "
            "gefunden. 92 ist das Maximum, das ein Audit vergeben kann, denn "
            "geprüft wird, was prüfbar ist. Das Ziel ist der Stand, wenn alles "
            "umgesetzt ist, wofür in diesem Report eine Maßnahme steht; was "
            "darüber hinaus fehlt, sind offene Fragen und Lücken in der "
            "Datenlage. <strong>Der eigentliche Vergleichswert entsteht beim "
            "nächsten Lauf:</strong> die heutigen Zahlen sind eingefroren, und "
            "der nächste Report misst gegen sie.</p>")


def sec_method(run: Run) -> str:
    """Wie der Score gerechnet wird, aus den Konstanten des Moduls erzeugt.

    **Der Text wird nicht getippt, er wird gebaut.** Eine Methodenbeschreibung
    von Hand veraltet mit der ersten Aenderung an einem Gewicht, und niemand
    merkt es: das Dokument rendert weiter. Alles Zahlenhafte hier unten kommt
    deshalb aus `score.py` selbst.

    **Was hier ausdruecklich steht, ist die Grenze der Methode.** Die Gewichte
    sind eine Kalibrierung, keine Messung, und der Score vergleicht nicht gegen
    andere Shops. Wer das verschweigt, verkauft eine Zahl als mehr, als sie
    ist, und beim ersten Nachfragen bricht sie zusammen.
    """
    sm = score_mod
    bereiche = table(
        ["Bereich", "Gewicht", "Abschnitte"],
        [(b["label"], percent(b["gewicht"], 0),
          ", ".join(SECTION_TITLES[k][1] for k in b["sektionen"]
                    if k in SECTION_TITLES))
         for b in sm.AREAS.values()])
    strafen = table(
        ["Schweregrad", "Strafpunkte", "Wann"],
        [("hoch", num_de(sm.PENALTY["hoch"]),
          "kostet heute Geld oder macht andere Zahlen unbrauchbar"),
         ("mittel", num_de(sm.PENALTY["mittel"]),
          "messbarer Verlust, aber nicht akut"),
         ("gering", num_de(sm.PENALTY["gering"]),
          "Hygiene, heute ohne messbaren Verlust")])
    sicher = table(
        ["Wie sicher der Befund ist", "Faktor auf die Strafpunkte"],
        [("belegt", num_de(sm.CERTAINTY["confirmed"], 1)),
         ("plausibel", num_de(sm.CERTAINTY["plausible"], 1)),
         ("Verdacht", num_de(sm.CERTAINTY["hypothesis"], 1))])
    return (
        '<p class="eyebrow eyebrow--line">Die Rechnung</p>'
        f"<p>Jeder Abschnitt startet bei 100 Punkten. Jeder Befund darin zieht "
        f"Punkte ab, nach Schweregrad und danach, wie sicher er belegt ist. Der "
        f"Bereichswert ist der Mittelwert seiner Abschnitte, der Gesamtwert das "
        f"gewichtete Mittel der Bereiche.</p>"
        + strafen
        + "<p>Ein Verdacht kostet weniger als eine Messung. Der Faktor wirkt "
          "auf die Strafpunkte oben.</p>"
        + sicher
        + '<p class="eyebrow eyebrow--line">Die Bereiche und ihr Gewicht</p>'
        + bereiche
        + "<p>Die Gewichtung folgt der Umsatzrechnung: was den Kauf betrifft, "
          "wiegt am schwersten, danach die Sichtbarkeit, die ihn ermöglicht. "
          "Der Abschnitt Shop-Setup fließt nicht ein, er ist eine "
          "Bestandsaufnahme und keine Bewertung.</p>"
        + '<p class="eyebrow eyebrow--line">Drei Regeln, die den Wert begrenzen</p>'
        + table(["Regel", "Wert", "Warum"], [
            ("Höchstwert", num_de(sm.DECKEL),
             "Ein Audit prüft, was prüfbar ist. 100 hieße, es gibt nichts mehr "
             "zu finden, und das kann niemand behaupten."),
            ("Tiefstwert", num_de(sm.FLOOR),
             "Sonst läuft ein gründlich geprüfter Abschnitt allein durch die "
             "Menge seiner Befunde gegen null."),
            ("Abnehmender Ertrag",
             f"{num_de(sm.HIGH_DAMPING, 2)} bzw. {num_de(sm.MITTEL_DAEMPFUNG, 2)}",
             f"Jeder weitere Befund derselben Stufe zählt weniger als der "
             f"davor, und von den mittleren zählen die "
             f"{num_de(sm.MITTEL_DECKEL)} schwersten. Sonst misst der Score, wie "
             "genau wir hingesehen haben, statt wie der Shop dasteht.")])
        + '<p class="eyebrow eyebrow--line">Wie das Ziel entsteht</p>'
        + "<p>Für das Ziel wird derselbe Wert noch einmal gerechnet, diesmal "
          "ohne die Befunde, für die in diesem Report eine Maßnahme steht. Es "
          "ist also der Stand, wenn alles umgesetzt ist. Was das Ziel unter "
          "dem Höchstwert hält, sind die Befunde ohne Maßnahme: offene Fragen, "
          "Lücken in der Datenlage und Dinge außerhalb des eigenen Zugriffs.</p>"
        + '<p class="eyebrow eyebrow--line">Was der Score nicht ist</p>'
        + "<p><strong>Er vergleicht nicht gegen andere Shops.</strong> Für ein "
          "Sortiment dieser Art gibt es keine belastbare öffentliche "
          "Vergleichszahl; die kursierenden Branchenwerte stammen aus "
          "Aggregator-Blogs und halten einer Nachfrage nicht stand. Ein "
          "Benchmark, den man nicht belegen kann, macht jede Aussage daneben "
          "angreifbar.</p>"
        + "<p><strong>Die Gewichte oben sind eine Kalibrierung, keine "
          "Messung.</strong> Sie sind so gewählt, dass ein schwerer Befund "
          "spürbar mehr wiegt als ein leichter und dass gründliches Prüfen den "
          "Wert nicht ruiniert. Sie stammen aus keiner Studie. Was die Methode "
          "garantiert, ist etwas anderes und für den Zweck entscheidend: "
          "<strong>dieselben Befunde ergeben immer denselben Wert, und zwei "
          "Läufe desselben Shops sind miteinander vergleichbar.</strong> Genau "
          "dafür ist die Baseline da.</p>"
        + "<p>Die Rechnung liegt offen: sie steht in "
          '<span class="mono">scripts/audit/score.py</span> des Plugins, das '
          "diesen Report erzeugt hat, und diese Seite ist daraus erzeugt, nicht "
          "danebengeschrieben.</p>")


def findings_overview(run: Run) -> str:
    """Die Befunde im Überblick, als Einstieg statt als Nachschlagewerk.

    Ersetzt seit dem 07.09.2026 die Tabelle "Der Zustand je Bereich". Die
    trug je Bereich eine Kernzahl ohne Zeitraum und eine Einordnung, die der
    Leser nicht auflösen konnte ("bereinigt gegen das Vorjahr"). Yves dazu:
    *"Die Zahlen bringen mir eigentlich nichts, weil ich nicht verstehe, was
    die aussagen."*

    Was hier steht, ist Navigation für ein Dokument, das niemand von vorn bis
    hinten liest: wo die Befunde liegen, wie schwer sie wiegen, und in welchem
    Abschnitt sie stehen. Das IIA nennt genau das als Regelform
    ("a dashboard that lists the findings in the form of a table"), der GAO
    Yellow Book als Highlights-Seite (9.17e).
    """
    rows, schwere_liste = [], []
    for filename, doc in sorted(run.findings.items()):
        sektion = SECTION_BY_FILE.get(filename)
        number, title = SECTION_TITLES.get(sektion, (99, sektion or filename))
        findings = []
        for i, f in enumerate(doc.get("findings") or [], 1):
            b = dict(f, id=finding_id(filename, f.get("id"), i))
            b["_schwere"] = severity_rank(b, run.backlog)
            findings.append(b)
        if not findings:
            continue
        hoch = [b for b in findings if b["_schwere"] == "hoch"]
        schwere_liste += [(number, title, b) for b in hoch]
        rows.append((number, (title, num_de(len(findings)),
                                num_de(len(hoch)) if hoch else "keiner",
                                f"Abschnitt {number}")))
    rows.sort(key=lambda z: z[0])
    tab = table(["Bereich", "Befunde", "davon schwerwiegend", "Steht in"],
                  [z[1] for z in rows],
                  empty="Für diesen Lauf liegen keine Befunde vor.")
    if not schwere_liste:
        return tab
    schwere_liste.sort(key=lambda x: x[0])
    points_text = "".join(
        f"<li><strong>{esc(b['id'])}</strong> · {esc(title)}: "
        f"{esc(first_sentence(b.get('statement'), 200)[0])}</li>"
        for _, title, b in schwere_liste[:8])
    return (tab + '<p class="eyebrow eyebrow--line">Die schwerwiegenden '
            f"Befunde</p><ol>{points_text}</ol>"
            + (f"<p>Weitere {num_de(len(schwere_liste) - 8)} Befunde tragen "
               "denselben Schweregrad und stehen in ihren Abschnitten.</p>"
               if len(schwere_liste) > 8 else ""))


# --------------------------------------------------------------- Sektionen
#
# Je Sektion eine Funktion: sie liefert den Zahlenblock aus den Snapshots, die
# Befunde haengt `section_blocks()` darunter. Fehlt der Snapshot, gibt die Funktion
# den Grund aus dem Zustand zurueck statt einer leeren Tabelle: eine Sektion,
# die "nicht erhoben, weil ..." sagt, ist eine Aussage, eine leere Tabelle ist
# ein Renderfehler.

def _month_de(m: str) -> str:
    """"2026-01" wird "01/2026". Ein ISO-Datum im Fliesstext liest sich als
    amerikanische Schreibweise, und der Leser rechnet um."""
    try:
        year, month = str(m).split("-")[:2]
        return f"{month}/{year}"
    except ValueError:
        return str(m)


def date_de(d: str) -> str:
    """"2025-04-25" wird "25.04.2025".

    Ein ISO-Datum im Kundendokument liest sich als amerikanische Schreibweise,
    und der Leser haelt "2026-09-06" fuer den 9. Juni.
    """
    try:
        year, month, tag = str(d)[:10].split("-")
        return f"{tag}.{month}.{year}"
    except ValueError:
        return str(d)


def period_de(block) -> str:
    """Der Zeitraum eines Snapshots, deutsch: "25.04.2025 bis 06.09.2026"."""
    per = (block or {}).get("period") or {}
    if not per.get("start"):
        return "Momentaufnahme"
    return f"{date_de(per['start'])} bis {date_de(per['end'])}"


#: Wie eine Datenquelle im Kundendokument heisst. Der Befund nennt intern den
#: Dateipfad im Snapshot, und der ist praezise und fuer die Nachpruefung
#: unverzichtbar, aber er sagt dem Leser nichts.
#:
#: Yves am 09.09.2026 zu "Beleg: ga4.json > compare_properties[0].by_month":
#: *"Die bringen sowieso nichts. Also mir sagt es nichts und dem Kunden wird
#: es noch weniger sagen."* Von 69 Belegzeilen des ersten fertigen Reports
#: trugen 65 einen solchen Pfad.
#:
#: Der Pfad bleibt in `evidence` stehen, die Nachpruefung braucht ihn. Nur die
#: gerenderte Fassung nennt die Quelle so, wie ein Mensch sie nennt.
SOURCE_LABEL = {
    "shopify.json": "Shopify",
    "ga4.json": "Google Analytics 4",
    "gsc.json": "Google Search Console",
    "crawl.json": "Seiten-Erfassung des Shops",
    "cwv.json": "Core Web Vitals, Felddaten aus Chrome",
    "geo.json": "Messung in ChatGPT, Perplexity und Google AI",
    "catalog.json": "Shopify-Produktkatalog",
    "shop-tech.json": "Shop-Konfiguration",
    "screens.json": "Bildschirmaufnahmen des Shops",
    "ads.json": "Google Ads",
    "dfs-shopping.json": "Google Shopping",
    "dfs-rankings.json": "Ranking-Daten",
    "dfs-competitors.json": "Wettbewerbsvergleich",
    "dfs-keywords.json": "Suchvolumen-Daten",
    "dfs-backlinks.json": "Backlink-Profil",
    "state.json": "Zugangslage dieses Laufs",
}

#: Ein Snapshot-Pfad: Dateiname, ">" und alles bis zum naechsten Semikolon.
_SOURCE_PATH = re.compile(
    r"\b([a-z0-9-]+\.json)\s*>\s*[^;]+", re.IGNORECASE)


def evidence_label(evidence: str) -> str:
    """Der Beleg in Kundensprache, ohne Dateipfade.

    Jeder Snapshot-Verweis wird durch den Namen seiner Quelle ersetzt, danach
    werden Dubletten zusammengezogen: drei Verweise in dieselbe Datei nennen
    die Quelle einmal. Teile, die schon in Kundensprache stehen (ein
    Screenshot, ein Seitenpfad, eine eigene Messung), bleiben unveraendert.
    """
    if not evidence:
        return ""
    teile, gesehen = [], set()
    for roh in str(evidence).split(";"):
        teil = roh.strip()
        if not teil:
            continue
        treffer = _SOURCE_PATH.match(teil)
        if treffer:
            teil = SOURCE_LABEL.get(treffer.group(1).lower(), treffer.group(1))
        else:
            # Ein Dateiname mitten im Satz, ohne ">" dahinter: "geprueft je
            # Host aus crawl.json", "catalog.json (Produkttitel-Abgleich)".
            # Auch der ist Pipeline-Sprache und wird durch seine Quelle
            # ersetzt, ohne den umgebenden Satz anzutasten.
            for datei, label in SOURCE_LABEL.items():
                teil = re.sub(rf"\b{re.escape(datei)}\b", label, teil,
                              flags=re.IGNORECASE)
        if teil.lower() not in gesehen:
            gesehen.add(teil.lower())
            teile.append(teil)
    return "; ".join(teile)


def _missing(run: Run, key: str, was: str) -> str:
    return f"<p>{esc(was)} wurde nicht erhoben: {esc(run.reason(key))}</p>"


def sec_shop(run: Run) -> str:
    st, shop = run.snap("shop-tech.json"), run.snap("shopify.json")
    cat = run.snap("catalog.json")
    if not st:
        return _missing(run, "shop_tech", "Der technische Stand des Shops")
    s, th = st.get("summary") or {}, st.get("theme") or {}
    cs = (cat or {}).get("summary") or {}
    av = (shop or {}).get("availability") or {}
    maerkte = [m.get("name") or m.get("handle") for m in (st.get("markets") or [])]
    sprachen = [l.get("locale") for l in (st.get("locales") or [])]
    rows = [
        ("Aktives Theme", f"{th.get('name', 'unbekannt')}",
         f"zuletzt geändert am {date_de(th.get('updated_at') or '') or 'unbekannt'}"),
        ("Themes im Konto", num_de(s.get("themes_total")),
         "inklusive der unveröffentlichten Entwürfe"),
        ("Produkte", num_de(cs.get("products_total") or len(shop.get("products") or [])
                        if shop else cs.get("products_total")),
         f"davon {num_de(cs.get('products_active'))} aktiv im Shop" if cs else ""),
        ("Varianten", num_de(cs.get("variants_total") or av.get("variants_total")),
         f"davon {num_de(av.get('variants_available'))} bestellbar" if av else ""),
        ("Sprachen", num_de(s.get("locales_total")), ", ".join(x for x in sprachen if x)),
        ("Märkte", num_de(s.get("markets_total")), ", ".join(x for x in maerkte if x)[:120]),
        ("Skripte fremder Anbieter", num_de(s.get("third_party_script_hosts")),
         "verschiedene Hosts im Quelltext der besuchten Seiten"),
        ("Mess-IDs im Quelltext", num_de(s.get("inline_tag_ids")),
         ", ".join(sorted((st.get("storefront_inline_tag_ids") or {}).keys()))),
    ]
    return numbers_block(["Angabe", "Wert", "Bezug"], rows,
                       zeitraum=f"Stichtag des Laufs, {date_de(run.run_id)}")


def sec_measurement(run: Run) -> str:
    shop, ga4 = run.snap("shopify.json"), run.snap("ga4.json")
    if not (shop and ga4):
        return _missing(run, "ga4", "Der Abgleich zwischen Shop und Analytics")
    f, rows = run.fenster, []
    st = shop.get("totals") or {}
    # Die Zuordnungsluecke wird ueber identische Monate gerechnet, nie ueber
    # die Gesamtsummen beider Dateien. Shopify reicht Jahre weiter zurueck als
    # Analytics, und der rohe Vergleich misst deshalb hauptsaechlich die
    # verschiedenen Startdaten. Genau das hat die Datenqualitaets-Analyse am
    # 07.09.2026 als eigenen Befund gemeldet.
    j = f["jetzt"] if f else {}
    # Meldet ein zweiter Absender Käufe mit, zählt die Monatsreihe jeden Kauf
    # seit dem Stichtag doppelt, und die Lücke wirkt kleiner, als sie ist. Käufe
    # des ersten Absenders gibt es nur über den ganzen Abfragezeitraum, nicht je
    # Monat (ga4_purchase_rows). Beide Zeilen nennen dann den Grund statt einer
    # falschen Zahl.
    onset = (ga4.get("senders") or {}).get("onset")
    doubled_reason = None
    if "purchase" in ga4_view(ga4)["double_counted"]:
        doubled_reason = ("Analytics zählt Käufe" + (f" seit {date_de(onset)}" if onset else "")
                          + " doppelt, weil ein zweiter Absender sie mitmeldet")
    # Der Umsatz aus Analytics steht in der Berichtswährung der Property, und
    # die muss nicht Euro sein: am 11.09.2026 fiel eine Property in USD neben
    # einem Shop in Euro auf. Der Report schreibt Shop-Umsätze in Euro, also
    # entsteht die Zeile nur, wenn der Snapshot Euro belegt. Snapshots von vor
    # diesem Tag tragen keine Währung und bekommen die Zeile deshalb nicht.
    if (j.get("umsatz") and j.get("ga4_umsatz") is not None
            and ga4.get("currency") == "EUR"):
        if doubled_reason:
            rows.append(("Zuordnungslücke Umsatz", "nicht messbar", doubled_reason))
        else:
            rows.append(("Zuordnungslücke Umsatz", percent(1 - j["ga4_umsatz"] / j["umsatz"]),
                           f"{num_de(j['ga4_umsatz'], 0, ' €')} von Analytics zugeordnet, "
                           f"{num_de(j['umsatz'], 0, ' €')} im Shop verbucht, "
                           f"{f['label']}"))
    # Die Käufe kommen aus `purchases`, ohne Refunds (window.purchases).
    if j.get("bestellungen") and j.get("ga4_kaeufe") is not None:
        if doubled_reason:
            rows.append(("Zuordnungslücke Bestellungen", "nicht messbar", doubled_reason))
        else:
            rows.append(("Zuordnungslücke Bestellungen",
                           percent(1 - j["ga4_kaeufe"] / j["bestellungen"]),
                           f"{num_de(j['ga4_kaeufe'])} Kaufereignisse in Analytics "
                           f"gegen {num_de(j['bestellungen'])} Bestellungen im Shop, "
                           f"{f['label']}"))
    rows.append(("Analytics misst seit",
                   date_de(ga4.get("history_from") or ""),
                   "erster Tag mit Daten in dieser Property"))
    gsc = run.snap("gsc.json")
    if gsc:
        rows.append(("Search Console reicht zurück bis",
                       date_de(gsc.get("history_from") or ""),
                       "Google gibt nie mehr als 16 Monate heraus"))
    if f and f["stoerungen"]:
        # "4 Monate mit auffälligen Werten" ist keine Aussage: der Leser weiss
        # nicht, welche Werte auffällig waren und was er damit anfangen soll.
        # Die Zeile nennt deshalb den Grund je Monat.
        gruende = {}
        for month, reason in f["stoerungen"]:
            gruende.setdefault(reason, []).append(month)
        for reason, months in gruende.items():
            rows.append((f"Monate mit {reason}", num_de(len(months)),
                           ", ".join(_month_de(m) for m in sorted(months))))
    return numbers_block(["Angabe", "Wert", "Bezug"], rows,
                       zeitraum=period_de(ga4))


def sec_commerce(run: Run) -> str:
    shop = run.snap("shopify.json")
    if not shop:
        return _missing(run, "shopify", "Der Handel")
    t, av, f = shop.get("totals") or {}, shop.get("availability") or {}, run.fenster
    months = [m for m in (shop.get("by_month") or []) if (m.get("total_sales") or 0) > 0]
    diagramm = ""
    if f:
        umsatz_je = {m["month"]: m.get("total_sales") for m in months}
        diagramm = charts.year_comparison(
            [(_month_de(m)[:2], umsatz_je.get(m), umsatz_je.get(v))
             for m, v in zip(f["jetzt"]["monate"], f["vorjahr"]["monate"])],
            f"Umsatz {f['label']} gegen {f['label_vorjahr']}")
    rows = [
        ("Umsatz gesamt", num_de(t.get("total_sales"), 0, " €"),
         f"über {num_de(len(months))} Monate mit Umsatz"),
        ("Bestellungen gesamt", num_de(t.get("orders")), ""),
        ("Bestellwert", num_de(t.get("average_order_value"), 2, " €"),
         "über die volle Historie"),
    ]
    if f:
        j, v = f["jetzt"], f["vorjahr"]
        rows += [
            (f"Umsatz {f['label']}", num_de(j["umsatz"], 0, " €"),
             f"{delta(f['delta']['umsatz'])} gegen {f['label_vorjahr']} "
             f"({num_de(v['umsatz'], 0, ' €')})"),
            (f"Bestellungen {f['label']}", num_de(j["bestellungen"]),
             f"{delta(f['delta']['bestellungen'])} gegen das Vorjahr "
             f"({num_de(v['bestellungen'])})"),
            (f"Bestellwert {f['label']}", num_de(j["aov"], 2, " €"),
             f"{delta(f['delta']['aov'])} gegen das Vorjahr"),
        ]
    if months:
        best = max(months, key=lambda m: m.get("total_sales") or 0)
        rows.append(("Stärkster Monat", num_de(best.get("total_sales"), 0, " €"),
                       _month_de(best.get("month") or best.get("period") or "")))
    if av:
        rows += [
            ("Aktive Produkte", num_de(av.get("active_products")), ""),
            ("Davon gar nicht kaufbar", num_de(av.get("products_fully_unavailable")),
             "keine einzige Variante bestellbar"),
            ("Davon teilweise kaufbar", num_de(av.get("products_partially_available")),
             "mindestens eine Variante nicht bestellbar"),
        ]
    top = shop.get("top_products") or []
    if top:
        total = sum(p.get("net_sales") or p.get("total_sales") or 0 for p in top)
        oben = sum((p.get("net_sales") or p.get("total_sales") or 0)
                   for p in top[:20])
        if total:
            rows.append(("Umsatzanteil der 20 stärksten Artikel", percent(oben / total),
                           f"von {num_de(len(top))} Artikeln mit Umsatz"))
    zt = (f"{_month_de(months[0]['month'])} bis {_month_de(months[-1]['month'])}"
          if months else period_de(shop))
    return diagramm + numbers_block(["Kennzahl", "Wert", "Bezug"], rows,
                                  zeitraum=zt)


def currency_suffix(snapshot: dict, name: str) -> str:
    """Die Einheit hinter einem Geldbetrag, als `suf` für num_de.

    GA4 berichtet in der Berichtswährung der Property, Google Ads in der
    Währung des Kontos, und beide müssen nicht die des Shops sein: am
    11.09.2026 fiel eine Property in USD neben einem Shop in Euro auf. Beide
    Pulls legen die Währung als `currency` in den Snapshot, und trotzdem stand
    jeder Betrag mit Euro-Zeichen im Report, bei GA4 bis zum 12.09.2026, bei
    Google Ads bis zum 13.09.2026. Bei Euro bleibt das Zeichen, jede andere
    Währung steht als ihr Code, weil ein Code eindeutig ist und ein Symbol wie
    $ nicht. Umgerechnet wird nichts.

    **Nennt der Snapshot keine Währung, steht keine Einheit da.** Das gilt für
    GA4-Snapshots von vor dem 11.09.2026 und für jede Antwort ohne
    Währungscode. Euro anzunehmen wiederholt den Fehler, sobald ein alter Lauf
    mit einer Property in USD neu gebaut wird; sec_measurement lässt die
    Zuordnungslücke aus demselben Grund weg. Die Beträge wegzulassen wäre eine
    fehlende Zahl, und das Verhältnis zwischen Kanälen, Geräten oder Kosten und
    Umsatz gilt in jeder Währung. Ein Satz dazu im Dokument spräche über den
    Stand unseres Werkzeugs statt über den Shop (siehe OUT_OF_SCOPE). Deshalb
    geht die Warnung an den, der den Report baut, und nennt die Datei `name`:
    ein neuer Pull dieser Quelle bringt die Währung mit.
    """
    code = snapshot.get("currency")
    if not code:
        print(f"Warnung: {name} nennt keine Währung. Die Beträge daraus stehen "
              "ohne Einheit im Report, ein neuer Pull bringt sie mit.",
              file=sys.stderr)
        return ""
    return " €" if code == "EUR" else f" {code}"


def ga4_view(ga4: dict) -> dict:
    """Die GA4-Zahlen, aus denen Traffic und Kaufweg im Report entstehen.

    **Warum nicht der Hauptteil von ga4.json.** Am 13.09.2026 in einem echten
    Audit nachgerechnet: ein Bot-Profil trug die Hälfte aller Sitzungen, und
    ein zweiter Absender meldete jede Stufe des Kaufwegs doppelt. Seitdem
    rechnen die Analysen ihre Befunde ohne das Profil und für doppelt gezählte
    Ereignisse nur mit dem ersten Absender (`ga4_variants`). Der Report las
    bis zum 15.09.2026 weiter den Hauptteil und druckte neben diesen Befunden
    Kanalanteile und einen Kaufweg, deren erste Stufen zur Hälfte Bots waren.

    `block` ist `bot_profiles.without`, wenn der Pull ein Profil erkannt hat,
    sonst der Hauptteil, und `labels` sagt das im Wortlaut der Befunde.
    `double_counted` sind die Ereignisse mit zweitem Absender, `primary` die
    Zahlen des ersten Absenders aus demselben Block. Die Varianten werden nie
    gemischt: der erste Absender im Hauptteil steht auf anderen Sitzungen als
    der Block ohne Profil.
    """
    variant = ga4_variants.variants(ga4)[-1]
    block = variant["block"]
    return {
        "block": block,
        "labels": [] if variant["key"] == "all_sessions" else [variant["label"]],
        "double_counted": set((ga4.get("senders") or {}).get("double_counted_events") or []),
        "primary": block.get("primary_sender") or {},
    }


def ga4_purchase_rows(view: dict, key: str, name: str) -> tuple[list, str]:
    """Die Kanal- oder Gerätezeilen eines Blocks mit den Käufen, die gelten.

    Der zweite Wert sagt, woher Käufe und Umsatz kommen:

    - `block`: aus dem Block selbst, der Kauf hat keinen zweiten Absender.
    - `first_sender`: der Kauf zählt doppelt, es gelten die Käufe des ersten
      Absenders. Eine Zeile, die bei ihm fehlt, hat keinen Kauf, weil GA4
      keine Nullzeilen liefert.
    - `not_measurable`: der Kauf zählt doppelt, und Zahlen des ersten
      Absenders gibt es nicht, weil mehrere Mess-IDs einen zweiten tragen
      oder die Abfrage scheiterte (`senders.primary_sender`). Käufe und
      Umsatz stehen dann auf None: die doppelt gezählte Zahl wäre falsch,
      eine fehlende fällt auf.
    """
    rows = view["block"].get(key) or []
    if "purchase" not in view["double_counted"]:
        return rows, "block"
    first = view["primary"].get(key)
    if first is None:
        return [dict(row, purchases=None, purchase_revenue=None) for row in rows], "not_measurable"
    by_name = {row.get(name): row for row in first}
    out = []
    for row in rows:
        match = by_name.get(row.get(name)) or {}
        out.append(dict(row, purchases=match.get("purchases", 0),
                        purchase_revenue=match.get("purchase_revenue", 0.0)))
    return out, "first_sender"


def ga4_caption(text: str, view: dict, first_sender: bool = False) -> str:
    """Zeitraum oder Zwischenüberschrift einer GA4-Tabelle samt der Variante,
    die sie zeigt, im Wortlaut der Befunde. Ohne Variante bleibt der Text."""
    labels = view["labels"] + ([ga4_variants.PRIMARY_SENDER_LABEL] if first_sender else [])
    return ", ".join([text, *labels])


def sec_traffic(run: Run) -> str:
    ga4 = run.snap("ga4.json")
    if not ga4:
        return _missing(run, "ga4", "Der Traffic")
    unit = currency_suffix(ga4, "ga4.json")
    view = ga4_view(ga4)
    channels, purchases_from = ga4_purchase_rows(view, "channels", "channel")
    kan = sorted(channels, key=lambda c: c.get("sessions") or 0, reverse=True)[:8]
    ges = sum(c.get("sessions") or 0 for c in channels) or 1
    # Zwei Panels, gleiche Reihenfolge: nur so faellt auf, wo viel Traffic
    # wenig Umsatz traegt. Keine Grafik mit zwei Y-Achsen, kein Tortenstueck.
    diagramm = charts.bar_pair(
        [(CHANNEL.get(c.get("channel"), c.get("channel") or ""),
          c.get("sessions"), c.get("purchase_revenue")) for c in kan],
        "Sitzungen", "Umsatz", "Sitzungen und Umsatz je Kanal",
        links_fmt=num_de, rechts_fmt=lambda v: num_de(v, 0, unit))
    rows = []
    for c in kan:
        s, u = c.get("sessions") or 0, c.get("purchase_revenue") or 0
        rows.append((CHANNEL.get(c.get("channel"), c.get("channel") or ""),
                       num_de(s), percent(s / ges),
                       "nicht messbar" if purchases_from == "not_measurable"
                       else num_de(u, 0, unit),
                       percent(c["purchases"] / s, 2)
                       if s and c.get("purchases") is not None
                       else "nicht messbar"))
    tab = diagramm + numbers_block(
        ["Kanal", "Sitzungen", "Anteil", "Umsatz", "Conversion Rate"],
        rows, zeitraum=ga4_caption(period_de(ga4), view, purchases_from == "first_sender"))
    lp = sorted(view["block"].get("landing_pages") or [],
                key=lambda p: p.get("sessions") or 0, reverse=True)[:10]
    if lp:
        # `or 0` waere hier falsch: bis 07.09.2026 fragte der GA4-Pull fuer
        # Einstiegsseiten weder Umsatz noch Bestellungen ab, und der Report
        # druckte in jede Zeile "0 €". Eine fehlende Zahl wird als fehlend
        # gezeigt, nie als Null.
        hat_umsatz = any(p.get("purchase_revenue") is not None for p in lp)
        # Zählt der Kauf doppelt, gibt es je Einstiegsseite keine Zahl des
        # ersten Absenders, und der Umsatz aus dem Block wäre doppelt gezählt.
        doubled = "purchase" in view["double_counted"]
        header = ["Seite", "Sitzungen", "Anteil der Besuche mit Interaktion"]
        if hat_umsatz:
            header += ["Umsatz"]
        rows = []
        for p in lp:
            name = p.get("landing_page") or "(ohne Zuordnung)"
            z = [name, num_de(p.get("sessions")), percent(p.get("engagement_rate"))]
            if hat_umsatz:
                z.append("nicht messbar" if doubled
                         else num_de(p.get("purchase_revenue"), 0, unit))
            rows.append(tuple(z))
        tab += ('<p class="eyebrow eyebrow--line">'
                + ga4_caption("Die stärksten Einstiegsseiten", view) + "</p>"
                + table(header, rows))
        if not hat_umsatz:
            tab += ("<p>Analytics liefert für Einstiegsseiten in diesem Lauf "
                    "keinen Umsatz, deshalb steht hier der Anteil der Besuche "
                    "mit Interaktion. Ab dem nächsten Lauf kommt der Umsatz "
                    "je Seite dazu.</p>")
    return tab


def sec_conversion(run: Run) -> str:
    ga4, shop = run.snap("ga4.json"), run.snap("shopify.json")
    if not ga4:
        return _missing(run, "ga4", "Der Kaufweg")
    view = ga4_view(ga4)
    fu = view["block"].get("funnel") or {}
    ses = fu.get("sessions") or 0
    # Die Stufennamen sind die offiziellen deutschen aus dem GA4-Bericht zum
    # Kaufprozess, mit einer Abweichung: Google uebersetzt add_to_cart mit
    # "Einkaufswagen", und das ist eine Uebersetzung, kein Handelsbegriff.
    # Die deutsche Handelssprache sagt Warenkorb, passend zu
    # Warenkorbabbruchrate und durchschnittlichem Warenkorb.
    stufen = [("Sitzung begonnen", None), ("Artikel angesehen", "view_item"),
              ("In den Warenkorb gelegt", "add_to_cart"),
              ("Warenkorb angesehen", "view_cart"),
              ("Bezahlvorgang gestartet", "begin_checkout"),
              ("Kauf", "purchase")]
    # **Diese Stufen sind keine Kette.** GA4 zaehlt je Stufe die Sitzungen, in
    # denen das Ereignis mindestens einmal vorkam, unabhaengig von der
    # Reihenfolge. Eine Sitzung kann den Warenkorb ansehen, ohne in derselben
    # Sitzung etwas hineingelegt zu haben: mit gespeichertem Warenkorb vom
    # letzten Besuch, ueber einen Newsletter-Link direkt auf /cart, oder durch
    # einen Klick auf das Warenkorb-Symbol.
    #
    # Deshalb steht hier kein "Weiter von der Stufe davor". Diese Spalte stand
    # bis zum 07.09.2026 im Report und behauptete einen Weg, den die Zahlen
    # nicht beschreiben: sie meldete fuer den Warenkorb 237,6 Prozent, also
    # mehr Menschen in der Stufe als in der davor. Yves dazu: *"Ok, dann
    # verstehe ich die Darstellung nicht."* Zu Recht.
    # Stufen, die ein zweiter Absender doppelt meldet, zählen nur die
    # Sitzungen des ersten, wie in den Befunden der Conversion-Analyse.
    first = view["primary"].get("funnel") or {}
    first_steps = {key for _, key in stufen
                   if key in view["double_counted"] and key in first}

    def step(key):
        return (first if key in first_steps else fu).get(key) or {}

    rows, balken = [], []
    for label, key in stufen:
        n = ses if key is None else (step(key).get("sessions")
                                     or step(key).get("events"))
        if not n:
            continue
        quote = percent(n / ses, 1) if ses else "nicht messbar"
        rows.append((label, num_de(n), quote))
        balken.append((label, n, quote))
    out = charts.step_bars(
        balken, "Der Kaufweg, je Stufe der Anteil aller Sitzungen",
        fmt=num_de, quote_kopf="Anteil aller Sitzungen") + numbers_block(
        ["Stufe", "Sitzungen", "Anteil aller Sitzungen"], rows,
        zeitraum=ga4_caption(period_de(ga4), view, bool(first_steps)))
    out += ("<p>Jede Zeile zählt die Sitzungen, in denen dieser Schritt "
            "mindestens einmal vorkam. Die Stufen sind deshalb keine feste "
            "Reihenfolge: wer mit einem gespeicherten Warenkorb zurückkommt "
            "oder über einen Link direkt in den Warenkorb springt, erscheint "
            "dort, ohne vorher etwas hineingelegt zu haben. Darum kann eine "
            "spätere Zeile größer sein als eine frühere.</p>")
    # Die eine Quote, die auch im offenen Trichter traegt: zwei Stufen, die
    # tatsaechlich aufeinander folgen muessen.
    an, ab = step("view_item").get("sessions"), step("add_to_cart").get("sessions")
    if an and ab:
        out += (f"<p>Die eine Strecke, die zwingend aufeinander folgt, ist "
                f"Produkt ansehen und in den Warenkorb legen: von "
                f"{num_de(an)} Sitzungen mit einer Produktansicht legen "
                f"{num_de(ab)} etwas hinein, das sind {percent(ab / an, 1)}.</p>")

    devices, purchases_from = ga4_purchase_rows(view, "devices", "device")
    dev = sorted(devices, key=lambda d: d.get("sessions") or 0, reverse=True)
    if dev:
        # Dieselbe Falle wie bei den Einstiegsseiten: ohne Käufe in der
        # Antwort ergab `(d.get("transactions") or 0) / sessions` eine
        # Conversion von 0,00 Prozent, während die Umsatzspalte daneben
        # gefüllt war. Die Käufe
        # stehen seit dem 11.09.2026 unter `purchases`; ein `transactions` aus
        # älteren Snapshots enthält Refunds und wird nicht gelesen.
        # Zählt der Kauf doppelt und fehlen die Zahlen des ersten Absenders,
        # bleibt die Spalte und sagt "nicht messbar": Analytics hat Käufe
        # geliefert, sie sind nur nicht zu gebrauchen.
        hat_best = (purchases_from == "not_measurable"
                    or any(d.get("purchases") is not None for d in dev))
        header = ["Gerät", "Sitzungen", "Umsatz"] + (["Conversion Rate"]
                                                   if hat_best else [])
        unit = currency_suffix(ga4, "ga4.json")
        rows = []
        for d in dev:
            z = [DEVICE.get(d.get("device"), d.get("device") or ""),
                 num_de(d.get("sessions")),
                 "nicht messbar" if purchases_from == "not_measurable"
                 else num_de(d.get("purchase_revenue"), 0, unit)]
            if hat_best:
                z.append(percent(d["purchases"] / d["sessions"], 2)
                         if d.get("sessions") and d.get("purchases") is not None
                         else "nicht messbar")
            rows.append(tuple(z))
        out += ('<p class="eyebrow eyebrow--line">'
                + ga4_caption("Nach Gerät", view, purchases_from == "first_sender") + "</p>"
                + table(header, rows))
        if not hat_best:
            out += ("<p>Analytics liefert je Gerät keine Bestellungen, deshalb "
                    "steht hier keine Conversion Rate. Ab dem nächsten Lauf "
                    "kommt sie dazu.</p>")
    ab = (shop or {}).get("abandoned_checkouts") or {}
    if ab.get("count"):
        out += (f'<p>Im Shop liegen {num_de(ab["count"])} abgebrochene Kassenvorgänge '
                f'über {num_de(ab.get("total_value"), 0, " €")}. Das ist der Betrag, '
                "der bereits in der Kasse stand und nicht bezahlt wurde.</p>")
    return out


def sec_seo(run: Run) -> str:
    gsc, rank = run.snap("gsc.json"), run.snap("dfs-rankings.json")
    kw, comp = run.snap("dfs-keywords.json"), run.snap("dfs-competitors.json")
    if not (gsc or rank):
        return _missing(run, "gsc", "Die Suchsichtbarkeit")
    rows = []
    if gsc:
        t = gsc.get("totals") or {}
        rows += [
            ("Klicks aus der Google-Suche", num_de(t.get("clicks")), "gemessen"),
            ("Impressionen", num_de(t.get("impressions")),
             "wie oft der Shop in den Ergebnissen erschien"),
            ("Klickrate", percent(t.get("ctr"), 2), "Klicks je Impression"),
            ("Durchschnittliche Position", num_de(t.get("position"), 1),
             "über alle Suchanfragen"),
        ]
    if rank:
        rs = rank.get("summary") or {}
        rows += [
            ("Keywords mit Ranking", num_de(rs.get("ranked_keywords_total")),
             "Begriffe, für die der Shop in den Top 100 steht"),
            ("Davon in den Top 10", num_de(rs.get("top_10")),
             f"und {num_de(rs.get('top_3'))} in den Top 3"),
            ("Geschätzter Traffic-Wert", num_de(rs.get("etv"), 0),
             "Besuche pro Monat, aus den Rankings hochgerechnet"),
        ]
    zt = period_de(gsc) if gsc else "Momentaufnahme des Laufs"
    out = numbers_block(["Kennzahl", "Wert", "Bezug"], rows, zeitraum=zt)
    if gsc:
        tq = sorted(gsc.get("top_queries") or [],
                    key=lambda q: q.get("clicks") or 0, reverse=True)[:12]
        out += ('<p class="eyebrow eyebrow--line">Die stärksten Suchanfragen</p>'
                + table(["Suchanfrage", "Klicks", "Impressionen", "Position"],
                          [(q.get("query") or "", num_de(q.get("clicks")),
                            num_de(q.get("impressions")), num_de(q.get("position"), 1))
                           for q in tq]))
    if rank:
        knapp = [k for k in (rank.get("top_keywords") or [])
                 if 11 <= (k.get("position") or 999) <= 20]
        knapp.sort(key=lambda k: -(k.get("search_volume") or 0))
        if knapp:
            out += ('<p class="eyebrow eyebrow--line">Knapp vor Seite eins</p>'
                    + table(["Suchbegriff", "Position", "Suchvolumen"],
                              [(k.get("keyword") or "", num_de(k.get("position")),
                                num_de(k.get("search_volume"))) for k in knapp[:12]])
                    + f"<p>{num_de(len(knapp))} Begriffe stehen auf Position 11 bis 20. "
                      "Das ist die zweite Ergebnisseite, auf der praktisch niemand "
                      "klickt, und zugleich die kürzeste Strecke zu zusätzlichen "
                      "Besuchern.</p>")
    if comp:
        gaps = sorted(comp.get("keyword_gaps") or [],
                      key=lambda g: -(g.get("search_volume") or 0))[:12]
        if gaps:
            out += ('<p class="eyebrow eyebrow--line">Themen ohne eigene Seite</p>'
                    + table(["Suchbegriff", "Suchvolumen", "Bester Wettbewerber"],
                              [(g.get("keyword") or "", num_de(g.get("search_volume")),
                                str(g.get("competitor") or g.get("domain") or ""))
                               for g in gaps]))
    if kw and not comp:
        ks = kw.get("summary") or {}
        out += (f"<p>Für {num_de(ks.get('keywords_returned'))} geprüfte Begriffe liegt "
                f"ein Suchvolumen von {num_de(ks.get('search_volume_total'))} Abfragen "
                "pro Monat vor.</p>")
    return out


def sec_geo(run: Run) -> str:
    geo = run.snap("geo.json")
    if not geo:
        return _missing(run, "geo", "Die Sichtbarkeit in AI-Antworten")
    alle = geo.get("queries") or []
    q = [x for x in alle if x.get("brand_mentioned") is not None]
    rows = []
    for p in sorted({x.get("platform") for x in alle if x.get("platform")}):
        part = [x for x in q if x.get("platform") == p]
        if not part:
            # Eine Plattform, die gar nicht geantwortet hat, faellt sonst
            # lautlos aus der Tabelle, und der Leser haelt drei Plattformen
            # fuer zwei. Der Grund steht in der Zeile.
            reason = next((x.get("evidence") or "" for x in alle
                          if x.get("platform") == p), "")
            rows.append((PLATFORM.get(p, p), "nicht erhoben", "nicht erhoben",
                           _short_reason(reason)))
            continue
        erw = sum(1 for x in part if x.get("brand_mentioned"))
        zit = sum(1 for x in part if x.get("domain_cited"))
        rows.append((PLATFORM.get(p, p), f"{erw} von {len(part)}",
                       f"{zit} von {len(part)}", f"{len(part)} Abfragen geprüft"))
    out = numbers_block(["Plattform", "Marke erwähnt", "Eigene Seite als Quelle",
                       "Bezug"], rows,
                      zeitraum=f"Abfrage am {date_de(geo.get('fetched_at') or '')}")
    for gruppe, title in (("brand", "Abfragen mit dem Markennamen"),
                          ("category", "Abfragen ohne Markennamen")):
        part = [x for x in q if x.get("group") == gruppe]
        part = [dict(x, platform=PLATFORM.get(x.get("platform"), x.get("platform")))
                for x in part]
        if not part:
            continue
        out += (f'<p class="eyebrow eyebrow--line">{title}</p>'
                + table(["Abfrage", "Plattform", "Marke erwähnt", "Eigene Seite als Quelle"],
                          [(x.get("query") or "", x.get("platform") or "",
                            "ja" if x.get("brand_mentioned") else "nein",
                            "ja" if x.get("domain_cited") else "nein")
                           for x in part]))
    cr = geo.get("crawlers") or {}
    if cr:
        # `check-geo` schreibt je Bot {status, rule}, nie ein Feld `allowed`.
        # Der Builder las bis 07.09.2026 `allowed` und trug deshalb fuer jeden
        # der acht Bots "nein" ein, obwohl keiner blockiert war: die Tabelle
        # behauptete das Gegenteil des Befunds zwei Absaetze darunter.
        gesperrt = [n for n, v in cr.items()
                    if "disallow" in str(v.get("rule", "")).lower()
                    and "kein disallow" not in str(v.get("rule", "")).lower()]
        out += ('<p class="eyebrow eyebrow--line">Zugang der AI-Crawler</p>'
                + table(["Crawler", "Darf lesen", "Regel in der robots.txt"],
                          [(n, "nein" if n in gesperrt else "ja",
                            str(v.get("rule") or v.get("status") or ""))
                           for n, v in cr.items()])
                + ("<p>Die robots.txt ist die Datei, mit der ein Shop "
                   "Suchmaschinen und AI-Systemen sagt, welche Seiten sie "
                   "abrufen dürfen. "
                   + (f"{num_de(len(gesperrt))} der {num_de(len(cr))} geprüften "
                      "AI-Crawler sind dort ausgesperrt."
                      if gesperrt else
                      f"Alle {num_de(len(cr))} geprüften AI-Crawler dürfen den Shop "
                      "lesen, keiner ist ausgesperrt.")
                   + "</p>"))
    # llms.txt ist eine eigene Aussage und keine Fussnote der Crawler-Tabelle.
    if geo.get("llms_txt"):
        out += ('<p>Eine <span class="mono">llms.txt</span> liegt vor. In dieser '
                "Datei beschreibt ein Shop den AI-Systemen, worum es auf seinen "
                "Seiten geht. Shopify legt sie automatisch an; ob sie etwas über "
                "diese Marke sagt oder nur den Standardtext trägt, steht in den "
                "Befunden.</p>")
    else:
        out += ('<p>Eine <span class="mono">llms.txt</span> liegt nicht vor. In '
                "dieser Datei beschreibt ein Shop den AI-Systemen, worum es auf "
                "seinen Seiten geht.</p>")
    return out


def sec_tech(run: Run) -> str:
    cwv, crawl = run.snap("cwv.json"), run.snap("crawl.json")
    if not (cwv or crawl):
        return _missing(run, "cwv", "Die Technik")
    out = ""
    if cwv:
        rows = []
        for p in cwv.get("pages") or []:
            fd = p.get("field_data") or {}
            lab = p.get("lab") or {}
            rows.append((p.get("page_type") or "", num_de(fd.get("lcp_ms"), 0, " ms"),
                           num_de(fd.get("inp_ms"), 0, " ms"), num_de(fd.get("cls"), 3),
                           num_de((lab.get("performance_score") or 0) * 100)))
        out += numbers_block(
            ["Seitentyp", "Ladezeit (LCP)", "Reaktion (INP)", "Layout (CLS)",
             "Laborwert"], rows,
            zeitraum=f"28 Tage Felddaten, abgerufen am {date_de(cwv.get('fetched_at') or '')}")
        out += ("<p>Ladezeit und Reaktion stammen aus echten Nutzungsdaten von "
                "Chrome, der Laborwert aus einer einzelnen Messung unter "
                "festen Bedingungen. Google zählt eine Ladezeit bis 2.500 "
                "Millisekunden als gut, eine Reaktion bis 200 Millisekunden.</p>")
    if crawl:
        s = crawl.get("summary") or {}
        rows = [
            ("Geprüfte Seiten", num_de(s.get("url_count")), "eigener Durchgang durch den Shop"),
            ("Nicht indexierbar", percent(s.get("share_not_indexable")),
             "von Google ausgeschlossen, per robots, noindex oder Canonical"),
            ("Ohne Meta-Beschreibung", percent(s.get("share_without_description")),
             "der Text unter dem Titel im Suchergebnis"),
            ("Mehrere H1-Überschriften", num_de(s.get("pages_with_multiple_h1")), "Seiten"),
            ("Bilder ohne Alt-Text", num_de(s.get("images_without_alt")),
             "Alt-Text beschreibt das Bild für Suchmaschinen und Screenreader"),
            ("Längste Weiterleitungskette", num_de(s.get("longest_redirect_chain")),
             "Sprünge bis zur Zielseite"),
            ("Tiefste Seite", num_de(s.get("max_click_depth")),
             "Klicks von der Startseite entfernt"),
        ]
        codes = s.get("status_code_distribution") or {}
        if codes:
            rows.append(("Statuscodes", ", ".join(f"{k}: {num_de(v)}"
                                                    for k, v in sorted(codes.items())),
                           "200 heißt geliefert, 3xx weitergeleitet, 4xx nicht gefunden"))
        out += ('<p class="eyebrow eyebrow--line">Der eigene Durchgang</p>'
                + table(["Angabe", "Wert", "Bezug"], rows))
    return out


def sec_catalogue(run: Run) -> str:
    cat = run.snap("catalog.json")
    if not cat:
        return _missing(run, "catalogue", "Der Katalog")
    s = cat.get("summary") or {}
    g = s.get("products_total") or 1
    rows = [
        ("Produkte im Katalog", num_de(s.get("products_total")),
         f"davon {num_de(s.get('products_active'))} aktiv"),
        ("Ohne Suchmaschinen-Titel", num_de(s.get("products_without_seo_title")),
         percent(s.get("products_without_seo_title", 0) / g)),
        ("Ohne Suchmaschinen-Beschreibung", num_de(s.get("products_without_seo_description")),
         percent(s.get("products_without_seo_description", 0) / g)),
        ("Ohne Produkttext", num_de(s.get("products_without_description")),
         percent(s.get("products_without_description", 0) / g)),
        ("Ohne Bild", num_de(s.get("products_without_image")),
         percent(s.get("products_without_image", 0) / g)),
        ("Mit Bildern ohne Alt-Text", num_de(s.get("products_with_missing_alt")),
         f"{percent(s.get('share_images_with_alt'))} aller "
         f"{num_de(s.get('images_total'))} Bilder haben einen"),
        ("Produkttext, mittlere Länge", num_de(s.get("description_length_p50"), 0, " Zeichen"),
         f"kürzestes Zehntel unter {num_de(s.get('description_length_p10'))}, "
         f"längstes über {num_de(s.get('description_length_p90'))}"),
        ("Varianten ohne Artikelnummer", num_de(s.get("variants_without_sku")),
         f"von {num_de(s.get('variants_total'))}"),
        ("Varianten ohne Einkaufspreis", num_de(s.get("variants_without_cost")),
         "ohne ihn lässt sich keine Marge rechnen"),
        ("Kategorien ohne Beschreibung", num_de(s.get("collections_without_description")),
         f"von {num_de(s.get('collections_total'))}"),
    ]
    return numbers_block(["Angabe", "Wert", "Bezug"], rows,
                       zeitraum=f"Stichtag des Laufs, {date_de(run.run_id)}")


def sec_competition(run: Run) -> str:
    comp, bl = run.snap("dfs-competitors.json"), run.snap("dfs-backlinks.json")
    rank = run.snap("dfs-rankings.json")
    if not (comp or bl):
        return _missing(run, "competitors", "Der Wettbewerb")
    out = ""
    # Der Sichtbarkeitsvergleich steht zuerst: er beantwortet die Frage, die
    # der Leser hat ("wie weit ist der Abstand"). Die Domain-Liste aus der
    # Ueberschneidung beantwortet nur, wer ueberhaupt konkurriert.
    if rank:
        sov = rank.get("share_of_voice") or []
        eigen = (run.config or {}).get("domain", "")
        if sov:
            total = sum(x.get("etv") or 0 for x in sov) or 1
            out += numbers_block(
                ["Domain", "Keywords mit Ranking", "Geschätzte Besuche pro Monat",
                 "Anteil an der Gruppe"],
                [((x.get("domain") or "") + (" (eigener Shop)"
                   if (x.get("domain") or "") in eigen else ""),
                  num_de(x.get("ranked_keywords")), num_de(x.get("etv"), 0),
                  percent((x.get("etv") or 0) / total))
                 for x in sorted(sov, key=lambda x: -(x.get("etv") or 0))],
                zeitraum=f"Abfrage am {date_de(rank.get('pulled_at') or '')}")
            out += ("<p>Die geschätzten Besuche rechnet DataForSEO aus Position "
                    "und Suchvolumen der rankenden Begriffe hoch. Sie sind kein "
                    "gemessener Traffic, sondern ein Größenvergleich zwischen "
                    "den Domains dieser Gruppe.</p>")
    if comp:
        # DataForSEO liefert je Wettbewerber avg_position, median_position,
        # rating, etv, keywords_count und visibility. Der Builder las bis
        # 07.09.2026 `intersections` und `keywords`, also zwei Felder, die es
        # in der Antwort nie gab: die Tabelle trug in zwei von vier Spalten
        # "nicht erhoben".
        wb = sorted((comp.get("competitors") or []),
                    key=lambda w: -(w.get("keywords_count") or 0))[:12]
        out += ('<p class="eyebrow eyebrow--line">Wer über dieselben Suchbegriffe '
                "gefunden wird</p>"
                + table(["Domain", "Gemeinsame Suchbegriffe",
                           "Mittlere Position", "Plattform"],
                          [(w.get("domain") or "", num_de(w.get("keywords_count")),
                            num_de(w.get("median_position") or w.get("avg_position"), 1),
                            "ja" if w.get("is_platform") else "nein") for w in wb]))
        seeds = (comp.get("summary") or {}).get("seed_keywords") or []
        if seeds:
            out += ("<p>Diese Domains sind nicht vorgegeben, sondern aus der "
                    "Überschneidung in den Suchergebnissen bestimmt: Ausgangspunkt "
                    f"waren die Suchbegriffe {', '.join(seeds[:6])}. Die Spalte "
                    "Plattform trennt Marktplätze und Portale von Shops, die "
                    "dasselbe Sortiment verkaufen.</p>")
    if bl:
        s = bl.get("summary") or {}
        out += ('<p class="eyebrow eyebrow--line">Das eigene Linkprofil</p>'
                + table(["Angabe", "Wert", "Bezug"], [
                    ("Verweisende Domains", num_de(s.get("referring_main_domains")),
                     "verschiedene Websites, die verlinken"),
                    ("Links insgesamt", num_de(s.get("backlinks")), ""),
                    ("Defekte Links", num_de(s.get("broken_backlinks")),
                     f"auf {num_de(s.get('broken_pages'))} nicht mehr erreichbare Seiten"),
                    ("Domain-Rang", num_de(s.get("rank")),
                     "Skala von 0 bis 1.000, wie DataForSEO die Stärke einschätzt"),
                ]))
    return out


def ads_totals(ads: dict, months=None) -> dict:
    """Kosten, Klicks, Umsatz und ROAS aus der Monatsreihe von ads.json.

    pull-ads schreibt keine Summen, nur `by_month`. Bis zum 15.09.2026 las
    sec_sea ein Feld `totals`, das kein Pull schreibt, und auf jedem Snapshot
    stand in allen vier Zeilen "nicht erhoben". Die Summe entsteht hier und
    nicht im Pull, weil nur der Report das Auswertungsfenster kennt: im Pull
    ginge sie über die volle Historie samt angebrochenem Monat.

    `months` sind die Monatsschlüssel des Fensters, ohne sie zählt jeder Monat
    des Snapshots. Der ROAS ist Umsatz durch Kosten über den ganzen Zeitraum,
    nie der Mittelwert der Monatswerte, sonst wöge ein Monat mit 100 Kosten so
    viel wie einer mit 10.000. Ohne Kosten gibt es keinen ROAS, also None
    statt 0, wie im Pull.
    """
    rows = [m for m in ads.get("by_month") or []
            if months is None or m.get("month") in months]
    if not rows:
        # Ohne einen Monat im Zeitraum lässt sich nicht unterscheiden, ob das
        # Konto pausiert war oder der Snapshot den Zeitraum gar nicht abdeckt.
        # Eine 0 wäre im zweiten Fall eine falsche Zahl, "nicht erhoben" ist
        # höchstens eine fehlende, und die meldet der Build als tote Spalte.
        return dict.fromkeys(("cost", "clicks", "conversions_value", "roas"))
    cost = sum(m["cost"] for m in rows)
    value = sum(m["conversions_value"] for m in rows)
    return {"cost": cost, "clicks": sum(m["clicks"] for m in rows),
            "conversions_value": value, "roas": value / cost if cost else None}


def sec_sea(run: Run) -> str:
    sh, ads = run.snap("dfs-shopping.json"), run.snap("ads.json")
    if not (sh or ads):
        return _missing(run, "ads", "Die bezahlte Suche")
    out = ""
    if ads:
        f = run.fenster
        t = ads_totals(ads, f["jetzt"]["monate"] if f else None)
        unit = currency_suffix(ads, "ads.json")
        # Die Kennzahl heißt ROAS, wie in skills/audit/SKILL.md unter "Wie eine
        # Kennzahl heißt". Bis zum 13.09.2026 stand hier "Rückfluss je Euro",
        # und das nannte eine Währung, die das Konto nicht haben muss.
        out += numbers_block(["Kennzahl", "Wert", "Bezug"], [
            ("Kosten", num_de(t.get("cost"), 0, unit), ""),
            ("Klicks", num_de(t.get("clicks")), ""),
            ("Umsatz", num_de(t.get("conversions_value"), 0, unit), ""),
            ("ROAS", num_de(t.get("roas"), 2, " x"),
             "Umsatz geteilt durch Kosten"),
        ], zeitraum=f["label"] if f else period_de(ads))
    if sh:
        s = sh.get("summary") or {}
        out += ('<p class="eyebrow eyebrow--line">Google Shopping</p>'
                + table(["Angabe", "Wert", "Bezug"], [
                    ("Geprüfte Suchbegriffe", num_de(s.get("keywords_checked")), ""),
                    ("Angebote insgesamt", num_de(s.get("offers_total")),
                     "aller Anbieter zu diesen Begriffen"),
                    ("Davon eigene", num_de(s.get("own_offers")),
                     "Treffer auf die eigene Domain"),
                    ("Davon Wettbewerber", num_de(s.get("competitor_offers")), ""),
                ]))
        for note in sh.get("notes") or []:
            out += f'<p class="evidence">{esc(note)}</p>'
    return out


#: Quellen, die in diesem Ausbaustand des Plugins gar nicht Teil eines Audits
#: sind. Sie sind keine Luecke im Shop und keine Luecke in diesem Lauf: sie
#: waren nie im Umfang. Am 07.09.2026 standen sie im Kundendokument mit dem
#: Grund "Pull noch nicht gebaut (Stufe 3)", also mit dem Roadmap-Stand
#: unseres eigenen Werkzeugs. Yves dazu: *"Was soll das mit 'Pull noch nicht
#: gebaut'?"* Der Leser hat Fragen zu seinem Shop, keine zu unserem Ausbau.
OUT_OF_SCOPE = {"esp", "meta", "reviews", "cwv_lab", "measures"}


def sec_gaps(run: Run) -> str:
    """Was gefehlt hat, und welche Frage dadurch offen bleibt.

    Hier steht ausschliesslich, was im Umfang dieses Audits lag und trotzdem
    nichts geliefert hat: ein fehlender Zugang, eine Schnittstelle, die
    abgelehnt hat, eine Historie, die kuerzer ist als gedacht. Der Wert liegt
    in der letzten Spalte: "GSC abgeschnitten" sagt einem Leser nichts, "die
    Entwicklung vor Juni 2025 bleibt offen" sagt ihm, was er durch einen
    Zugang gewinnt.
    """
    rows = []
    for key, st in sorted((run.state or {}).get("sources", {}).items()):
        if st.get("status") == "done" or key in OUT_OF_SCOPE:
            continue
        rows.append((source_label(key, run),
                       {"skipped": "nicht erhoben", "failed": "fehlgeschlagen"}
                       .get(st.get("status"), st.get("status") or ""),
                       _reason_readable(st.get("reason") or "")))
    tab = table(["Quelle", "Status", "Grund"], rows,
                  empty="Jede Quelle im Umfang dieses Audits hat geliefert.",
                  leerspalten_ok=("Status",))
    shop = run.snap("shopify.json")
    notes = (shop or {}).get("notes") or {}
    if notes:
        tab += ('<p class="eyebrow eyebrow--line">Einschränkungen innerhalb '
                "gelieferter Quellen</p>"
                + table(["Angabe", "Einschränkung"],
                          [(_field_readable(k), _reason_readable(v))
                           for k, v in notes.items()]))
    return tab


#: Wofuer ein Vermerk im Shopify-Snapshot steht, in Kundensprache.
FIELD_READABLE = {
    "order_history": "Bestellhistorie", "by_month": "Monatsreihe",
    "top_products": "Umsatz je Produkt", "orders_by_source": "Bestellquelle",
    "customer_type": "Neu- und Bestandskunden",
    "top_collections": "Umsatz je Kategorie",
    "abandoned_checkouts": "Abgebrochene Kassenvorgänge",
    "availability": "Verfügbarkeit", "session_funnel": "Kaufweg im Shop",
    "site_search": "Suche im Shop",
}


def _field_readable(key: str) -> str:
    return FIELD_READABLE.get(key, str(key).replace("_", " "))


def _reason_readable(text: str) -> str:
    """Den Wortlaut einer Schnittstelle in einen Satz uebersetzen.

    Die Rohvermerke tragen Feldnamen und API-Meldungen ("ShopifyQL meldet
    'Column Not Found' fuer customer_type"). Die gehoeren in die Belegzeile
    eines Befunds, nicht in eine Tabelle, die der Kunde liest.
    """
    t = " ".join(str(text or "").split())
    for muster, ersatz in (
        ("Pull noch nicht gebaut", "nicht Teil dieses Audits"),
        ("Column Not Found", "Der Shop liefert diese Auswertung nicht"),
        ("read_all_orders", "Die Bestellhistorie ist ohne erweiterten Zugang "
                            "auf 60 Tage begrenzt"),
    ):
        if muster in t:
            return ersatz
    return t


def sec_sources(run: Run) -> str:
    """Woher jede Zahl stammt, mit Umfang und Stand."""
    umfang = {}
    for name, key in (("shopify.json", "shopify"), ("ga4.json", "ga4"),
                      ("gsc.json", "gsc")):
        d = run.snap(name)
        if d and d.get("period"):
            umfang[key] = period_de(d)
    # ShopifyQL liefert auch fuer Zeitraeume ohne Daten eine Zeile je Monat,
    # der Zeitraum beginnt also bei der Abfragegrenze, nicht beim ersten
    # Umsatz. Im Dokument steht der erste Monat mit Umsatz.
    shop = run.snap("shopify.json")
    months = [m.get("month") for m in ((shop or {}).get("by_month") or [])
              if (m.get("total_sales") or 0) > 0]
    if months:
        umfang["shopify"] = f"{min(months)} bis {max(months)}"
    cat = run.snap("catalog.json")
    if cat:
        umfang["catalogue"] = (f"{num_de((cat.get('summary') or {}).get('products_total'))} "
                               "Produkte, Momentaufnahme")
    crawl = run.snap("crawl.json")
    if crawl:
        umfang["crawl"] = (f"{num_de((crawl.get('summary') or {}).get('url_count'))} "
                           "Seiten, Momentaufnahme")
    rows = []
    for key, st in sorted((run.state or {}).get("sources", {}).items()):
        if st.get("status") != "done" or key in OUT_OF_SCOPE:
            continue
        rows.append((source_label(key, run), umfang.get(key, "Momentaufnahme"),
                       date_de(st.get("last_pulled") or run.run_id)))
    # Was der Lauf uns an Abfragen gekostet hat, steht im Ledger und geht den
    # Kunden nichts an. Am 07.09.2026 stand es im Dokument.
    return numbers_block(["Quelle", "Umfang", "Stand"], rows,
                       zeitraum=f"Erhoben am {date_de(run.run_id)}")


#: Woran eine Pflichtseite im Crawl erkennbar ist. Mehrsprachig, weil ein Shop
#: mit zweitem Markt seine Rechtstexte auch dort führen muss und die englische
#: Fassung sonst als fehlend gezählt würde. Ein Treffer ist ein Hinweis, kein
#: Beweis: ob die Seite inhaltlich trägt, entscheidet ein Anwalt, und ob ein
#: Käufer sie findet, entscheidet der Screenshot. Beides steht im Befund des
#: Subagenten, hier steht nur, was der Crawl gesehen hat.
MANDATORY_PAGES = (
    ("Impressum", ("impressum", "imprint", "legal-notice")),
    ("Widerruf", ("widerruf", "cancellation", "right-of-withdrawal")),
    ("AGB", ("agb", "terms", "conditions")),
    ("Datenschutz", ("datenschutz", "privacy")),
    ("Versand", ("versand", "shipping", "lieferung", "delivery")),
    ("Kontakt", ("kontakt", "contact")),
)


def sec_trust(run: Run) -> str:
    """Was der Crawl an Pflichtseiten gesehen hat, plus der Rechtsvorbehalt.

    Die Sektion rechnet keine Kennzahl. Sie stellt die eine Tabelle, die sich
    maschinell belegen lässt, und überlässt alles Weitere den Befunden des
    Subagenten: ob die Seite aus dem Footer erreichbar ist, ob sie die üblichen
    Bestandteile nennt, ob die Datenschutzerklärung die geladenen Fremddienste
    aufführt.
    """
    crawl = run.snap("crawl.json")
    if not crawl:
        return _missing(run, "crawl", "Die Pflichtangaben")
    pages = crawl.get("pages") or []

    # **Ein gekappter Crawl kann nichts über Abwesenheit sagen.** Erreicht die
    # Zahl der erfassten Seiten genau das Budget, hat der Crawler aufgehört,
    # bevor er fertig war, und eine nicht gefundene Seite kann schlicht
    # jenseits der Grenze liegen. Genau das war im ersten echten Lauf der Fall:
    # das Budget war ausgeschöpft, gut die Hälfte der Sitemap blieb
    # unbesucht, und Impressum, AGB und Widerruf lagen nicht
    # in den erfassten Seiten. "Nicht gefunden" hätte dort wie "gibt es
    # nicht" gelesen, und das wäre eine Behauptung über den Shop gewesen, die
    # der Lauf nicht belegen kann.
    budget = (run.config or {}).get("crawl_max_urls")
    erfasst = (crawl.get("summary") or {}).get("url_count") or 0
    gekappt = bool(budget) and erfasst >= budget
    fehlt_text = ("nicht in den erfassten Seiten" if gekappt
                  else "im Crawl nicht gefunden")

    rows = []
    for label, fragmente in MANDATORY_PAGES:
        treffer = [p for p in pages
                   if any(f in (p.get("url") or "").lower() for f in fragmente)]
        erreichbar = [p for p in treffer if p.get("status") == 200]
        if not treffer:
            rows.append((label, fehlt_text, "-"))
        elif erreichbar:
            url = erreichbar[0].get("url") or ""
            rows.append((label, "gefunden", url))
        else:
            code = treffer[0].get("status")
            rows.append((label, f"gefunden, antwortet mit {code}",
                           treffer[0].get("url") or ""))
    out = table(["Pflichtangabe", "Im Crawl", "Adresse"], rows)
    if gekappt:
        out += (f'<p class="evidence">Der Crawl hat {num_de(erfasst)} Adressen '
                'erfasst und damit sein Budget ausgeschöpft. Was hier nicht '
                'steht, wurde nicht besucht. Dass es die Seite nicht gibt, ist '
                'damit nicht gesagt. Für eine belastbare Aussage über fehlende '
                'Pflichtseiten muss der Crawl die Sitemap vollständig '
                'durchlaufen.</p>')
    # Der Vorbehalt steht in der Sektion selbst, nicht in einer Fußnote. Ein
    # Leser, der hier einen Mangel sieht, soll im selben Blick lesen, dass das
    # eine Feststellung ist und kein Rechtsurteil.
    out += ('<p class="evidence">Diese Übersicht sagt, welche Seiten der Crawl '
            'gefunden hat und mit welchem Status sie antworten. Sie ist keine '
            'juristische Prüfung: ob ein Rechtstext inhaltlich trägt, '
            'entscheidet eine Anwältin oder ein Anwalt. Wo unten ein Mangel '
            'steht, ist er als Feststellung gemeint und sollte anwaltlich '
            'geprüft werden.</p>')
    return out


SECTIONS = {"shop": sec_shop, "measurement": sec_measurement,
             "commerce": sec_commerce, "traffic": sec_traffic,
             "conversion": sec_conversion, "trust": sec_trust,
             "seo": sec_seo, "geo": sec_geo,
             "tech": sec_tech, "catalogue": sec_catalogue,
             "competition": sec_competition, "sea": sec_sea,
             "gaps": sec_gaps, "method": sec_method, "sources": sec_sources}

#: Die Abschnitte hinter den Fachsektionen. Sie stehen nicht in
#: SECTION_TITLES, weil sie keine Befunde tragen; ohne diese Tabelle fiel die
#: Web-Navigation auf "99 method" zurueck, also auf den Schluessel im Code.
SECTION_APPENDIX = {
    "measures": (13, "Maßnahmen"),
    "gaps": (14, "Lücken in der Datenlage"),
    "method": (15, "Wie der PTAI E-Com Score gerechnet wird"),
    "sources": (16, "Quellen"),
}


#: Welche Befund-Datei unter welche Sektion gehaengt wird.
FINDINGS_BY_SECTION = {v: k for k, v in SECTION_BY_FILE.items()}


# ------------------------------------------------------------- Sitzungstext

TEMPLATE_HINTS = {
    "cover_headline": ("Die Cover-Headline. Ist workos:voice installiert, läuft "
                       "sie durch deren Pitch-Gate. Handelt vom Leser und von "
                       "dem, was er danach kann, nie vom Dokument und nie von "
                       "einem Mangel. Ohne Schlusspunkt: den roten Punkt setzt "
                       "das Template."),
    "intro": ("Der Einstieg, vier Saetze, Ergebnis zuerst: (1) der staerkste "
              "Befund als Aussage ueber den Shop, mit seiner Zahl, (2) der "
              "Mechanismus dahinter, (3) erst jetzt der Umfang, als Beleg, "
              "(4) eine Handlung, die der Leser ohne den Rest des Dokuments "
              "treffen kann. Nie mit dem Umfang der Arbeit anfangen. "
              "Prueffrage fuer Satz 4: koennte er unter jedem beliebigen "
              "Report stehen? Dann ist er keiner. HTML mit <p>-Absaetzen."),
    "summary_what": "Gegenstand und Grundgesamtheit: welcher Shop, welcher Stichtag, welche Bereiche.",
    "summary_why": "Der Mechanismus, der die Baseline noetig macht, nicht der Ablauf des Audits.",
    "summary_status": "Die drei bis vier tragenden Zahlen aus der Kennzahlenleiste, als Satz.",
    "summary_problem": "Was aus dem staerksten Befund folgt, in der Sprache des Lesers.",
    "summary_possible": "Der Weg raus, ohne Preis und ohne Ablauf.",
    "takeaways": ("Die fuenf Saetze, die den ganzen Report tragen. Jeder nennt "
                  "eine gemessene Zahl und die Kennung des Befunds dahinter. "
                  "HTML: <ol><li>...</li></ol>."),
    "next_step": ("Der Schlussblock, ein konkreter Ask. Laeuft durch das "
                  "Pitch-Gate. HTML mit <p>-Absaetzen."),
}

TEMPLATE_PROBLEMS = [
    {"value": "<nur die Zahl, hoechstens 12 Zeichen, etwa \"1.000\">",
     "unit": "<der Bezug, klein gesetzt, etwa \"von 3.000\">",
     "label": "<was sie zaehlt, zwei bis vier Woerter>",
     "detail": "<eine Zeile, die sagt was daran das Problem ist>",
     "finding_ref": "<Kennung des Befunds, etwa MES-01>"},
]


def write_template(pfad: Path, run: Run) -> None:
    """Die Textvorlage anlegen, mit den Zahlen des Laufs als Hilfe daneben.

    Der Zweck des `_hinweis`-Blocks: wer die Vorlage fuellt, hat die Zahlen
    sonst nicht vor Augen und schreibt einen Statussatz ohne Beleg.
    """
    kpi = key_figures(run)
    hilfe = {"kennzahlen": {k.strip("_").lower(): v for k, v in kpi.items()
                            if not k.endswith("_NOTE__")},
             "befunde": sorted(finding_index(run)),
             "massnahmen": len(open_measures(run.backlog))}
    doc = {"_hinweis": dict(TEMPLATE_HINTS, section_messages=(
        "Je Sektion ein Satz, der sagt was sie gefunden hat, nicht was sie "
        "enthaelt. Die Ueberschrift bleibt fest, dieser Satz steht darunter. "
        "Vorbild ist das audit-light: 'Den Preis traegt der Absender, nicht "
        "das Leder' statt 'Der Markt'. Mit Zahl, wo eine traegt."), problems=(
        "Die zwei bis vier groessten Probleme als Zahl, nicht als Satz. Die "
        "Zahl IST das Problem: \"1.000 / von 3.000 aktiven Produkten nicht "
        "bestellbar\". Jede Kachel nennt den Befund, aus dem sie stammt; "
        "eine Zahl auf Seite eins ohne Herkunft kann der Leser nicht "
        "nachschlagen.")),
        "_zahlen_dieses_laufs": hilfe}
    doc.update({k: "" for k in TEXT_FIELDS})
    doc[PROBLEM_FIELD] = TEMPLATE_PROBLEMS
    doc[KEY_MESSAGE] = {k: "" for k in SECTIONS
                        if k not in WITHOUT_KEY_MESSAGE}
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def text_laden(pfad: Path) -> dict:
    doc = json.loads(pfad.read_text(encoding="utf-8"))
    fehlt = [k for k in TEXT_FIELDS if not (doc.get(k) or "").strip()]
    if fehlt:
        raise SystemExit(f"In {pfad} fehlen noch: {', '.join(fehlt)}")
    aussagen = doc.get(KEY_MESSAGE) or {}
    fehlend = [k for k in SECTIONS if k not in WITHOUT_KEY_MESSAGE
               and not str(aussagen.get(k) or "").strip()]
    if fehlend:
        raise SystemExit(
            f"In {pfad} fehlt unter {KEY_MESSAGE!r} die Kernaussage für: "
            f"{', '.join(fehlend)}. Ein Satz je Sektion, der sagt was sie "
            "gefunden hat, nicht was sie enthält.")
    prob = doc.get(PROBLEM_FIELD) or []
    if not 2 <= len(prob) <= 4:
        raise SystemExit(
            f"In {pfad} braucht {PROBLEM_FIELD!r} zwei bis vier Eintraege, "
            f"gefunden: {len(prob)}. Das sind die groessten Probleme als Zahl, "
            "nicht als Satz.")
    for i, x in enumerate(prob, 1):
        fehlt = [f for f in ("value", "label", "detail", "finding_ref")
                 if not str(x.get(f) or "").strip()]
        if fehlt:
            raise SystemExit(f"Problem {i} in {pfad}: {', '.join(fehlt)} fehlt")
        # `value` ist eine kurze Zahl, keine Ueberschrift. Der Bezug gehoert in
        # `unit` und wird kleiner gesetzt. "31 von 1.480" als `value` bricht im
        # Display-Schnitt mitten in der Zahl um; genau dieser Fehler steht
        # schon in der audit-light-Skill.
        if len(str(x["value"])) > 12:
            raise SystemExit(
                f"Problem {i} in {pfad}: value {x['value']!r} ist zu lang. "
                "Die Zahl gehoert in `value`, der Bezug in `unit` "
                '(value "31", unit "von 1.480").')
    return doc


def problem_tiles(run: Run, text: dict) -> str:
    """Die groessten Probleme als Zahl, nicht als Satz.

    Die Bauform steht seit dem 07.09.2026 fest und kommt aus einem eigenen
    Report, der funktioniert hat: **die Zahl ist das Problem.** "3
    Versandkostenschwellen, gleichzeitig" oder "0 Laender, bei denen die
    Preise uebereinstimmen" sagen in einer Kachel, wofuer ein Absatz drei
    Saetze braucht.

    Welche drei von 91 Befunden das sind, folgt nicht aus den Daten: das
    entscheidet die Sitzung und schreibt es in `report-text.json`. Der Builder
    prueft nur, dass jede Kachel auf einen Befund zeigt, den es gibt. Eine
    Zahl auf der ersten Seite ohne Herkunft ist genau das, was der Leser nicht
    nachschlagen kann.
    """
    idx = finding_index(run)
    kacheln = []
    for x in text.get(PROBLEM_FIELD) or []:
        ref = str(x["finding_ref"]).strip()
        if ref not in idx:
            raise SystemExit(
                f"Problem-Kachel verweist auf {ref!r}, diesen Befund gibt es "
                f"nicht. Vorhanden sind: {', '.join(sorted(idx))}")
        einheit = (f'<span class="unit">{esc(x["unit"])}</span>'
                   if x.get("unit") else "")
        kacheln.append(
            f'<div class="problem"><p class="value">{esc(x["value"])}{einheit}</p>'
            f'<p class="label">{esc(x["label"])}</p>'
            f'<p class="caption">{esc(x["detail"])} '
            f'<span class="ref">Befund {esc(ref)}</span></p></div>')
    return '<div class="problem-grid">' + "".join(kacheln) + "</div>"


# ---------------------------------------------------------------- Bauen

def section_blocks(run: Run, brand: str) -> dict:
    """Je Marker der fertige HTML-Block: Zahlen, dann die Befunde daraus."""
    out = {}
    for key, fn in SECTIONS.items():
        try:
            block = fn(run)
        except Exception as exc:              # noqa: BLE001
            print(f"Sektion {key} nicht gebaut: {exc}", file=sys.stderr)
            block = (f"<p>Dieser Abschnitt konnte nicht gebaut werden. "
                     f"Die Rohdaten liegen im Lauf-Ordner.</p>")
        filename = FINDINGS_BY_SECTION.get(key)
        if filename:
            sc = scores(run)["sektionen"].get(key)
            z = scores(run)["sektion_ziele"].get(key)
            if sc is not None:
                # Als Block mit Balken, nicht als Zeile: bis zum 07.09.2026
                # stand hier "38/100 ZIEL 89" direkt unter der Kernaussage und
                # ging im Lesen unter.
                width = max(0, min(100, sc))
                ziel_pos = max(0, min(100, z or sc))
                block = (
                    '<div class="section-score">'
                    '<p class="label">PTAI E-Com Score</p>'
                    f'<p class="value">{sc}<span class="unit">/100</span>'
                    f'<span class="arrow">{z}</span></p>'
                    f'<div class="scorebar"><span style="width:{width}%"></span>'
                    f'<i style="left:{ziel_pos}%"></i></div>'
                    f'<p class="caption">Heute {sc}, nach Umsetzung der '
                    f'Maßnahmen in diesem Abschnitt {z}. Wie sich der Wert '
                    'errechnet, steht in Abschnitt 14.</p></div>') + block
            block += finding_blocks(run, filename)
        out[key] = block
    out["measures"] = measures_overview(run, brand)
    return out


MONTH = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
         "September", "Oktober", "November", "Dezember")


def content(run: Run, text: dict) -> dict:
    """Alles, was in beide Fassungen geht, einmal gebaut.

    Die Druckfassung und die Web-Fassung teilen sich Zahlen, Befunde,
    Massnahmen und Quellen; getrennt sind nur Navigation und Satz. Zwei
    Builder waeren zwei Wahrheiten, und die erste Zahl, die nur in einer von
    beiden korrigiert wird, faellt niemandem auf.
    """
    brand = (run.config or {}).get("brand") or "der Shop"
    year, month, tag = run.run_id[:4], int(run.run_id[5:7]), run.run_id[8:10]
    values = {
        "__BRAND__": esc(brand),
        "__RUN_LABEL__": f"Stand {MONTH[month - 1]} {year}",
        "__GENERATED_DATE__": f"{tag}.{month:02d}.{year}",
        "__FINDINGS_OVERVIEW__": findings_overview(run),
        "__PROBLEMS__": problem_tiles(run, text),
        "__SCORES__": score_leiste(run),
    }
    values.update(key_figures(run))
    values.update({f"__{k.upper()}__": text[k] for k in TEXT_FIELDS})
    # Der rote Schlusspunkt steht im Template, nicht im Text. Wer die Vorlage
    # fuellt, schreibt ihn trotzdem mit, weil er ihn im fertigen Dokument
    # gesehen hat; das Ergebnis waren am 07.09.2026 zwei Punkte nebeneinander.
    values["__COVER_HEADLINE__"] = re.sub(
        r'(\s*<span class="dot">\.</span>|\.)\s*$', "",
        values["__COVER_HEADLINE__"].strip())
    sek = section_blocks(run, brand)
    # Die Kernaussage steht vor den Zahlen der Sektion, nicht danach.
    for key, satz in (text.get(KEY_MESSAGE) or {}).items():
        if key in sek and str(satz or "").strip():
            sek[key] = f'<p class="section-message">{satz}</p>' + sek[key]
    return {"brand": brand, "werte": values, "sektionen": sek}


def build(run: Run, text: dict, template: Path, assets: Path,
          inh: dict | None = None) -> str:
    inh = inh or content(run, text)
    brand = inh["brand"]
    html_text = template.read_text(encoding="utf-8")

    # Der BAUKASTEN ist Bauanleitung fuer diese Datei, kein Inhalt. Er enthaelt
    # selbst Kommentare, deshalb endet er an seiner eigenen Schlusszeile: ein
    # nicht-gieriges .*? braeche am ersten inneren "-->" ab und liesse den Rest
    # als sichtbaren Text stehen. Genau das ist am 07.09.2026 im PDF gelandet.
    html_text = re.sub(r"<!-- ===+ BAUKASTEN.*?^=+ -->\n?", "", html_text,
                       flags=re.S | re.M)

    ersetzungen = dict(inh["werte"], **{
        "__CSS_PATH__": str(assets / "report.css"),
        "__LOGO_PATH__": str(assets / "logo.svg"),
        "__LOGO_REVERSED_PATH__": str(assets / "logo-reversed.svg"),
    })
    for marker, value in ersetzungen.items():
        html_text = html_text.replace(marker, str(value))
    for key, block in inh["sektionen"].items():
        html_text = html_text.replace(f"<!-- SECTION:{key} -->", block)

    # Den Schluss füllt nicht diese Schleife: `closing.apply` setzt ihn zuletzt
    # ein, die Schlussseite aus PTAI_CLOSING_FILE oder den neutralen Schluss
    # (Entscheidung 15.09.2026). Er kommt nach Prüfung und Lesbarkeit, weil die
    # Datei des Betreibers ungelesen übernommen wird und kein Text dieses Audits ist.
    offen = sorted((set(re.findall(r"__[A-Z_]+__", html_text)) - {closing.PLACEHOLDER})
                   | {m for m in re.findall(r"<!-- SECTION:(\w+) -->", html_text)})
    if offen:
        raise SystemExit("Im fertigen Dokument stehen noch Platzhalter: "
                         + ", ".join(offen))
    _report_readability(html_text, text)
    return closing.apply(html_text, run.ws)


def _report_readability(html_text: str, text: dict) -> None:
    """Den Fliesstext messen und melden, wo er aus dem Band faellt.

    Kein Abbruch: eine Lesbarkeitszahl ist ein Signal, kein Fehler. Der Sinn
    ist der Regressionstest. Wenn der Einstieg eines Laufs deutlich schwerer
    liest als der des letzten, soll das jemand sehen, bevor das Dokument
    rausgeht.
    """
    for name, raw, sorte in (
            ("Einstieg", text.get("intro"), "einstieg"),
            ("Fließtext des Dokuments", readability.text_aus_html(html_text),
             "fliesstext")):
        inhalt_text = re.sub(r"<[^>]+>", " ", str(raw or ""))
        for message in readability.check(inhalt_text, sorte):
            print(f"Lesbarkeit, {name}: {message}", file=sys.stderr)
    k = readability.metrics(readability.text_aus_html(html_text))
    if k:
        print(f"Lesbarkeit gemessen: Wiener Sachtextformel {k['wstf']}, "
              f"LIX {k['lix']}, mittlere Satzlänge {k['satzlaenge']} Wörter "
              f"über {num_de(k['woerter'])} Wörter Fließtext.", file=sys.stderr)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", default=".")
    p.add_argument("--run-id", required=True)
    p.add_argument("--text", help="report-text.json der Sitzung")
    p.add_argument("--out", help="Zieldatei, Vorgabe ist audit.html im Lauf-Ordner")
    p.add_argument("--no-web", action="store_true",
                   help="nur die Druckfassung bauen, ohne audit-web.html")
    p.add_argument("--pdf", action="store_true",
                   help="direkt nach A4-PDF rendern, braucht Chrome")
    a = p.parse_args(argv)

    ws = Path(a.workspace).resolve()
    run = Run(ws, a.run_id)
    if not run.state:
        raise SystemExit(f"Kein Lauf {a.run_id} unter {ws}/reporting/runs/")

    textpfad = Path(a.text) if a.text else run.run / "report-text.json"
    if not textpfad.exists():
        write_template(textpfad, run)
        print(f"Textvorlage geschrieben: {textpfad}\n"
              f"Die neun Felder füllen, dann erneut aufrufen.")
        return 2
    text = text_laden(textpfad)

    hier = Path(__file__).resolve().parent.parent.parent
    # Einmal rechnen, beide Fassungen daraus. Sonst laufen Zahlen und Befunde
    # zweimal durch dieselbe Ableitung, und ein Unterschied zwischen PDF und
    # Web-Fassung faellt niemandem auf.
    inh = content(run, text)
    html_text = build(run, text, hier / "skills" / "audit" / "templates" / "audit.html",
                      hier / "assets" / "brand", inh=inh)
    goal = Path(a.out) if a.out else run.run / "audit.html"
    goal.write_text(html_text, encoding="utf-8")
    print(f"Geschrieben: {goal}")

    # **Die Web-Fassung entsteht im selben Aufruf.** Sie lag bis zum 09.09.2026
    # in einem eigenen Kommando, und genau das ist passiert, was bei einem
    # Schritt in zwei Aufrufen immer passiert: die Druckfassung wurde gerendert
    # und die Web-Fassung vergessen. Ein Lauf, der ein PDF hat und keine
    # Web-Fassung, sieht fertig aus.
    #
    # Der Import steht hier und nicht oben, weil `report_web` seinerseits
    # dieses Modul importiert; auf Modulebene waere das ein Zirkelschluss.
    if not a.no_web:
        from audit import report_web
        web_ziel = goal.with_name(goal.stem + "-web.html")
        web_ziel.write_text(
            report_web.build(run, text, inh,
                             assets=hier / "assets" / "brand"),
            encoding="utf-8")
        print(f"Geschrieben: {web_ziel}")

    render = hier / "skills" / "report" / "scripts" / "render_pdf.sh"
    pdf_ziel = goal.with_suffix(".pdf")
    if a.pdf:
        import subprocess
        ergebnis = subprocess.run(["bash", str(render), str(goal), str(pdf_ziel)],
                                  capture_output=True, text=True)
        print(ergebnis.stdout.strip() or ergebnis.stderr.strip())
        if ergebnis.returncode:
            return ergebnis.returncode
    else:
        print(f'Rendern: bash {render} "{goal}" "{pdf_ziel}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
