<p>
  <a href="https://path-to-ai.com">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="assets/brand/logo-reversed.svg">
      <img src="assets/brand/logo.svg" alt="Path to AI" width="220">
    </picture>
  </a>
</p>

# ptai-ecom-toolkit

**Endlich weißt du, was du mit deinen Shop-Zahlen als Nächstes tun sollst.**

Wenn du für SEO, SEA oder CRM Agenturen bezahlst, bist du pro Disziplin schnell bei mehreren
tausend Euro im Monat. Zurück kommen oft Reports voller Zahlen, und die nächsten Schritte musst du
dir selbst überlegen.

Genau so habe ich es als E-Commerce-Verantwortlicher erlebt. Die Agenturen, mit denen ich
gearbeitet habe, haben Feedback nur auf Nachfrage gegeben und mir nie Maßnahmen mitgegeben.
Deshalb habe ich diesen Audit gebaut: Ich will meinen Kunden das Ergebnis geben, das ich damals
selbst erwartet hätte. Der Audit zieht die echten Daten deines Shops aus Shopify, GA4, Search
Console, Google Ads und der AI-Suche und wertet sie über alle Kanäle hinweg aus.

Danach weißt du, wo dein Shop steht, und hast eine nach Hebel sortierte Liste konkreter
Maßnahmen, jede mit Beleg. Die Maßnahmen gibst du direkt an Claude und setzt sie in deinem Shop um.

Als E-Com-Manager oder Founder ziehst du den Audit für deinen eigenen Shop. Als Investor ziehst du
denselben Audit mit den Zugängen einer Brand aus deinem Portfolio und siehst, wo sie über alle
Kanäle steht und wo ihre größten Hebel liegen. Für einen ersten Blick ohne Zugänge reicht
`audit-light` mit der Shop-URL.

Nutz das Toolkit selbst: Es ist kostenlos, läuft lokal in Claude Code und ist mit zwei Befehlen
installiert (siehe [Installation](#installation)). Melde dich gerne jederzeit bei mir auf
[LinkedIn](https://www.linkedin.com/in/yves-schleich/).

## Was drin ist

Du startest mit dem Setup, ziehst dann den Audit und danach jeden Monat den Report.

### Einrichten

| Skill | Wofür |
|---|---|
| `ptai-ecom:setup` | Du richtest das Toolkit Schritt für Schritt ein: einmal auf deinem Rechner die Schlüssel für Datenquellen wie PageSpeed und DataForSEO, danach für jeden Shop die Zugänge zu Shopify, GA4 und Search Console. Vorher siehst du, was schon funktioniert und was noch fehlt. |

### Audit und Report

| Skill | Wofür |
|---|---|
| `ptai-ecom:audit` | Du ziehst den großen Audit mit den Zugängen des Shops und siehst, wo er über alle Kanäle steht, von Umsatz und Traffic über SEO, AI-Suche und Google Ads bis zu Conversion und Vertrauen. Am Ende hast du eine nach Hebel sortierte Liste konkreter Maßnahmen und ein PDF zum Weitergeben. |
| `ptai-ecom:audit-light` | Du bekommst einen ersten Audit allein aus der Shop-URL, ohne Zugänge, als PDF. Der Light-Audit prüft von außen, ob der Shop bei Google und in der AI-Suche gefunden wird, wie der Kauf abläuft, ob Pflichtangaben und Vertrauenssignale da sind, wie das Sortiment präsentiert ist und wo der Shop im Markt steht. |
| `ptai-ecom:report` | Du bekommst jeden Monat einen Report als PDF mit Umsatz, Traffic, SEO, Ladezeiten und AI-Sichtbarkeit, jeweils im Vergleich zum Vormonat, und mit den Maßnahmen, die daraus folgen. |
| `ptai-ecom:pulse` | Du siehst jede Woche die wichtigsten Kennzahlen im Vergleich zur Vorwoche, mit einem Kommentar nur dort, wo etwas auffällt. |

### Datenquellen

Audit und Report holen ihre Zahlen über diese Skills. Einzeln rufst du eine dieser Skills nur auf, wenn du genau eine Quelle brauchst. Die fünf Skills mit DataForSEO kosten je Abfrage Geld, und in der Config legst du dafür eine Obergrenze fest.

| Skill | Quelle | Was du bekommst |
|---|---|---|
| `ptai-ecom:pull-shopify` | Shopify | Umsatz, Bestellungen, Warenkorbwert, Top-Produkte, Sessions, Bestand, Neu- und Bestandskunden |
| `ptai-ecom:pull-shopify-catalog` | Shopify | wie vollständig deine Produkte gepflegt sind: SEO-Titel und -Beschreibungen, Bilder mit Alt-Text, Preise, Kollektionen |
| `ptai-ecom:pull-shopify-tech` | Shopify und Crawl | welches Theme läuft, welche Tools und Skripte eingebunden sind, Sprachen, Märkte und Zahlungsarten |
| `ptai-ecom:pull-ga4` | Google Analytics 4 | woher deine Besucher kommen, auf welchen Seiten sie landen und wo sie im Kaufprozess abspringen |
| `ptai-ecom:pull-gsc` | Google Search Console | mit welchen Suchbegriffen und Seiten dein Shop bei Google gefunden wird, Tag für Tag, dazu Sitemaps und eine Stichprobe zur Indexierung |
| `ptai-ecom:pull-cwv` | PageSpeed Insights | wie schnell deine wichtigsten Seitentypen für echte Besucher laden (Core Web Vitals), mit dem Verlauf der letzten Wochen |
| `ptai-ecom:pull-ads` | Google Ads | wofür dein Werbebudget ausgegeben wird: Ausgaben, ROAS, verpasste Einblendungen samt Grund und Suchbegriffe, die Geld kosten und nichts verkaufen |
| `ptai-ecom:pull-klaviyo` | Klaviyo | Flows, Kampagnen mit Betreff und Text, Listen, Segmente und Formulare; noch in Erprobung |
| `ptai-ecom:pull-dfs-rankings` | DataForSEO | für welche Suchbegriffe dein Shop rankt und wie sichtbar er gegenüber dem Wettbewerb ist |
| `ptai-ecom:pull-dfs-competitors` | DataForSEO | wer bei Google für deine Kategorie-Begriffe auftaucht, auf Wunsch mit den Begriffen, für die dein stärkster Wettbewerber rankt und du nicht |
| `ptai-ecom:pull-dfs-keywords` | DataForSEO | wie oft nach deinen Produkt- und Kategoriebegriffen gesucht wird, wie umkämpft sie sind und was ein Klick kostet |
| `ptai-ecom:pull-dfs-shopping` | DataForSEO | ob dein Shop bei Google Shopping gelistet ist und zu welchen Preisen der Wettbewerb dort verkauft |
| `ptai-ecom:pull-dfs-backlinks` | DataForSEO | welche Seiten auf deinen Shop verlinken und wie stark und sauber dein Linkprofil im Vergleich zum Wettbewerb ist |
| `ptai-ecom:check-geo` | ChatGPT, Perplexity, Google AI | ob deine Marke in den Antworten der AI-Suchen vorkommt und ob deren Crawler deine Seiten lesen dürfen |

### Prüfungen von außen

Diese Skills brauchen keine Zugänge und sehen deinen Shop so, wie ein Besucher und Google ihn sehen.

| Skill | Wofür |
|---|---|
| `ptai-ecom:crawl-site` | Du siehst, welche Seiten Fehler liefern, weiterleiten oder nicht indexiert werden können, wie tief Seiten in der Navigation liegen und ob strukturierte Daten gepflegt sind. |
| `ptai-ecom:capture-screens` | Du bekommst Screenshots aller Seitentypen auf Desktop und Handy und des Kaufprozesses bis zur Zahlungsauswahl, damit der Zustand vor jeder Änderung am Shop festgehalten ist. |
| `ptai-ecom:lens-purchase-path` | Du siehst, woran ein Kauf scheitern kann, von der Produktseite über den Warenkorb bis zur Zahlungsauswahl, ohne dass eine Bestellung ausgelöst wird. |
| `ptai-ecom:lens-trust` | Du siehst, ob Impressum, Widerruf, AGB, Datenschutz, Preis- und Versandangaben, Bewertungen und Siegel vorhanden und auffindbar sind; eine juristische Prüfung ersetzt die Skill nicht. |
| `ptai-ecom:lens-assortment` | Du siehst, ob Filter, Varianten, Produkttexte, Bilder, Empfehlungen und der Umgang mit ausverkauften Artikeln Besuchern das Finden und Kaufen leicht machen. |

### Im Hintergrund

| Skill | Wofür |
|---|---|
| `ptai-ecom:ecom-language` | Audit, Report und die Analyse-Agents nutzen diese Skill, damit jeder Befund dieselbe Fachsprache spricht und jeder Fachbegriff beim ersten Auftreten erklärt ist. |

Für den großen Audit werten elf Analyse-Agents die Daten aus, jeder für eine Disziplin:
`audit-data-quality` (Messqualität), `audit-commerce` (Umsatz, Warenkorb, Wiederkäufer),
`audit-traffic` (Kanäle und Landingpages), `audit-seo-technical` (technisches SEO),
`audit-seo-content` (SEO-Inhalte), `audit-geo` (AI-Suche), `audit-sea` (Google Ads),
`audit-conversion` (Kaufstrecke und Conversion), `audit-content-brand` (Content und Marke),
`audit-competition` (Wettbewerb) und `audit-trust` (Vertrauen und Pflichtangaben). Der Audit
startet die Agents selbst, einzeln rufst du sie nicht auf.

## Voraussetzungen

- Claude Code mit Plugin-Unterstützung.
- `python3` ab 3.10 mit `google-auth` und `requests` (`pip3 install --user google-auth requests`).
- `jq`, `curl` und `git`.
- Node.js (getestet mit Version 22) für die Render- und Versandskripte von `audit-light`.
- Shopify CLI (`npm install -g @shopify/cli@latest`).
- Ein headless Browser für PDFs und Screenshots: bevorzugt die Headless Shell von Playwright (`npx playwright install chromium-headless-shell`), Google Chrome oder Chromium gehen auch.

## Installation

Technisch heißt das Plugin `ptai-ecom`, danach richten sich die Installation und die Namen der
Skills:

```text
/plugin marketplace add yves-s/ptai-ecom-toolkit
/plugin install ptai-ecom@ptai-ecom
```

Danach stehen die Skills als `/ptai-ecom:setup`, `/ptai-ecom:audit` und so weiter
bereit.

## Setup in zwei Teilen

**Teil 1, einmal je Rechner.** `/ptai-ecom:setup` legt `~/.config/ptai-ecom/.env`
mit den Rechten `600` an und führt durch die Schlüssel des Betreibers:
PageSpeed-Key, DataForSEO, die GEO-Keys und optional das Entwicklertoken für
Google Ads. Dazu kommen sechs Einstellungen, alle optional:

| Einstellung | Vorgabe | Wofür |
|---|---|---|
| `PTAI_ACCOUNTS_ROOT` | `~/ptai-ecom/accounts` | Ordner mit einem Unterordner je Kunde, darin `entity.md`, Screenshots und Deliverables |
| `PTAI_OPERATOR_NAME` | `Dienstleister` | wie der Betreiber im Maßnahmen-Katalog und im Audit heißt; nur ausdrücklich gesetzt zeigt der Schluss von Audit, Monats-Report und `audit-light` die Zeile Unternehmen |
| `PTAI_OPERATOR_CONTACT` | keine | wer beim Betreiber ansprechbar ist, etwa ein Name; Zeile Ansprechpartner im Schluss von Audit, Monats-Report und `audit-light` |
| `PTAI_OPERATOR_EMAIL` | keine | Mailadresse; Zeile E-Mail im Schluss von Audit, Monats-Report und `audit-light` |
| `PTAI_OPERATOR_BOOKING_URL` | keine | Terminlink mit `https://`; Zeile Termin im Schluss von Audit, Monats-Report und `audit-light` |
| `PTAI_CLOSING_FILE` | keine | Pfad zu einer HTML-Datei mit der eigenen Schlussseite; ersetzt in Audit, Monats-Report und `audit-light` den Schluss aus den Zeilen darüber |

Der Schluss zeigt eine Zeile je gesetztem und gültigem Wert, keinen Satz. Ohne
eine einzige gültige Einstellung endet jedes Dokument nur mit der Herkunftszeile.
Wie eine eigene Schlussseite gebaut sein muss, steht unter "Eigene Marke".

**Teil 2, je Kunde.** Im Workspace des Kunden schreibt der Wizard
`reporting/config.json`, legt das Dienstkonto für GA4 und Search Console unter
`secrets/` ab und baut aus `reference/access.md`, Teil B, die Anforderung an den
Kunden: nur die Zugänge, die noch fehlen, als Text zum Verschicken.
`scripts/check_env.sh` prüft Rechner und Workspace ohne Seiteneffekte.

## Einstufung der Quellen

| Stufe | Quelle | Ohne sie fehlt |
|---|---|---|
| Pflicht | Shopify | Handel, Katalog, Conversion und Messung |
| Pflicht | Google Analytics 4 | Traffic, Conversion und Messung, dazu die Datenqualitäts-Analyse, die im Report vorne steht |
| Pflicht | Google Search Console | SEO Suche, dazu die Keyword-Liste für DataForSEO |
| Empfohlen | DataForSEO | SEO-Sichtbarkeit, Wettbewerb und Shopping-Präsenz |
| Empfohlen | PageSpeed-Key | Core Web Vitals, der Block Technik bleibt leer |
| Empfohlen | GEO-Keys | GEO-Sichtbarkeit per API. Es bleibt der Browser-Weg mit Login in jedem Lauf |
| Optional | Google Ads | SEA. Betrifft nur Shops mit Suchanzeigen, und das Token muss Google erst freigeben |

Eine fehlende Quelle bricht keinen Lauf ab: sie erscheint im Dokument als nicht
verfügbar, mit Grund. Jeder bezahlte DataForSEO-Aufruf landet mit Kosten in
`reporting/dfs-ledger.jsonl`.

## Datenablage

```text
reporting/
  config.json                     Marke, IDs, Quellen-Schalter. Keine Secrets.
  data/<run-id>/<source>.json     Snapshots eines Laufs
  runs/<run-id>/                  state.json, source-status.md, findings/, screens.json
  baseline/01/                    baseline.json und baseline.md, blockweise eingefroren
  measures.json, measures.md      Maßnahmen-Backlog über alle Läufe
  dfs-ledger.jsonl                eine Zeile je bezahltem DataForSEO-Aufruf
```

Formeln, Schwellen und Benchmarks stehen in `reference/metrics.md`.

## Was nicht passiert

- **Kein Schreiben in Kundensysteme.** Alle Skills lesen nur.
- **Keine Secrets in Git.** `.env` und `secrets/` sind ignoriert, das Setup prüft das.
- **Keine Datenbank, keine Infrastruktur.** Die Historie liegt als Dateien unter `reporting/`.

## Eigene Marke

PDFs und Reports erscheinen im Erscheinungsbild von Path to AI: Logo, Farben und
Schriften unter `assets/brand/`. Audit, Monats-Report und der Report von
`audit-light` enden mit derselben letzten Seite. Ohne weitere Einstellung zeigt
sie die Kontaktdaten des Betreibers aus den Einstellungen oben, keinen Satz dazu.
Path to AI steht dort nur als Herkunft des Plugins, nicht als Absender
(`scripts/audit/closing.py`, für `audit-light`
`scripts/report/sales/report-pdf-full.mjs`). Wer eine eigene Marke will, tauscht
Logo und `assets/brand/report.css` aus.

Eine eigene Schlussseite liegt außerhalb des Plugins, als eine HTML-Datei, auf
die `PTAI_CLOSING_FILE` zeigt. Das Plugin setzt ihren Inhalt unverändert als
letzte Seite ein, in der Web-Fassung des Audits als Blatt mittig unter dem
Inhalt. Die Datei hält:

- genau ein `<section>`-Element auf oberster Ebene, darin optional ein `<style>`-Element,
- nur Selektoren unter der eigenen Klasse dieses Elements,
- alle Bilder und Schriften als `data:`-URIs,
- eine volle A4-Seite im Hochformat: `break-before: page; width: 210mm; height: 297mm; box-sizing: border-box`,
- keine der Zeichenfolgen `<!-- CLOSING:start -->`, `<!-- CLOSING:end -->` und `__CLOSING__`: damit markiert das Plugin den Schluss im Dokument, und Audit und Monats-Report verweigern eine Seite, die sie enthält.

Fehlt die Datei, ist sie nicht lesbar oder leer, endet das Dokument mit dem
Schluss aus den Kontaktzeilen, und eine Zeile auf stderr nennt den Grund.

## Tests

`bash scripts/run_tests.sh` startet die Python- und die JavaScript-Suite. Kein
Test geht ins Netz.

## Lizenz

MIT, siehe `LICENSE`. Ausgenommen sind der Name Path to AI und das Logo. Die
Schriften stehen unter der SIL Open Font License 1.1, die Lizenztexte liegen in
`assets/brand/fonts/LICENSES/`.
