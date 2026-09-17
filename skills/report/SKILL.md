---
name: report
description: Monats-Report für den Kunden-Workspace erzeugen; orchestriert alle Quellen-Pulls (Shopify, GA4, Search Console, Core Web Vitals, GEO), vergleicht gegen den Vormonats-Snapshot, schreibt reporting/reports/YYYY-MM-monthly.md und rendert das Kunden-PDF im Path-to-AI-CI. Nutzen bei /ptai-ecom:report oder wenn der Nutzer den Monatsreport, Kundenreport oder das Report-PDF will. Liest reporting/config.json im Kunden-Workspace.
---

# report: Monats-Report mit PDF

Das Herzstück des Plugins: ein Lauf zieht alle angeschlossenen Quellen, schreibt
den Markdown-Report mit sechs Kapiteln und rendert daraus das Kunden-PDF im
Path-to-AI-CI. Nicht angeschlossene oder gescheiterte Quellen blockieren nie:
sie erscheinen im Report als "nicht verfügbar (Grund)", der Rest läuft.

## Voraussetzungen

Arbeitsverzeichnis ist der Kunden-Workspace (dort liegt `reporting/`):

- `reporting/config.json` (legt der Skill `setup` an) mit mindestens einer
  Quelle auf `true` unter `sources`
- Für das PDF: ein headless Browser auf dem Rechner, bevorzugt die Headless
  Shell von Playwright, Chrome oder Chromium gehen auch. Fehlt er, wird der
  Markdown-Report trotzdem geschrieben und der PDF-Schritt als Fehler gemeldet
  (Hinweis auf `/ptai-ecom:setup`), nie der ganze Lauf abgebrochen.

**Fehlt die Config komplett** (typisch: jemand ruft `/ptai-ecom:report` als
Erstes auf): nichts raten, nichts anlegen. In zwei Sätzen sagen, was fehlt und
warum es ohne nicht geht, dann anbieten, das Setup direkt jetzt zu starten
(Skill `setup`). Sagt die Person ja, übernimmt der Wizard; sagt sie nein, hier
aufhören. Keine Sackgassen-Meldung, kein leerer Report.

**Config da, aber keine Quelle liefert** (alle aktiven Quellen scheitern an
fehlenden Secrets oder Auth): keinen Report schreiben, der nur aus "nicht
verfügbar" besteht. Stattdessen die betroffenen Quellen mit Grund auflisten
und dasselbe Angebot machen, das Setup zu starten. Liefert mindestens eine
Quelle echte Zahlen, läuft der Report wie gewohnt und die anderen erscheinen
als "nicht verfügbar (Grund)".

## Ablauf

1. **Config lesen, Berichtsmonat bestimmen.** Default ist der letzte volle
   Monat (Erster bis Letzter des Vormonats von heute). Nennt der Nutzer
   explizit einen Monat, gilt dieser volle Kalendermonat; die Datumsgrenzen
   dann explizit an die Pulls geben (`SINCE`/`UNTIL` bzw. `--start`/`--end`).
2. **Vormonats-Snapshot suchen** (Vergleichsbasis, Semantik unten). Ergebnis:
   entweder ein Vormonats-Ordner je Quelle, oder Erstlauf.
3. **Alle aktiven Quellen nacheinander ziehen:** die Skills `pull-shopify`,
   `pull-ga4`, `pull-gsc`, `pull-cwv`, `check-geo`, jeweils nur bei
   `sources.<quelle>: true`. Den Vergleichsmonat nur live mitziehen lassen
   (`--compare-start/--compare-end` bzw. `comparison`-Teil-Pulls), wenn
   Schritt 2 für die Quelle keinen Vormonats-Snapshot gefunden hat. Jeder
   Fehler bleibt isoliert: die Quelle wird im Report "nicht verfügbar (Grund)",
   die übrigen laufen weiter. Erst wenn alle Quellen ausfallen, gibt es nichts
   zu berichten; dann mit klarer Meldung abbrechen statt ein leeres PDF zu
   bauen.
4. **Vergleichs-Präzedenz: Snapshot schlägt Live.** Existiert ein
   Vormonats-Snapshot, ist er die einzige Vergleichsbasis; `comparison`-Blöcke
   in frisch gezogenen Dateien werden dann ignoriert. Grund: APIs restaten
   Zahlen nachträglich; die damals berichteten Zahlen bleiben die Referenz,
   sonst widerspricht der neue Report dem alten.
5. **Markdown-Report schreiben:** `reporting/reports/YYYY-MM-monthly.md` mit
   den sechs Kapiteln (unten), am Ende der Schluss (Abschnitt "Schluss" unten).
6. **PDF rendern** (Mechanik unten), Ergebnis liegt neben dem Markdown.
7. **Zusammenfassung an den Nutzer:** Kernbefunde (die Executive-Sätze in
   Kurzform), wichtigste Maßnahme, welche Quellen nicht verfügbar waren, Pfade
   zu `.md` und `.pdf`.

Der Lauf liest nur. In Kundensysteme (Shop, GA4, GSC) wird nie geschrieben.

## Vormonats-Snapshot: die Such-Semantik

Vormonat heißt: der Kalendermonat vor dem Berichtsmonat (Berichtsmonat Juli
2026, Vormonat Juni 2026).

- **Period-tragende Quellen** (`shopify.json`, `ga4.json`, `gsc.json`): je
  Datei gilt der jüngste Ordner unter `reporting/data/`, dessen Datei einen
  `period` mit granularity `month` über den vollen Vormonat trägt (start ist
  der Erste, end der Letzte des Vormonats). `-pulse`-Dateien ignorieren, die
  sind nie Vergleichsbasis. Im Normalfall bestimmen alle drei denselben Ordner.
- **Period-lose Quellen** (`cwv.json`, `geo.json`): dieselbe Ordnerwahl
  übernehmen, die die period-tragenden Quellen bestimmt haben (bei
  Abweichungen der jüngste davon). Nie eine eigene Suche nach der jüngsten
  `cwv.json` oder `geo.json`: die könnte aus einem Puls-Tag oder Zwischenlauf
  stammen und gehört zu keinem Monatsstand. Fehlt die Datei im bestimmten
  Ordner, hat die Quelle keinen Vormonats-Vergleich.
- **Kein qualifizierender Ordner für eine Quelle:** Erstlauf für diese Quelle,
  der Pull zieht den Vergleichsmonat live mit (so steht es auch in den
  Pull-Skills selbst).

## Zahlen-Regeln (hart)

- **Jede Zahl im Report stammt aus einem konkreten Snapshot-Feld.** Nichts
  schätzen, nichts erfinden, keine Benchmarks aus dem Modellwissen.
  Branchenvergleiche nur qualitativ und ausdrücklich als Einschätzung
  gekennzeichnet, nie als Zahl.
- Deutsche Formate: `12.480 €`, `3,1 %`, Deltas mit Vorzeichen (`+8,2 %`).
  Sinnvoll runden (Umsatz auf Euro, Conversion Rate auf eine Nachkommastelle),
  keine Schein-Präzision.
- Ist die Vergleichsbasis 0 oder fehlt sie, gibt es kein Prozent-Delta:
  absolute Differenz nennen oder das Delta weglassen. Fehlt der Vergleich für
  eine Quelle ganz, entfällt die Delta-Spalte komplett, keine leeren Zellen.
- **Conversion-Präzedenz:** die berichtete Conversion Rate ist
  `totals.orders` geteilt durch `sessions.sessions`, beides aus
  `shopify.json`. Sessions ebenfalls von dort.

  **Nicht `sessions.conversion_rate` nehmen.** Das Feld zählt nur Bestellungen,
  die Shopify einer Session zuordnen konnte, und liegt dadurch systematisch zu
  tief: im Pilotmonat 0,2 Prozent (4 zugeordnete Bestellungen) gegenüber 0,6
  Prozent tatsächlich (12 Bestellungen auf 2.000 Besuche). Ein Report, der die
  niedrigere Zahl als Conversion Rate ausweist, macht den Shop schlechter, als
  er ist, und die Zahl stimmt in keinem Monat mit den Bestellungen daneben
  überein.

  Weicht `sessions.conversion_rate` stark von der gerechneten Rate ab, ist das
  kein Rechenfehler, sondern ein Befund über die Zuordnung: dann gehört ein
  Satz ins Traffic-Kapitel, wie viele Bestellungen sich keiner Session zuordnen
  lassen. Fehlt `sessions` ganz, kommen Funnel und Conversion aus `ga4.json`
  (`funnel`, Conversion = purchase geteilt durch sessions), und der Report sagt
  dazu, dass GA4 untererfasst. Fehlt beides, ist die Conversion nicht
  berechenbar; genau das steht dann als Satz im Shop-Kapitel, keine Ersatzzahl.

## Kennzahlen-Katalog (verbindlich)

Formeln, Quellfelder, Diagnose-Schwellen und Benchmark-Bänder stehen im Katalog
unter `${CLAUDE_PLUGIN_ROOT}/reference/metrics.md`. Er ist verbindlich: der
Report rechnet keine eigene Formel und setzt keine eigene Schwelle. Steht eine
Kennzahl dort mit einem Parameter (etwa der Mindest-Impressionen für
Striking-Distance-Queries), gilt genau dieser Wert.

- **Benchmarks sind immer Fremdquelle mit Datum,** nie eine eigene Messung. Im
  Report steht die Quelle in Klammern hinter der Einordnung, etwa "(Benchmark:
  karbonanalytics.com, abgerufen 2026-08-11, Fremdquelle)". Eine Benchmark ordnet
  ein und bewertet nicht: "liegt unter dem Median der Shopify-Shops", nicht "zu
  niedrig".
- **Fehlt ein Wert im Katalog, wird nichts geschätzt.** Gibt es für eine
  Kennzahl keine Benchmark, steht der Vergleich zum eigenen Vormonat und sonst
  nichts. Keine Zahl aus dem Modellwissen, auch nicht als grobe Hausnummer.
- Ist eine Diagnose nach Katalog nicht berechenbar (Feld `null`, zu wenige
  Vergleichszeilen, Nenner 0), entfällt ihr Block im Kapitel mit einem Satz
  Begründung, statt mit einer leeren Tabelle dazustehen.

## Fehler-Shapes je Quelle (alle abfangen, nie crashen)

Die Snapshots melden Teilausfälle in definierten Formen. Jede davon sauber
behandeln; ein unerwartetes Shape ist ein Grund für eine Note im Report, nie
für einen Abbruch:

- `shopify.json`: Kern-Felder (`top_products`, `top_collections`, `sessions`,
  `products`, `customer_type` u. a.) können `null` sein, die Begründung steht
  dann in `notes`; die Note im Report in einem Satz wiedergeben statt leerer
  Tabellen. `customer_type` `null` heißt: keine Repeat-Rate, kein Ersatzwert.
  `products` `null` heißt: keine Sortiments-Diagnosen. `total_inventory`
  und `status` je Produkt können `null` sein (Spalte dann leer lassen oder
  weglassen); für das Bestandsrisiko zählt `null` als "Bestand unbekannt", nie
  als unauffällig. `comparison` steht nur beim Erstlauf drin; fehlt er und gibt
  es keinen Vormonats-Snapshot, entfällt das Delta. Genullte Felder innerhalb
  von `comparison` tragen ihren Grund in einem eigenen `notes`-Eintrag dort: das
  betroffene Delta weglassen.
- `ga4.json`: `comparison` fehlt oder ist `{"error": ...}`: Delta weg.
  `channels[].purchases` kann `null` sein (die Property hat die Metrik
  abgelehnt, Grund unter `notes.purchases`): dann entfällt die Spalte
  Conversion Rate in der Kanal-Tabelle komplett, keine leeren Zellen und
  keine 0 als Ersatz. Ein Snapshot von vor dem 11.09.2026 trägt statt
  `purchases` nur `transactions`; darin zählt GA4 Refunds mit, das Feld wird
  nie als Käufe gelesen. `purchase_revenue` steht in `currency`, der Währung
  der Property: ist das nicht die Währung des Shops, kein Umsatzvergleich mit
  Shopify.
- `gsc.json`: `sitemaps` ist eine Liste oder `{"error": ...}`;
  `index_sample`-Einträge können `{"url", "error"}` sein: als "Prüfung
  fehlgeschlagen" je URL ausweisen, nie als "nicht indexiert" werten.
  `comparison` fehlt oder ist `{"error": ...}`: Delta weg.
- `cwv.json`: `pages`-Einträge können `{"url", "error"}` sein (die URL fehlt
  dann mit Grund); `field_data` kann `null` sein, das ist kein Fehler, sondern
  zu wenig CrUX-Traffic: als "keine Feld-Daten (zu wenig Traffic)" ausweisen
  und den Lab-Score trotzdem nutzen.
- `geo.json`: `brand_mentioned`/`domain_cited` können `null` sein (nicht
  prüfbar): nie als `false` zählen, aus allen Quoten herausrechnen und die
  Zeilen getrennt als "nicht prüfbar" ausweisen. Zeilen tragen ein
  `method`-Feld (`api` oder `browser`); nicht angeschlossene Plattformen
  stehen mit `null`/`null` und `evidence` "nicht angeschlossen: kein API-Key".
  `crawlers` ist das Objekt mit acht Schlüsseln oder `{"error": ...}`.
  `llms_txt` ist boolesch. `other_citations` ist immer eine Liste, bei nicht
  prüfbaren Zeilen leer; fehlt das Feld ganz (Snapshot aus einem älteren Lauf),
  entfällt der Share of Voice mit einem Satz, statt aus `evidence` geraten zu
  werden.
- **Ganze Quelle fehlt** (Pull gescheitert, `sources` auf `false`, Datei
  fehlt): das Kapitel bleibt bestehen, mit einem Satz "nicht verfügbar
  (Grund)" statt Zahlen. Kapitel werden nie gestrichen, die Struktur ist jeden
  Monat gleich.

## Die sechs Kapitel

Markdown-Struktur: H1 `<Brand> · Monats-Report <Monat JJJJ>`, je Kapitel ein
H2, gleiche Reihenfolge wie im PDF.

1. **Executive Summary:** zuerst das Zahlenbild, dann wenig Text. Acht
   KPI-Kacheln in zwei Reihen zu vier (`kpi-grid kpi-grid--4`) zeigen den Monat
   auf einen Blick. Wer die Seite anschaut, muss den Monat aus den Kacheln
   verstehen, ohne den Fließtext zu lesen.

   **Vier Kacheln sind gesetzt,** weil sie in jedem Monat und jedem Shop tragen:
   Umsatz, Bestellungen, Warenkorbwert, Sessions. Sie bilden die erste Reihe.

   **Vier Kacheln wählt der Monat.** Sie bilden die zweite Reihe und sollen die
   Kernaussage tragen, typischerweise die Conversion Rate, die Kennzahl mit dem
   größten Sichtbarkeits-Hebel (Suchklicks, GEO Citation Rate) und die eine oder
   zwei Raten, an denen die Hauptmaßnahme hängt (Produktansichtsrate,
   Add-to-Cart-Rate, Repeat-Rate). Was diesen Monat nichts erklärt, kommt nicht
   in die Reihe.

   Regeln, die hart bleiben:
   - Acht Kacheln, keine neunte, keine Kachel ohne Wert.
   - Jede Kachel trägt den Vormonatswert als Caption. Gibt es keinen (erster
     Snapshot einer Quelle), taugt die Kennzahl nicht als Kachel.
   - **Keine Kachel, die eine andere Kachel dupliziert.** "Davon im Shop" neben
     "Bestellungen" ist bei einem reinen Onlineshop dieselbe Zahl zweimal und
     verschenkt einen von acht Plätzen. Solche Aufteilungen nur, wenn sie sich
     im Berichtsmonat tatsächlich unterscheiden.
   - **Kennzahlennamen sind eindeutig belegt.** Steht auf einer Kachel
     "Add-to-Cart-Rate 0,5 %", darf derselbe Name im Report nicht mit 2,6 %
     auftauchen, nur weil dort eine andere Bezugsgröße gemeint ist. Entweder
     dieselbe Zahl, oder der Bezug wird ausgeschrieben ("von den Sessions mit
     Produktansicht").
   - **Raten, die nebeneinander stehen, teilen sich eine Basis.** Zwei
     Funnel-Raten in einer Reihe werden beide auf dieselbe Session-Zahl
     gerechnet, und welche das ist, steht im Fließtext darunter.

   Dazu höchstens drei bis vier kurze Sätze und ein dunkler
   Kernbefund-Callout, der einzige im ganzen Report.

2. **Shop** (aus `shopify.json`, Funnel-Zwischenstufen aus `ga4.json`):
   Umsatz (total_sales, net_sales), Bestellungen, AOV, Sessions und Conversion
   Rate, je mit Delta. Die Conversion Rate wird nach der Präzedenz im Katalog
   aus Bestellungen und Sessions gerechnet; liegt eine Zuordnungslücke vor,
   steht die zugeordnete Quote in einem hellen Callout daneben, mit der
   Erklärung und dem Beleg aus `orders_by_source`.

   **Der Micro-Conversion-Funnel** als eigener Block, ausschließlich
   session-basiert (Katalog, gleichnamiger Abschnitt). Tabelle mit vier Spalten
   in dieser Reihenfolge: Stufe, Sessions Berichtsmonat, Sessions Vormonat,
   Übergangsrate Berichtsmonat. Die Stufen heißen "Sessions gesamt",
   "Produktansicht" und "Add to Cart", also die etablierten Kennzahlennamen und
   keine Umschreibungen. Die schwächste Übergangsrate bekommt `neg`.

   Harte Regeln für diesen Block, alle am Pilot gelernt:
   - **Nie Ereigniszahlen als Menschen ausgeben.** Die Produktansicht-Zeile
     kommt aus GA4 als Metrik `sessions` unter `eventName = view_item`, nie als
     `eventCount`.
   - **Übergangsrate heißt Anteil der vorherigen Stufe.** Wird zusätzlich der
     Bezug auf alle Sessions genannt (etwa für die KPI-Kachel), steht der Bezug
     ausdrücklich dabei.
   - **Alle Zeilen einer Tabelle auf derselben Basis.** GA4-Zeilen gegen
     GA4-Sessions, Shopify-Zeilen gegen Shopify-Sessions. Die jeweils andere
     Zahl gehört in den Fließtext darunter, nicht in dieselbe Spalte.
   - **Keine Zeile wiederholen, die schon in der Kennzahlen-Tabelle darüber
     steht.** Umsatz und Bestellungen gehören nicht in den Funnel, sonst liest
     sich der Block wie eine Dublette und trägt nichts.
   - **Keine Kauf- und keine Checkout-Stufe,** solange die Zuordnung die
     Bestellzahl nicht trifft. Eine Kaufzeile mit 3, während zwei Tabellen
     weiter oben 10 Bestellungen stehen, ist ein Widerspruch im selben Dokument.
     Stattdessen ein Satz, warum die Stufen fehlen, inklusive des Drawers ohne
     eigene URL, wenn `view_cart` fehlt.
   - **Gegenprobe nennen:** die Add-to-Cart-Zahl aus Shopify neben die aus GA4
     stellen. Liegen sie in derselben Größenordnung, ist die Zahl belastbar, und
     genau dieser Satz gehört in den Report. Weichen sie stark ab, ist es ein
     Messproblem und kein Shop-Befund.
   - **Ein Kernbefund-Callout pro Report,** und der steht in der Executive
     Summary. Ein zweiter dunkler Callout im Shop-Kapitel, der dasselbe noch
     einmal sagt, entwertet beide.

   **Abandoned Carts** als kleine Tabelle (Zeitraum, Anzahl,
   Warenwert) plus zwei Sätze: was die Zahl bedeutet, und ob sie relevant ist.
   Auffällige Häufungen an einem Tag als mögliche Tests benennen, mit dem
   Muster als Begründung und ausdrücklich als Vermutung.

   **Top-Produkte** als Tabelle, auf die Top 10 gekappt (Umsatz, Bestellungen,
   Bestand, Status). Steht bei einem Umsatzträger "unbekannt", ist der Pull
   unvollständig: nachfragen statt drucken (Katalog, Bestandsrisiko).

   **Die Repeat-Rate** (Formel im Katalog, aus `customer_type`) als ein Satz mit
   Einordnung gegen das DTC-Band, Benchmark als Fremdquelle mit Datum. Fehlt
   `customer_type`, steht dort der Grund aus `notes`.

   **Die Verfügbarkeit** als eigener Block, immer wenn die Warenkorb-Rate
   auffällig ist: die Quote der bestellbaren Varianten, die Produkte mit Lücken
   als Tabelle (Produkt, bestellbare Größen als "1 von 8"), und der Satz, ob
   Verfügbarkeit die niedrige Warenkorb-Rate erklärt oder eben nicht. **Bestand
   0 nie als Kaufhindernis lesen**, entscheidend ist `availableForSale`. Ein
   negatives Ergebnis wird ausgeschrieben, es schließt die naheliegendste
   Hypothese aus.

   **Die Sortiments-Diagnosen** nach Katalog, aber nur mit Treffern: "Ware ohne
   Umsatz" und "Bestandsrisiko", je als kurze Tabelle, beide auf 10 Zeilen
   gekappt, mit Anzahl und gebundenen Stück über alle Treffer. Ohne Treffer ein
   Satz statt einer leeren Tabelle. Nach Warengruppen schauen: verkauft ein
   Produkt einer Gruppe und die Geschwister nicht, ist das der wertvollste
   Befund des Kapitels und gehört in die Maßnahmen.

3. **Traffic** (aus `ga4.json`): Totals (Sessions, Nutzer, Umsatz),
   Kanal-Tabelle, Top-Landingpages mit Engagement-Rate, dazu zwei, drei Sätze
   zu den auffälligsten Verschiebungen.

   Die Kanal-Tabelle bekommt die Spalte **Conversion Rate** (`purchases`
   geteilt durch `sessions` je Kanal, Formel und Mindestbasis im Katalog).
   Direkt darunter ein Satz zum stärksten und zum schwächsten Kanal, jeweils
   mit der Zahl und der Einordnung gegen die Kanal-Bänder des Katalogs,
   Benchmark als Fremdquelle mit Datum benannt. Kanäle unterhalb der
   Mindestbasis bleiben in der Tabelle, werden aber nicht kommentiert: bei
   wenigen Sessions ist die Rate Zufall, und genau das steht als Halbsatz
   dabei. Ist `purchases` `null` oder fehlt, entfällt die Spalte samt Satz.
4. **SEO** (aus `gsc.json` und `cwv.json`): GSC-Totals (Klicks, Impressionen,
   CTR, Position) mit Delta; Gewinner- und Verlierer-Queries nur, wenn
   Vergleichsdaten existieren (Match über den Query-String); Indexierung:
   Sitemap-Status plus Auffälligkeiten der Index-Stichprobe (alles, was nicht
   indexiert ist, mit URL); Core Web Vitals je URL (LCP, INP, CLS mit
   Kategorie, Lab-Score). GSC-Daten laufen 2 bis 3 Tage nach: liegen zwischen
   Monatsende und heute weniger als 4 Tage, gehört der Hinweis ins Kapitel,
   dass die letzten Tage des Monats noch unvollständig sein können.

   Dazu zwei Blöcke nach Katalog-Definition, beide auf die Top 10 gekappt:

   - **Striking-Distance-Queries** als Tabelle mit Query, Position,
     Impressionen (Einblendungen), Klicks, sortiert nach Impressionen
     absteigend. Ein Satz darunter, wie sie zu lesen ist: das sind Suchbegriffe
     knapp hinter den vorderen Plätzen, bei denen wenige Positionen viele
     Klicks bringen.
   - **CTR-Lücken** als Tabelle mit Query, Position, Impressionen, eigener CTR
     und dem Median der eigenen Queries auf vergleichbarer Position, sortiert
     nach der rechnerischen Klick-Lücke. Der Vergleich läuft ausschließlich
     innerhalb des eigenen Datensatzes; genau das gehört als Satz darunter,
     damit niemand eine Marktzahl hineinliest.

   Sind für eine der beiden Diagnosen zu wenige Queries über der
   Mindest-Impressionsgrenze, entfällt der Block mit einem Satz.
5. **GEO** (aus `geo.json`): je Gruppe (`brand`/`category`) und Plattform, wie
   oft die Brand erwähnt und die Domain zitiert wurde; nicht prüfbare Zeilen
   getrennt ausweisen; Crawler-Matrix mit den blockierten Crawlern beim Namen;
   llms.txt-Status.

   Die **Citation Rate** je Gruppe (Formel im Katalog: zitierte Zeilen geteilt
   durch prüfbare Zeilen) steht als Zahl da, eingeordnet nach den Katalog-Bändern
   (unter 15 % deutliche Lücke, 25 bis 40 % wettbewerbsfähig, über 40 % stark),
   Benchmark als Fremdquelle mit Datum benannt. Dazu der **Share of Voice**: die
   fünf häufigsten fremden Zitat-Domains derselben Queries aus `other_citations`,
   als kurze Tabelle mit Domain und Anzahl der Zeilen, die eigene Domain in
   derselben Rangliste. Ein Satz dazu, wer statt der Brand zitiert wird. Fehlt
   `other_citations` oder ist es überall leer, entfällt der Block mit einem Satz. Veränderung zum Vormonat nur, wenn der Vormonats-Ordner
   eine `geo.json` hat, und nur über Zeilen, die in beiden Monaten prüfbar
   waren **und** mit derselben Methode erhoben wurden (`method`-Feld: gleiche
   Plattform plus gleiche Methode). Hat eine Plattform die Methode gewechselt
   (etwa von `browser` auf `api`), steht das als ein Satz im Kapitel statt
   eines stillen Vergleichs. Steht `geo_method` in der Config auf `off`,
   besteht das Kapitel aus einem Satz: GEO ist bewusst abgeschaltet und lässt
   sich über `/ptai-ecom:setup` aktivieren. Harte Regel: GEO stellt während
   eines Report- oder Puls-Laufs nie Fragen an den Nutzer und öffnet nichts
   unangekündigt; alle Entscheidungen (api/browser/off) stehen in der Config
   (`geo_method`), fehlende Voraussetzungen werden zu `null`-Zeilen oder
   "nicht verfügbar (Grund)".
6. **Maßnahmen:** 3 bis 7 Punkte, priorisiert (1 kommt zuerst). Jede Maßnahme
   hat drei Teile: was tun, Begründung aus den Daten dieses Reports (mit der
   konkreten Zahl), Impact-Einschätzung hoch/mittel/niedrig mit einem Satz,
   warum. Umsatz-Prognosen nur, wenn sie sich aus den Snapshot-Zahlen
   herleiten lassen, und dann mit der Rechnung daneben. Dieses Kapitel
   unterscheidet den Report von Agentur-PDFs: konkret, aus den Daten, machbar.

   Die naheliegendsten Kandidaten sind die Treffer aus Kapitel 4 und 2:
   Striking-Distance-Queries (wenige Positionen bis in die Top 3, Nachfrage
   belegt) und die Sortiments-Diagnosen (Kapital liegt im Regal oder der
   Umsatzträger läuft leer). Beides sind konkrete, abgegrenzte Aufgaben mit
   einer Zahl daneben. Sie sind kein Pflichtprogramm: gibt es in diesem Monat
   Wichtigeres, steht das Wichtigere oben.

**Schluss:** ans Ende des Markdown-Reports eine Trennlinie `---` und darunter
wörtlich die Ausgabe von

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" python3 -m audit.closing report-md .
```

im Workspace aufgerufen. Sie enthält eine Kontaktzeile je gesetztem und
gültigem Wert (Unternehmen, Ansprechpartner, E-Mail, Termin) und immer die
Herkunftszeile, keinen Satz dazu. Nie umformulieren, nie ergänzen, keine
Kontaktdaten von Hand. Der Markdown-Report endet immer so, auch wenn
`PTAI_CLOSING_FILE` gesetzt ist. Das HTML bekommt seinen Schluss erst nach dem
Speichern (unten, Schritt 5), nie den Markdown-Text.

## PDF rendern

1. Template lesen: `${CLAUDE_PLUGIN_ROOT}/skills/report/templates/report.html`.
2. Platzhalter ersetzen, Pfade immer absolut (headless Chrome löst keine
   Plugin-relativen Pfade auf):
   - `__CSS_PATH__`: absoluter Pfad zu
     `${CLAUDE_PLUGIN_ROOT}/assets/brand/report.css`. Immer auf die Plugin-CSS
     zeigen: die Fonts liegen relativ zur CSS-Datei (`fonts/...`), eine
     kopierte CSS ohne ihren `fonts/`-Ordner rendert ohne Fonts.
   - `__LOGO_PATH__`: absoluter Pfad zu
     `${CLAUDE_PLUGIN_ROOT}/assets/brand/logo.svg`.
   - `__BRAND__`, `__PERIOD_LABEL__` (z. B. "Juli 2026"),
     `__GENERATED_DATE__` (z. B. "10.08.2026").
   - `__CLOSING__` bleibt stehen, wie er ist, ebenso die beiden Markierungen
     `CLOSING:start` und `CLOSING:end` um das Schluss-Panel. Den Schluss setzt
     Schritt 5 ein; nichts davon von Hand schreiben.
3. Die sechs `SECTION:`-Kommentare durch das Kapitel-HTML ersetzen, gebaut
   ausschließlich aus den Blöcken im BAUKASTEN-Kommentar des Templates
   (KPI-Zeile, Hero-KPI, Tabelle, Kernbefund dunkel, Hinweis hell, Eyebrow,
   Umbruch-Helfer). Keine eigenen Styles, keine neuen Klassen: nur so sieht
   jeder Monat gleich aus. Zahlenzellen und Zahlen-Spaltenköpfe tragen
   `class="num"`.
4. Den BAUKASTEN-Referenz-Kommentar aus dem gefüllten HTML entfernen (er ist
   Bauanleitung, kein Inhalt), dann das HTML als
   `reporting/reports/YYYY-MM-monthly.html` speichern (bleibt liegen, für
   Re-Render und Fehlersuche).
5. Den Schluss einsetzen, im Workspace:

   ```bash
   PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" python3 -m audit.closing apply reporting/reports/YYYY-MM-monthly.html .
   ```

   Das Script schreibt die Datei um und sagt in einer Zeile, welchen Schluss
   es genommen hat. Ist `PTAI_CLOSING_FILE` gesetzt und lesbar, ersetzt die
   Schlussseite des Betreibers das Schluss-Panel zwischen den Markierungen,
   dieselbe Seite wie im Audit und in `audit-light`; die Markierungen bleiben
   stehen. Sonst wird `__CLOSING__` zum neutralen Schluss: eine Kontaktzeile je
   gesetztem und gültigem Wert des Betreibers und immer die Herkunftszeile,
   keinen Satz dazu. Fehlt die Datei, ist sie nicht lesbar oder leer, steht dazu
   ein Hinweis auf stderr.

   Ein zweiter Aufruf auf derselben Datei richtet keinen Schaden an. Mit
   gesetzter Schlussseite ersetzt er, was zwischen den Markierungen steht, auch
   einen früheren neutralen Schluss oder eine ältere Seite. Ohne sie füllt er
   `__CLOSING__`, solange der Platzhalter da ist; ist er schon ersetzt, bleibt
   die Datei unverändert, und die Zeile sagt, dass nur die Vorlage den neutralen
   Schluss neu baut. Enthält die Schlussseite selbst eine der beiden
   Markierungen oder `__CLOSING__`, bricht das Script mit einer Fehlermeldung
   ab und lässt die Datei, wie sie ist.
6. Rendern:

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/skills/report/scripts/render_pdf.sh" \
     "reporting/reports/YYYY-MM-monthly.html" \
     "reporting/reports/YYYY-MM-monthly.pdf"
   ```

   Das Script findet den Browser selbst, rendert A4 ohne Browser-Kopfzeilen und
   prüft, dass das PDF existiert und über 20 KB groß ist (grober Beleg, dass
   die Fonts eingebettet sind).
7. Das PDF kurz sichtprüfen (öffnen oder lesen): Archivo Black in den Überschriften,
   Logo oben rechts, Tabellen und KPI-Kacheln sauber, Schlussseite am Ende.

**Deliverable-Hinweis:** das Kunden-PDF zusätzlich abzulegen (etwa im
Account-Ordner eines Drive) regeln der Nutzer bzw. die Workspace-Regeln des
Kunden-Repos, nicht dieses Plugin. Der Report meldet nur die Pfade.

## Ton und Sprach-Hygiene

**Ist `workos:report` installiert, lädt der Lauf sie vor dem ersten Satz, für
Tonfall und Prüfungen.** Sie hält die vier Textarten im Report, die vier
Label-Fragen für Überschriften und Spaltenköpfe und die vier Sätze des
Einstiegs. Wo sie dieser Skill widerspricht, gilt diese Skill. Was hier steht,
gilt mit und ohne sie: die Regeln, die nur für diesen Monats-Report gelten und
in keiner allgemeinen Datei stehen können.

Der Report geht an eine Geschäftsführung, nicht an eine Analystin und nicht an
eine Laiin. Das ist der Grat, auf dem der Ton läuft.

**Etablierte Kennzahlen behalten ihren etablierten Namen.** Conversion Rate,
Sessions, Add-to-Cart-Rate, Produktansichtsrate, Engagement-Rate, AOV,
Micro-Conversion-Funnel: das sind die Begriffe, die jede E-Commerce-Person
sofort liest, und sie werden nicht übersetzt. Beim ersten Vorkommen im Kapitel
steht ein Nebensatz dazu, was sie messen, und damit ist es erledigt.

**Nie einen Metriknamen erfinden.** Umschreibungen wie "Wie weit ein Besuch
kommt", "Im Shop angekommen", "Davon mit etwas im Warenkorb" oder
"Warenkorb-Zulage" sind schlechter als der Fachbegriff, nicht besser: sie sind
länger, unpräziser, in keinem anderen Werkzeug wiederzufinden, und sie klingen
nach jemandem, der die Kennzahl selbst nicht kennt. Beim ersten Report ist genau
das passiert und musste dreimal zurückgebaut werden. Gibt es keinen etablierten
Namen, wird die Zeile mit einem vollständigen, sachlichen Substantiv benannt
("Abandoned Carts"), nie mit einem Satzfragment.

**Prosa beschreibt Kennzahlen, sie dramatisiert sie nicht.** "Die
Add-to-Cart-Rate liegt bei 2,6 %" statt "der Shop verliert die Leute zweimal,
bevor es um Geld geht". Jeder Satz, der ohne Zahl auskommt und trotzdem
Dramatik behauptet, wird gestrichen.

**Funnel-Tabellen** tragen die Stufe, die Zahl je Zeitraum und die Übergangsrate
zur vorherigen Stufe, in dieser Reihenfolge. Keine Zeile, die eine Kennzahl aus
einer Tabelle weiter oben wiederholt: eine Funnel-Tabelle, deren erste und letzte
Zeile schon in der Kennzahlen-Tabelle stehen, trägt nichts bei und wird
weggelassen.

Wo eine Tabelle erklärungsbedürftig ist, steht ein Satz darunter, wie sie zu
lesen ist.

Spaltenreihenfolge in allen Vergleichstabellen gleich: Berichtsmonat zuerst,
dann Vormonat, dann Delta. Auch in Query- und Produkttabellen, sonst dreht sich
die Leserichtung mitten im Report.

Mechanik, Wortliste und die Prüfung am Ende kommen aus `workos:report`, falls
installiert. Für diesen Report gilt in jedem Fall: jede Aussage hängt an einer
Zahl aus den Snapshots oder ist als Einschätzung markiert.

## Fehlerbilder

- **Kein Browser:** `render_pdf.sh` bricht mit klarer Meldung ab. Der
  Markdown-Report ist trotzdem fertig und bleibt das Deliverable; dem Nutzer
  den PDF-Schritt als offen melden (Headless Shell von Playwright oder Chrome
  installieren, Script erneut ausführen).
- **PDF unter 20 KB:** fast immer sind `__CSS_PATH__` oder `__LOGO_PATH__`
  nicht durch absolute Pfade ersetzt oder die CSS zeigt auf eine Kopie ohne
  `fonts/`. Pfade prüfen, neu rendern.
- **Einzelne Quelle gescheitert:** Kapitel mit "nicht verfügbar (Grund)"
  füllen, weiterlaufen. Die Gründe stehen in den Fehlerbildern der jeweiligen
  Pull-Skill.
- **Alle Quellen gescheitert:** kein Report. Abbrechen, die Gründe je Quelle
  auflisten und auf `/ptai-ecom:setup` verweisen.
- **Berichtsmonat liegt weiter zurück** (Nachzügler-Lauf): die Pulls mit
  expliziten Datumsgrenzen aufrufen; die Vormonats-Suche bezieht sich dann auf
  den Monat vor dem gewünschten Berichtsmonat, nicht auf den Kalender von
  heute.
