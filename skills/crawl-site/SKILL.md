---
name: crawl-site
description: Vollständigen Site-Crawl über sitemap.xml und interne Links ziehen (Statuscodes, Weiterleitungsketten, Titles, Descriptions, H1, Canonicals, hreflang, robots.txt, interne Verlinkung und Klicktiefe, Wortzahl, strukturierte Daten, Bilder, eingebundene Fremdskripte) und als Snapshot ablegen. Nutzen, wenn der Audit oder ein monatlicher Report frische Crawl-Daten braucht, oder wenn der Nutzer explizit einen Site-Crawl für eine Domain will. Liest reporting/config.json im Kunden-Workspace.
---

# crawl-site: vollständigen Site-Crawl ziehen

Crawlt eine Domain über den aufgelösten Sitemap-Baum und die Breitensuche über interne
Links: Statuscode, vollständige Weiterleitungskette und Ladezeit je URL, dazu die
SEO-Kopfdaten aus `parse_page` (Title, Description, Canonical, hreflang, H1, Bilder,
strukturierte Daten, interne Links, eingebundene Skript-Quellen) und die Klicktiefe
ab der Startseite. Wird vom
Audit- und Report-Lauf aufgerufen, funktioniert aber auch solo.

**Kadenz: monatlich (Spec Abschnitt 3).** Ein Crawl ist teuer (bis zu `--max-urls`
Seitenabrufe mit Verzögerung dazwischen) und ändert sich zwischen zwei Reports selten
genug, dass ein monatlicher Rhythmus reicht. In `reporting/config.json` unter
`cadences.crawl` überschreibbar, ein Lauf mit "alles ziehen"-Schalter zieht ihn auch
außer der Reihe.

## Voraussetzungen

Im Kunden-Workspace (aktuelles Arbeitsverzeichnis):

- `reporting/config.json` mit `domain` (z. B. `https://www.example.com`) und
  `sources.crawl` nicht `false`

Steht `sources.crawl` auf `false`, oder ist `domain` nicht gesetzt: Crawl als
"nicht verfügbar (Grund)" melden und aufhören. Ein Fehlschlag hier legt nie den
Gesamtlauf (Audit oder Report), das gilt für die Quelle als Ganzes genauso wie für
jede einzelne URL innerhalb des Crawls.

## Ablauf

1. `reporting/config.json` lesen: `domain`, `sources.crawl`, und den Umfang über
   `audit.config.crawl_budget(config)`. Der liefert immer ein Paar aus
   `crawl_max_urls` und `crawl_delay_sec`, mit Vorgaben, wenn die Felder fehlen.

   **Den Umfang nie aus dem Prompt nehmen.** Er hängt am Shop und nicht am
   Lauf: wie viele URLs die Sitemap führt, wie viele davon Sprachdubletten
   sind, wie schnell der Shop antwortet. Das ist jedes Mal dieselbe Antwort,
   und wer sie im Prompt mitgibt, gibt sie beim nächsten Lauf entweder wieder
   mit oder fällt still auf die Vorgabe zurück.
2. Ist die Quelle fällig (Kadenz `month`, siehe `audit/run.py`) oder erzwungen, das
   Script aufrufen, Zielordner ist der Daten-Ordner des laufenden Audits oder Reports:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/crawl-site/scripts/crawl.py" \
     --domain <domain> \
     --out "reporting/data/<run-id>" \
     [--max-urls 5000] [--delay 0.2]
   ```

   Ist die Quelle nicht fällig, den letzten vorhandenen `crawl.json`-Snapshot mit
   seinem Datum übernehmen, kein neuer Abruf, kein Delta (Spec Abschnitt 3: "nicht
   fällige Quellen erzeugen kein Delta").
3. Kernzahlen an den Nutzer melden: Anzahl gecrawlter URLs, Statuscode-Verteilung,
   Anteil nicht indexierbar, Anteil ohne Description, maximale Klicktiefe, längste
   Weiterleitungskette. Auffälligkeiten benennen (viele 404, tiefe Klicktiefe,
   KI-Crawler in robots.txt blockiert).

## Snapshot-Schema

Das Script schreibt `<out>/crawl.json`:

```json
{
  "domain": "https://www.example.com",
  "collected_at": "2026-09-05T07:33:05+00:00",
  "robots": {
    "found": true,
    "sitemaps": ["https://www.example.com/sitemap.xml"],
    "disallow_rules": {"*": ["/admin", "/cart"], "GPTBot": ["/"]},
    "ai_crawler_rules": {"GPTBot": "disallow", "ClaudeBot": "allowed"},
    "sitemap_errors": [{"sitemap": "...", "reason": "..."}]
  },
  "summary": {
    "url_count": 842,
    "status_code_distribution": {"200": 810, "404": 12, "error": 3},
    "share_not_indexable": 0.02,
    "share_without_description": 0.15,
    "pages_with_multiple_h1": 4,
    "images_without_alt": 37,
    "longest_redirect_chain": 2,
    "max_click_depth": 5,
    "blocked_links": 6,
    "third_party_script_hosts": ["cdn.intelligems.io", "cdn.judge.me", "www.googletagmanager.com"]
  },
  "findings_index": {
    "cap": 25,
    "orphans": {"count": 0, "examples": ["..."]},
    "errors": {"count": 0, "by_status": {"404": 0}, "examples": [{"url", "status"}]},
    "multiple_canonicals": {"count": 0, "examples": [{"url", "canonical_count"}]},
    "canonical_mismatch": {"count": 0, "examples": [{"url", "canonical"}]},
    "duplicate_titles": {"count": 0, "groups": [{"title", "count", "examples"}]},
    "deepest": [{"url", "click_depth"}],
    "parameter_urls": {"count": 0, "indexable": 0,
                       "without_consolidating_canonical": 0, "examples": ["..."]},
    "schema_types": {"Product": 0},
    "pages_without_schema": {"count": 0, "examples": ["..."]},
    "path_prefixes": {"/products/": 0},
    "inline_tag_ids": {"G-XXXXXXXXXX": 300, "GTM-XXXXXXX": 300}
  },
  "pages": [
    {
      "url": "https://www.example.com/products/x",
      "status": 200,
      "redirects": [{"url": "...", "status": 301}],
      "end_url": "https://www.example.com/products/x/",
      "load_time_sec": 0.29,
      "click_depth": 2,
      "title": "...", "description": "...", "canonical": "...", "canonical_count": 1,
      "hreflang": {}, "h1": ["..."], "images": {"total": 9, "without_alt": 0, "empty_alt": 0},
      "schema_types": ["Product"], "indexable": true,
      "script_sources": ["//cdn.judge.me/y.js", "/assets/theme.js", "https://cdn.intelligems.io/x.js"],
      "internal_links": ["..."], "word_count": 340
    }
  ]
}
```

**`inline_tag_ids` zählt Container- und Mess-IDs, die im Seitenquelltext
stehen, statt über ein `src`-Attribut geladen zu werden.** Genau die häufigsten
Doppelzähler (Tag Manager, GA4, Ads-Conversion) bauen sich per Inline-Snippet
ein und tauchen deshalb in `script_sources` und in
`summary.third_party_script_hosts` grundsätzlich nicht auf. Ohne diese Zeile
heißt "kein Hinweis auf doppelte Tags" in Wahrheit "nicht messbar". Zwei
GA4-IDs mit ähnlicher Seitenzahl sind der belegte Fall einer doppelten Messung.
Gespeichert werden ausschließlich die IDs, nie Skript-Inhalte.

**`findings_index` ist der Zugang für die Analyse, nicht `pages`.** Die
Seitenliste trägt rund 6,8 KB je gecrawlter Seite, ein Shop mit 2000 Seiten
ergibt 13 MB; kein Analyse-Agent liest das am Stück, und ein abgeschnittener
Ausschnitt erzeugt Befunde über zufällig sichtbare Seiten. Der Index trägt je
Befundklasse die **vollständige** Anzahl und höchstens `cap` Beispiele als
Beleg. Wer mehr braucht, fragt `pages` gezielt mit `jq` ab, immer mit Filter
und Grenze.

Zwei Zahlen je Klasse sind bewusst getrennt: `count` ist die echte Menge,
`examples` ist die gekürzte Belegliste. Ein Befund nennt `count`, nie die
Länge von `examples`.

`robots.ai_crawler_rules` deckt eine feste, im Script gepflegte Liste bekannter
KI-Crawler ab (GPTBot, ClaudeBot, PerplexityBot, Google-Extended, CCBot und weitere);
diese Liste veraltet und wird bei Bedarf nachgezogen. Die Auswertung ist bewusst kein
vollständiger robots.txt-Interpreter nach RFC 9309 (keine Wildcard- oder
Präzedenzregeln), sondern hält die wörtlichen Gruppen und ihre `Disallow`-Zeilen fest.
Gelesen wird robots.txt nur für den Befund, sie steuert den Crawl selbst nicht:
jede interne URL wird unabhängig von `Disallow` abgerufen, weil das eine
Kunden-eigene Domain im Auftrag des Kunden ist und die Baseline sonst Lücken hätte,
die sich nie mehr nachmessen lassen.

**`click_depth` ist die Tiefe der Breitensuche über interne Links ab der Startseite,
nie die Position in der Sitemap.** Eine Seite, die in der Sitemap steht, aber von
keiner gecrawlten Seite aus verlinkt ist, bekommt `click_depth: null`, das ist selbst
ein Befund (verwaiste, aber indexierte Seite).

Ein regulärer 404 oder 500 ist kein `error` in diesem Sinn, sondern selbst der
Befund: der Statuscode steht in `status`, nur ohne die SEO-Kopfdaten aus
`parse_page`, weil es dafür keinen auswertbaren Seiteninhalt gibt. `error`
erscheint nur bei einem echten Netzwerkfehler, einer Redirect-Kette über der
internen Grenze (Redirect-Loop) oder einem Nicht-HTML-Content-Type auf einer
2xx-Antwort.

## Setup-Check

`--check` ruft nur robots.txt und die Sitemap-Wurzel(n) ab und meldet, wie viele
URLs zu erwarten sind, ohne eine einzige Seite zu crawlen. Gedacht für den
Setup-Wizard und Gate A, um vor einem langen Lauf die Größenordnung zu kennen:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/crawl-site/scripts/crawl.py" \
  --domain <domain> --check
```

Exit 0 bei Erfolg, Exit 1 nur wenn keine einzige Sitemap-Wurzel erreichbar war
(Domain vermutlich falsch oder nicht erreichbar).

## Der Lauf meldet sich, alle 20 Sekunden

Das Script schreibt seinen Fortschritt nach stderr, unabhängig davon, wie
schnell der Shop antwortet:

```
Sitemap: 3 Wurzel(n), wird aufgeloest ...
Sitemap: 4200 URLs, 0 Fehler.
Crawl startet: 4200 bekannte URLs, Budget 150 Seiten, Pause 0.3s. Meldung alle 20s.
Crawl: 3 Seiten in 0:20 (9/min), Pause 2.4s, 8 mal gedrosselt, 3 geparkt, noch 147 offen, fertig in rund 16 min
```

**Diese Zeilen sind der einzige Weg, einen langsamen Lauf von einem hängenden
zu unterscheiden.** Wer den Crawl im Hintergrund startet, liest sie und
entscheidet danach; wer ihn ohne sie startet, rät. Am 08.09.2026 lief ein
Crawl drei Stunden ohne eine einzige Zeile, und niemand konnte sagen, ob er
arbeitet. Er tat es, nur sehr langsam.

**Die drei Zahlen, die zählen:**

| Zahl | Was sie sagt | Wann sie ein Problem meldet |
|---|---|---|
| Tempo (`/min`) | wie viele Seiten der Lauf schafft | unter 30/min: der Shop drosselt |
| `Pause` | die aktuelle Wartezeit je Seite | über `--delay`: der Shop drosselt gerade |
| `gedrosselt` | wie oft 429 kam, über den ganzen Lauf | wächst weiter: `--delay` war zu klein |

**Die geschätzte Restzeit rechnet mit dem bisherigen Tempo** und wird deshalb
kürzer, sobald die Drosselung nachlässt. Sie ist eine Größenordnung, keine
Zusage.

## Bot-Erkennung: wenn 429 gar keine Drosselung ist

**Zwei völlig verschiedene Dinge kommen als HTTP 429 an, und der Unterschied
entscheidet über Stunden.** Eine Drosselung sagt "zu schnell", und langsamer
werden hilft. Eine Bot-Challenge sagt "du siehst aus wie ein Skript", und
langsamer werden hilft nie: die Abweisung kommt in Millisekunden zurück, egal
wie lange der Crawl vorher gewartet hat.

**Das Signal ist der Antwort-Header,** nicht der Statuscode. Cloudflare setzt
`Cf-Mitigated`; ein 429 von Cloudflare ohne `Retry-After` ist der zweite Fall,
weil eine echte Drosselung fast immer nennt, wann es wieder geht. Das Script
prüft beides (`bot_challenge()`), zählt solche Seiten getrennt in
`summary.bot_challenge_pages` und wiederholt sie **nicht**: sie erhöhen die
Pause nicht und wandern nicht in den Nachlauf.

**Was die Messung kostet, wenn das fehlt.** Am 08.09.2026 lief ein Crawl drei
Stunden gegen eine Cloudflare-Challenge an, weil beides als 429 ankam. Der
gemessene Unterschied auf demselben Shop, gleiche Minute, gleiche Seiten:

| | vorher (alles als Drosselung) | nachher (Challenge erkannt) |
|---|---|---|
| Tempo | 9 Seiten/min | 65 Seiten/min |
| Pause nach 20 Sekunden | 2,4 s (von 0,3 hochgelaufen) | unverändert 0,5 s |
| Restzeit für 150 Seiten | rund 16 Minuten | unter einer Minute |
| abgewiesene Seiten | als "gedrosselt" gezählt, Grund unbekannt | als Bot abgewiesen, mit Grund |

**Der Weg heraus führt über den Kunden, nicht über den Crawler.** Eine
Bot-Erkennung zu umgehen ist genau das, wogegen sie gebaut ist. Die Ausnahme
für den User-Agent `ptai-audit` steht in `reference/access.md` unter
"Empfohlen" und gehört in die Zugangs-Anforderung, sobald ein Lauf abgewiesene
Seiten meldet.

**Bis dahin ist der Snapshot unvollständig, und das steht drin.** Die
abgewiesenen Seiten liegen mit `bot_challenge` und ihrem Grund in `pages`,
`summary.bot_challenge_pages` zählt sie, und jeder Anteil aus dem Snapshot
bezieht sich auf die messbaren Seiten. Das ist der Unterschied zu vorher, als
sie einfach fehlten.

## Drosselung: wenn der Shop mit 429 antwortet

**429 heißt "später nochmal", nicht "gibt es nicht".** Eine abgewiesene Seite
wird im Hauptdurchgang **genau einmal** wiederholt. Antwortet sie auch dann
nicht, wandert sie in den Nachlauf, und der Hauptdurchgang läuft weiter. Der
Nachlauf holt die geparkten Seiten am Ende in zwei Runden mit der höchsten
Pause; der Shop hatte bis dahin Zeit, sich zu erholen. Was auch dann fehlt,
trägt `"throttled": true` und zählt in `summary.throttled_pages`.

**Zwei Fehler stecken in dieser Mechanik, beide am 08.09.2026 bezahlt:**

1. **Vorher galt eine abgewiesene Antwort als erledigte Seite.** Im ersten
   echten Lauf fehlte dadurch rund ein Drittel aller Seiten im Snapshot. Der
   sah aus wie ein fertiger Crawl, und jeder Anteil darin ("72 Prozent der
   Produktseiten haben mehrere H1") bezog sich in Wahrheit auf die
   verbliebenen zwei Drittel, ohne dass das irgendwo stand.
2. **Der erste Fix wiederholte dreimal je Seite mit einer Pause von
   `delay * 16`.** Bei `--delay 0.6` sind das 9,6 Sekunden, mal drei Versuche
   29 Sekunden für eine einzige Seite, und ein Lauf über 3.000 URLs hätte
   einen Tag gebraucht. Deshalb ist die Pause heute absolut gedeckelt
   (`PAUSE_MAX`, 5 Sekunden) statt an `--delay` gekoppelt, und deshalb hängt
   der Hauptdurchgang nie an einer Seite.

**`--delay` wählen, statt ihn zu erben.** Ein Shop, der drosselt, drosselt ab
der ersten Minute: die Fortschrittszeile zeigt es nach 20 Sekunden. Steigt die
Pause dort schon über den gesetzten `--delay`, den Lauf abbrechen und mit
höherem `--delay` neu starten, statt ihn stundenlang gegen die Bremse fahren
zu lassen. Ein Lauf mit `--delay 1.0`, der durchläuft, ist schneller fertig
als einer mit `--delay 0.2`, der sich hochschaukelt.

**Meldet der Lauf am Ende aufgegebene Seiten, ist der Snapshot
unvollständig**, und `audit.qa` weist das als Warnung aus.

## Fehlerbilder

- `sources.crawl: false` oder `domain` fehlt in der Config: Crawl als "nicht
  verfügbar (Grund)" melden, Rest des Laufs unberührt.
- Eine einzelne URL scheitert (Netzwerkfehler, Timeout, Redirect-Loop): landet als
  Zeile mit `error` in `pages`, beendet nie den Lauf. Das gilt für jede URL, egal
  ob sie aus der Sitemap oder aus einem internen Link stammt.
- Eine einzelne Sitemap im Baum ist kaputt (ungültiges XML, 404 mit
  XML-Content-Type): landet als Eintrag in `robots.sitemap_errors`, die übrigen
  Äste des Sitemap-Baums werden trotzdem aufgelöst. Das war explizit die
  Übergabe aus dem Parsing-Teil: die Sitemap-Auflösung läuft vor der Seitenschleife
  und braucht dieselbe Isolierung wie die Schleife selbst.
- robots.txt fehlt oder ist nicht erreichbar: kein Fehler, der Crawl fällt auf
  `{domain}/sitemap.xml` zurück.
- `--check` findet keine einzige erreichbare Sitemap-Wurzel: Exit 1 mit Grund,
  gedacht als Signal für den Wizard, dass die Domain selbst geprüft werden muss.
- Eigener User-Agent `ptai-audit/1.0`, damit der Kunde und Dritte den Bot erkennen
  können; keine Rücksicht auf `Disallow` beim Abruf selbst (siehe oben, Abschnitt
  Snapshot-Schema).
