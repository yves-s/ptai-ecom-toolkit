# Kennzahlen-Katalog

Die eine Quelle für Formeln, Quellfelder, Diagnose-Schwellen und
Benchmark-Einordnung dieses Plugins. `report` und `pulse` rechnen nicht selbst
und tragen keine eigenen Grenzwerte: sie schlagen hier nach. Ändert sich eine
Formel, eine Schwelle oder eine Benchmark, ändert sie sich in dieser Datei und
nirgends sonst.

## Zwei harte Regeln

**1. Benchmarks sind externe Einordnung, nie eine Aussage über die Brand.** Eine
Benchmark sagt, wo eine Zahl im Markt ungefähr liegt, und nichts darüber, ob sie
für diesen Shop gut oder schlecht ist. Jede Benchmark-Zeile trägt Quelle und
Abrufdatum. Veraltet eine Quelle, wird sie hier ersetzt, nie in den Skills. In
Report und Puls wird eine Benchmark immer als Fremdquelle mit Datum benannt, nie
als eigene Messung.

**2. Kein Wert in diesem Katalog wird geschätzt oder erfunden.** Was nicht belegt
ist, steht als "keine belastbare Benchmark" drin und bleibt dort stehen, bis es
eine Quelle gibt. Eine fehlende Benchmark ist ein brauchbarer Eintrag, eine
geratene ist ein Fehler.

## Notation

- **Quellfeld** ist der exakte Pfad im Snapshot, geschrieben als
  `datei.json > pfad`. `[]` heißt Liste, `channels[].sessions` also das Feld
  `sessions` jedes Eintrags in `channels`.
- **Nicht berechenbar** heißt: Zähler oder Nenner fehlt oder ist `null`. Dann
  steht im Report genau das, nie eine Ersatzzahl.
- **Auffälligkeits-Schwelle** ist plugin-weit das relative Delta zum
  Vergleichszeitraum von betragsmäßig 20 % oder mehr, plus jeder Fall, in dem
  aktueller Wert oder Vergleichswert auf der Null-Linie liegt. Sie stammt aus
  `skills/pulse/SKILL.md` und gilt für alle Kennzahlen, bei denen unten nichts
  Eigenes steht.

## 1. Shop (shopify.json)

| Kennzahl | Formel | Quellfeld | Diagnose-Schwelle |
|---|---|---|---|
| Umsatz brutto | kommt fertig von Shopify | `shopify.json > totals.total_sales` | Auffälligkeits-Schwelle |
| Umsatz netto | kommt fertig von Shopify | `shopify.json > totals.net_sales` | Auffälligkeits-Schwelle |
| Bestellungen | kommt fertig von Shopify | `shopify.json > totals.orders` | Auffälligkeits-Schwelle |
| Warenkorbwert (AOV) | kommt fertig von Shopify, nie selbst mitteln | `shopify.json > totals.average_order_value` | Auffälligkeits-Schwelle |
| Sessions | kommt fertig von Shopify | `shopify.json > sessions.sessions` | Auffälligkeits-Schwelle |
| Conversion Rate gesamt | `totals.orders / sessions.sessions`, nie `sessions.conversion_rate` | `shopify.json > totals.orders` und `shopify.json > sessions.sessions`, sonst `ga4.json > funnel.purchase` und `ga4.json > funnel.sessions` | Einordnung gegen die Bänder unten |
| Zuordnungslücke Bestellungen | `1 - (sessions.conversion_rate × sessions.sessions) / totals.orders` | `shopify.json > sessions.conversion_rate`, `sessions.sessions`, `totals.orders` | Befund ab 20 % nicht zugeordneter Bestellungen |
| Repeat-Rate | siehe unten | `shopify.json > customer_type[]` | siehe unten |

Die Conversion Rate wird aus Bestellungen und Sessions gerechnet, nie aus
`sessions.conversion_rate` übernommen. Warum, steht direkt darunter unter
Zuordnungslücke. Fehlt `sessions` ganz, kommen die Sessions aus
`ga4.json > totals.sessions`; fehlt beides, ist die Conversion nicht
berechenbar, und genau das steht dann im Report.

**Zähler und Nenner müssen denselben Zeitraum abdecken, sonst gilt die Formel
nicht.** Bei einem Audit über die volle Historie ist das regelmäßig nicht der
Fall: Shopify hält Sessions kürzer vor als Bestellungen, und `totals.orders`
reicht dann Jahre weiter zurück als `sessions.sessions`. Wer die beiden Felder
trotzdem direkt teilt, bekommt eine Rate, die um ein Vielfaches zu hoch liegt,
und friert sie als Nullpunkt ein. Am 06.09.2026 lag der Unterschied beim ersten
echten Lauf beim Doppelten.

Deshalb gilt: den Beginn beider Reihen bestimmen (`by_month[0].month` gegen den
ersten Monat mit Sessions), die Bestellungen über das Überlappungsfenster
summieren und nur dieses Fenster teilen. Das benutzte Fenster gehört als eigener
Wert neben die Rate, nie nur die Zahl.

### Zuordnungslücke Bestellungen

`sessions.conversion_rate` von Shopify zählt nur Bestellungen, die einer Session
zugeordnet werden konnten. Die Differenz zur echten Bestellzahl ist keine
Rundung, sondern eine Messlücke, und gehört als Befund in den Report.

- **Formel:** zugeordnete Bestellungen sind `sessions.conversion_rate ×
  sessions.sessions`, gerundet. Die Lücke ist der Rest zu `totals.orders`.
- **Diagnose-Schwelle:** Befund ab 20 Prozent nicht zugeordneter Bestellungen.
- **Pilot-Beleg:** Juli 2026, Beispielshop: 2.000 Sessions, `conversion_rate`
  0,002, macht 4 zugeordnete Bestellungen bei 12 tatsächlichen. Lücke 67
  Prozent. Dieselbe Größenordnung zeigt GA4 mit 4 von 12 erfassten Käufen, was
  auf eine gemeinsame Ursache in der clientseitigen Erfassung deutet.

### Repeat-Rate

Anteil der Bestellungen, die von wiederkehrenden Kundinnen und Kunden kommen.

- **Formel:** `orders` der Zeile mit `customer_type` gleich `returning`, geteilt
  durch die Summe der `orders` über alle Zeilen in `customer_type`.
- **Quellfeld:** `shopify.json > customer_type[].customer_type` und
  `shopify.json > customer_type[].orders`.
- **Diagnose-Schwelle:** Befund, wenn die Rate unter 25 % liegt (unteres Ende des
  DTC-Bandes unten) oder wenn sie gegenüber dem Vergleichsmonat um mindestens
  10 Prozentpunkte fällt.
- **Nicht berechenbar,** wenn `customer_type` `null` ist oder die Summe der
  `orders` 0 ergibt. Der Grund steht dann in `shopify.json > notes.customer_type`.
- **Nicht jeder Shop hat das Feld.** Am Pilot-Shop existiert `customer_type`
  im `sales`-Schema nicht, ebenso wenig `returning_customer_type`,
  `customer_segment` und `billing_customer_type`; die Repeat-Rate entfällt dort
  ersatzlos und wird nicht aus einem anderen Schema zusammengerechnet. Kommt ein
  dritter Wert zurück (dokumentiert sind `first-time` und `returning`), zählt er
  in den Nenner und nicht in den Zähler.

### Micro-Conversion-Funnel

Wie viele Sessions jede Stufe des Kaufprozesses erreichen. **Ausschließlich
session-basiert**, nie aus Ereigniszahlen. Die Stufen heißen im Report
Produktansicht und Add to Cart, die zugehörigen Raten Produktansichtsrate und
Add-to-Cart-Rate; die Namen werden nicht umschrieben.

- **Produktansichtsrate:** Sessions mit `view_item` geteilt durch alle Sessions.
- **Add-to-Cart-Rate:** je nach Bezug entweder Sessions mit `add_to_cart`
  geteilt durch Sessions mit `view_item` (Übergangsrate, die diagnostische
  Größe) oder geteilt durch alle Sessions (die Kachel-Größe). Welcher Bezug
  gemeint ist, steht immer dabei.
- **Übergangsrate** ist im Report grundsätzlich der Anteil der jeweils
  vorherigen Stufe, so wird ein Funnel gelesen.
- **Keine Benchmark** für beide Raten im Katalog, also nur Vergleich gegen den
  eigenen Vormonat.

- **Quellfeld, Regelfall:** `shopify.json > session_funnel.sessions` und
  `.sessions_with_cart_additions`.
- **Zwischenstufe Produktansicht:** GA4, und zwar die Metrik `sessions` unter
  der Dimension `eventName = view_item`, nicht `eventCount`. Dieselbe Basis für
  jede Zeile einer Tabelle verwenden: GA4-Zeilen gegen GA4-Sessions,
  Shopify-Zeilen gegen Shopify-Sessions. Beide Systeme in einer Spalte zu
  mischen ergibt Quoten, die es nicht gibt.
- **Warum nicht `eventCount`:** eine Person sieht mehrere Produkte an. Am
  Pilot-Shop standen deutlich mehr `view_item`-Ereignisse als Sessions. Wer die
  Ereignisse als Menschen liest, rechnet jede Folgequote falsch.
- **Die beiden unteren Stufen** (`sessions_that_reached_checkout`, zugeordnete
  Käufe) werden **nicht zu Quoten verrechnet.** Sie sind bei kleinen Shops
  inkonsistent: am Pilot-Shop standen in einem Monat mehr Bestellungen als
  erreichte Checkouts und in einem anderen mehr erreichte Checkouts als
  Warenkorb-Sessions. Sie stehen im Snapshot und dürfen im Text genannt
  werden, nie als Prozentzahl.
- **Es gibt keinen Schritt „Warenkorb angesehen“,** wenn der Warenkorb ein
  Drawer ohne eigene Adresse ist: `view_cart` wird dann nie gefeuert. Fehlt das
  Ereignis, ist das kein Messfehler, und eine Abbruchquote im Warenkorb ist
  nicht berechenbar.
- **Gegenprobe ist Pflicht:** die Warenkorb-Zahl aus Shopify gegen die aus GA4
  halten. Liegen sie in derselben Größenordnung, ist die Zahl belastbar; weichen
  sie um mehr als den Faktor zwei ab, gehört das als Messproblem in den Report
  statt als Shop-Befund.

### Abandoned Carts

Im Report heißt die Kennzahl **Abandoned Cart**, das ist der etablierte
Begriff. Das Snapshot-Feld heißt weiter `abandoned_checkouts`, weil es das
Admin-Objekt `abandonedCheckouts` eins zu eins spiegelt; Feldnamen folgen der
API, Anzeigenamen dem Sprachgebrauch. Gemeint ist beides Mal dasselbe: ein
begonnener Checkout ohne Bestellung.

- **Formel:** Anzahl und Summe der `abandoned_checkouts.items` mit
  `completed_at` gleich `null`.
- **Quellfeld:** `shopify.json > abandoned_checkouts`.
- **Diagnose-Schwelle:** Befund, wenn der Warenwert der Abandoned Carts
  mindestens 20 % des Monatsumsatzes erreicht. Darunter wird die Zahl
  genannt, aber nicht zur Maßnahme.
- **Vorsicht bei Ausreißern:** mehrere identische Checkouts am selben Tag sind
  meist interne Tests, keine echte Nachfrage. Am Pilot-Shop lag in einem Monat
  die Mehrheit der Abandoned Carts auf einem Tag, mehrfach dasselbe Produkt. Das
  Muster benennen und die Zahl als Vergleichsbasis relativieren, nie stillschweigend
  als Kundenverhalten verkaufen.

### Verfügbarkeit

Ob die Produkte überhaupt gekauft werden können. Das ist die erste Hypothese
bei einer niedrigen Warenkorb-Rate und muss geprüft werden, bevor eine Maßnahme
darauf zeigt.

- **Formel:** `availability.variants_available` geteilt durch
  `availability.variants_total`, dazu die Produkte mit Lücken aus
  `availability.partially_available` und `availability.fully_unavailable_titles`.
- **Quellfeld:** `shopify.json > availability`.
- **Diagnose-Schwelle:** Befund je Produkt, dessen bestellbare Varianten unter
  der Hälfte aller seiner Varianten liegen. Im Report auf 10 Zeilen gekappt,
  sortiert nach dem kleinsten Anteil zuerst.
- **`total_inventory: 0` ist kein Kaufhindernis.** Entscheidend ist
  `availableForSale`, und die hängt an `inventoryPolicy`: bei `CONTINUE` ist das
  Produkt trotz Bestand 0 bestellbar (Fertigung auf Bestellung). Am Pilot-Shop
  waren fast alle Produkte mit Bestand 0 normal bestellbar und fast alle
  Varianten kaufbar. Wer Bestand 0 als „nicht kaufbar“ liest, schreibt das
  Gegenteil der Wahrheit in den Report.
- **Ein negatives Ergebnis ist ein Ergebnis:** ist die Abdeckung gut, gehört der
  Satz in den Report, dass Verfügbarkeit die niedrige Warenkorb-Rate *nicht*
  erklärt. Das schließt die naheliegendste Hypothese aus und lenkt die Maßnahmen
  auf die richtige Stelle.

### Sortiments-Diagnosen

Beide arbeiten über **alle aktiven Produkte** aus `products[]`, nicht über eine
Stichprobe.

**Ware ohne Umsatz.** Produkt, das aktiv und lieferbar ist, im Berichtszeitraum
aber keine Bestellung hatte.

- **Formel:** Eintrag aus `products[]` mit `status` gleich `ACTIVE` und
  `total_inventory` größer 0, dessen `product_title` in keiner Zeile von
  `top_products[]` vorkommt.
- **Quellfeld:** `shopify.json > products[].status`,
  `shopify.json > products[].total_inventory`,
  `shopify.json > products[].product_title`, gegen
  `shopify.json > top_products[].product_title`.
- **Diagnose-Schwelle:** jeder Treffer ist ein Befund. Im Report auf die 10
  Produkte mit dem höchsten Bestand gekappt, weil dort das meiste Kapital liegt,
  plus Anzahl und Summe der gebundenen Stück über alle Treffer.
- **Voraussetzung:** die Umsatzabfrage (`LIMIT 50` in `pull-shopify`) muss alle
  Produkte mit Umsatz enthalten. Liefert sie genau 50 Zeilen, ist sie
  möglicherweise abgeschnitten und ein Produkt auf Rang 51 zählte fälschlich als
  umsatzlos; dann das Limit erhöhen statt die Diagnose zu drucken.
- **Nach Warengruppen schauen, nicht nur nach Bestand.** Der wertvollste Befund
  entsteht, wenn ein Produkt einer Gruppe verkauft und die Geschwister derselben
  Gruppe nicht: dieselbe Nachfrage ist dann belegt und der Weg zum Artikel fehlt.
  Am Pilot-Shop verkaufte sich das Kinderset-*Set*, während die Einzelteile
  Weste und Hose mit 838 Stück unangetastet lagen.

**Bestandsrisiko.** Umsatzträger, dessen Bestand den nächsten Monat rechnerisch
nicht trägt.

- **Formel:** Eintrag aus `top_products[]`, dessen `total_inventory` kleiner ist
  als die eigenen `orders` im Berichtszeitraum (Reichweite unter einem Monat)
  oder kleiner oder gleich 5 Stück.
- **Quellfeld:** `shopify.json > top_products[].total_inventory` und
  `shopify.json > top_products[].orders`.
- **Diagnose-Schwelle:** jeder Treffer ist ein Befund, sortiert nach `net_sales`
  absteigend, im Report auf 10 gekappt.
- **`total_inventory` `null` ist kein zulässiges Ergebnis mehr.** Findet der
  Titel-Match kein Produkt, wird der Bestand für genau diesen Titel gezielt
  nachgefragt (`pull-shopify`, Schritt Bestand und Verfügbarkeit). Erst wenn
  auch das nichts liefert, steht "Bestand unbekannt" da, getrennt ausgewiesen
  und nie als unauffällig gezählt. Am Pilot-Shop standen im ersten Lauf die
  umsatzstärksten Produkte auf `null`, weil die Bestandsabfrage nur die
  ersten 50 Titel des Alphabets zog.
- **Auf Variantenebene schauen,** wenn ein Umsatzträger knappen Bestand hat: ein
  Produkt mit 3 Stück, die alle in einer Randgröße liegen, ist praktisch
  ausverkauft. Der Fall gehört zusätzlich in die Verfügbarkeits-Diagnose.

## 2. Traffic (ga4.json)

| Kennzahl | Formel | Quellfeld | Diagnose-Schwelle |
|---|---|---|---|
| Sessions gesamt | kommt von GA4 als Gesamtzeile | `ga4.json > totals.sessions` | Auffälligkeits-Schwelle |
| Nutzer | kommt von GA4 als Gesamtzeile, entdoppelt | `ga4.json > totals.total_users` | Auffälligkeits-Schwelle |
| Umsatz aus GA4 | kommt von GA4 als Gesamtzeile, abzüglich Erstattungen, in der Währung `ga4.json > currency` | `ga4.json > totals.purchase_revenue` | Auffälligkeits-Schwelle |
| Conversion Rate je Kanal | siehe unten | `ga4.json > channels[].purchases` und `ga4.json > channels[].sessions` | siehe unten |
| Engagement-Rate je Landingpage | kommt fertig von GA4 | `ga4.json > landing_pages[].engagement_rate` | keine belastbare Benchmark, nur Vergleich der Seiten untereinander |
| Funnel-Abbruch | siehe unten | `ga4.json > funnel` | siehe unten |

**Die drei Totals werden nicht selbst summiert.** Der Kanal-Call fordert
`metricAggregations: ["TOTAL"]` an, GA4 rechnet die Gesamtzeile. Bei Sessions
und Umsatz käme dasselbe heraus, bei der Nutzerzahl nicht: GA4 entdoppelt
Nutzer je Dimensionskombination, wer im Zeitraum über Organic und über E-Mail
kommt, steht in beiden Kanalzeilen. Eine Summe über die Kanäle ist deshalb
immer zu hoch, und zwar umso mehr, je mehr Kanäle ein Shop bespielt.

Bis zum 06.09.2026 hat das Script summiert; Nutzerzahlen in Reports davor sind
zu hoch. Fehlt die Gesamtzeile ausnahmsweise, steht `total_users` auf `null`,
nie auf einer Summe.

### Conversion Rate je Kanal

- **Formel:** `purchases / sessions` je Eintrag in `channels`, ausgewiesen in
  Prozent mit einer Nachkommastelle.
- **Quellfeld:** `ga4.json > channels[].purchases`,
  `ga4.json > channels[].sessions`. `purchases` kommt aus der GA4-Metrik
  `ecommercePurchases`, nie aus `transactions`: die zählt `refund`-Ereignisse
  mit. Snapshots von vor dem 11.09.2026 tragen nur `transactions` und sind
  hierfür nicht berechenbar.
- **Diagnose-Schwelle:** Befund für den schwächsten Kanal mit mindestens 100
  Sessions im Berichtszeitraum, dessen Rate unter der Hälfte der Rate des
  stärksten Kanals liegt. Die 100 Sessions sind die Mindestbasis, darunter ist
  eine Rate Zufall und wird nicht kommentiert.
- **Nicht berechenbar,** wenn `purchases` fehlt oder `null` ist (die
  GA4-Property hat die Metrik abgelehnt, Grund in `ga4.json > notes.purchases`)
  oder wenn `sessions` 0 ist. Dann entfällt die Spalte komplett, keine leeren
  Zellen.
- **Benchmark:** Bänder je Kanal unten, ausdrücklich als Fremdquelle.

### Funnel (nur als Zulieferung zum Kaufweg)

`ga4.json > funnel` trägt je Ereignis zwei Zahlen: `events` (wie oft es
ausgelöst wurde) und `sessions` (in wie vielen Besuchen es vorkam).

- **Für jede Quote im Report zählt `sessions`, nie `events`.** Eine Person sieht
  mehrere Produkte an: am Pilot-Shop standen deutlich mehr
  `view_item`-Ereignisse als Sessions. Wer die Ereigniszahl als Personen liest,
  rechnet jede Folgequote
  falsch und produziert Weiterraten über 100 %, die dann als "kein Fehler"
  wegerklärt werden müssen.
- **`events` bleibt im Snapshot** als Rohwert und für die Frage, wie intensiv
  ein Schritt genutzt wird. Im Report taucht die Zahl höchstens als Nebensatz
  auf, nie in einer Quote.
- **Die Reihenfolge** ist `sessions`, `view_item`, `add_to_cart`,
  `begin_checkout`, `purchase`. Verwendet wird davon im Report nur, was der
  Abschnitt Micro-Conversion-Funnel oben zulässt: die Produktansicht als Zwischenstufe, alles
  ab `begin_checkout` nur als genannte Zahl ohne Quote.
- **Fehlt ein Ereignis ganz** (etwa `view_cart` bei einem Warenkorb-Drawer ohne
  eigene Adresse), ist das kein Messfehler und wird nicht als 0 gewertet: der
  Schritt existiert in diesem Shop schlicht nicht.

## 3. SEO (gsc.json)

| Kennzahl | Formel | Quellfeld | Diagnose-Schwelle |
|---|---|---|---|
| Klicks | kommt fertig von GSC | `gsc.json > totals.clicks` | Auffälligkeits-Schwelle |
| Impressionen | kommt fertig von GSC | `gsc.json > totals.impressions` | Auffälligkeits-Schwelle |
| CTR gesamt | kommt fertig von GSC, nie aus Klicks und Impressionen nachrechnen | `gsc.json > totals.ctr` | Auffälligkeits-Schwelle |
| Position | kommt fertig von GSC | `gsc.json > totals.position` | Verschlechterung um mindestens 3 Plätze |
| Striking-Distance-Query | siehe unten | `gsc.json > top_queries[]` | siehe unten |
| CTR-Lücke | siehe unten | `gsc.json > top_queries[]` | siehe unten |
| Indexierte Seiten | siehe unten | `gsc.json > index_sample[].verdict`, ersatzweise `crawl.json > pages[].indexable` | keine belastbare Benchmark |
| Anteil Nicht-Marken-Klicks | siehe unten | `gsc.json > top_queries[]` gegen `geo.json > query_set.brand` | keine belastbare Benchmark |

### Striking-Distance-Query

Query, die schon nah an den Top-3 steht und genug Nachfrage hat, damit ein paar
Plätze spürbar werden.

- **Formel:** Eintrag aus `top_queries[]` mit `position` zwischen 4 und 15
  (beide inklusive) und `impressions` größer oder gleich
  `striking_distance_min_impressions`.
- **Quellfeld:** `gsc.json > top_queries[].position`,
  `gsc.json > top_queries[].impressions`, `gsc.json > top_queries[].clicks`,
  `gsc.json > top_queries[].query`.
- **Parameter:** `striking_distance_min_impressions` gleich 50 im Monat. Im
  Wochen-Puls wird der Parameter nicht angewendet, die Diagnose ist eine
  Monats-Diagnose.
- **Diagnose:** Quick-Win-Kandidat. Sortiert nach `impressions` absteigend, im
  Report auf 10 gekappt.

### CTR-Lücke

Query, die auf ihrer Position deutlich weniger geklickt wird als die eigenen
Queries auf vergleichbarer Position. Bewusst ohne fremde Positions-CTR-Kurve: es
gibt keine belastbare, prüfbare Kurve, deshalb wird ausschließlich innerhalb des
eigenen Datensatzes verglichen.

- **Formel,** je Query `q` aus `top_queries[]` mit
  `impressions >= ctr_gap_min_impressions`:
  1. Vergleichsmenge `P(q)`: alle anderen Queries aus `top_queries[]` mit
     `impressions >= ctr_gap_min_impressions` und
     `|position - position(q)| <= ctr_gap_position_window`.
  2. Sind in `P(q)` weniger als `ctr_gap_min_peers` Queries, ist die CTR-Lücke
     für `q` nicht berechenbar. Kein Befund, keine Ersatzzahl.
  3. `median_ctr` ist der Median der `ctr` über `P(q)`.
  4. Befund, wenn `ctr(q) < ctr_gap_factor * median_ctr`.
- **Quellfeld:** `gsc.json > top_queries[].ctr`,
  `gsc.json > top_queries[].position`, `gsc.json > top_queries[].impressions`.
- **Parameter:** `ctr_gap_min_impressions` gleich 50, `ctr_gap_position_window`
  gleich 2 Positionen nach oben und unten, `ctr_gap_min_peers` gleich 5,
  `ctr_gap_factor` gleich 0,5 (die Hälfte des Medians).
- **Sortierung:** nach der rechnerischen Klick-Lücke
  `impressions * (median_ctr - ctr)` absteigend, im Report auf 10 gekappt. Die
  Klick-Lücke ist eine Rechengröße aus zwei Snapshot-Feldern, keine Prognose,
  und wird im Report als solche benannt oder weggelassen.

### Indexierte Seiten

Anteil der geprüften URLs, die bei Google tatsächlich indexiert sind. Zwei
Quellen unterschiedlicher Genauigkeit, nie in einer Zahl gemischt.

- **Formel, primär (Googles eigener Befund):** Zeilen aus `index_sample[]` mit
  `verdict` gleich `PASS`, geteilt durch alle Zeilen ohne `error`. Diese
  Stichprobe deckt nur die in `cwv_urls` konfigurierten Seitentypen ab
  (dieselbe kleine Liste wie beim CWV-Pull), nie den ganzen Shop.
- **Formel, ersatzweise (Crawler-Heuristik):** liegt kein `index_sample` vor
  (GSC nicht angeschlossen oder die Stichprobe komplett fehlgeschlagen),
  Anteil der Zeilen aus `crawl.json > pages[]` mit `indexable` gleich `true`
  über alle gecrawlten Seiten. Das ist eine Schätzung aus Robots-Meta,
  Canonical und Statuscode, kein Googles eigener Befund.
- **Quellfeld:** `gsc.json > index_sample[].verdict`, ersatzweise
  `crawl.json > pages[].indexable`.
- **Im Report immer benennen, welche der beiden Quellen gezählt wurde:** die
  Zahlen sind nicht vergleichbar, eine Stichprobe weniger Seitentypen gegen
  den vollen Crawl.
- **Keine Benchmark,** nur die eigene Zahl mit Quellenangabe.

### Anteil Nicht-Marken-Klicks

Anteil der Klicks und Impressionen, die auf Suchanfragen ohne Markenbezug
entfallen.

- **Formel:** jede Query aus `top_queries[]` gegen `geo.json >
  query_set.brand` klassifizieren: markenbezogen, wenn sie einen der
  Markenbegriffe (oder einen erkennbaren Wortstamm daraus) enthält,
  unabhängig von Groß-/Kleinschreibung. Anteil Nicht-Marken-Klicks ist die
  Summe `clicks` der nicht-markenbezogenen Zeilen geteilt durch die Summe
  `clicks` aller Zeilen, getrennt davon dieselbe Rechnung für `impressions`.
- **Quellfeld:** `gsc.json > top_queries[].query`, `.clicks`, `.impressions`
  gegen `geo.json > query_set.brand`.
- **Nicht berechenbar,** wenn `geo.json` fehlt oder kein `query_set.brand`
  trägt (GEO war in diesem Lauf deaktiviert oder nicht verfügbar): kein
  geratener Marke-Nichtmarke-Split.
- **Einschränkung:** das Ergebnis bezieht sich nur auf die in `top_queries[]`
  erfassten Zeilen, eine Stichprobe der stärksten Queries, nie auf das volle
  Suchvolumen; das gehört als Einschränkung mit in den Report.
- **Keine Benchmark,** nur Vergleich gegen den eigenen Vormonat.

## 4. Core Web Vitals (cwv.json)

| Kennzahl | Formel | Quellfeld | Diagnose-Schwelle |
|---|---|---|---|
| LCP | kommt fertig aus CrUX (Feld) bzw. Lighthouse (Lab) | `cwv.json > pages[].field_data.lcp_ms`, ersatzweise `pages[].lab.lcp_ms` | gut bis 2,5 s, siehe Googles Definition unten |
| INP | kommt fertig aus CrUX | `cwv.json > pages[].field_data.inp_ms` | gut bis 200 ms, siehe unten |
| CLS | kommt fertig aus CrUX (Feld) bzw. Lighthouse (Lab) | `cwv.json > pages[].field_data.cls`, ersatzweise `pages[].lab.cls` | gut bis 0,1, siehe unten |
| Lab-Performance-Score | kommt fertig von Lighthouse | `cwv.json > pages[].lab.performance_score` | Befund unter 0,5 |

`field_data` gleich `null` ist kein Fehler, sondern zu wenig CrUX-Traffic. Dann
zählt der Lab-Wert, und die Zeile wird als "keine Feld-Daten" gekennzeichnet.
Feld- und Lab-Werte werden nie in einer Spalte vermischt.

**Schwellen (Googles offizielle Definition, keine Fremd-Benchmark):** LCP gut bis
2,5 Sekunden, INP gut bis 200 Millisekunden, CLS gut bis 0,1. Gemessen wird
jeweils am 75. Perzentil der Seitenaufrufe, getrennt nach Mobil und Desktop.
Quelle: Google, https://web.dev/articles/vitals, abgerufen 2026-08-11.

**Diese Tabelle ist zugleich die Formel-Quelle für den Baseline-Block `tech`**
(Spec Abschnitt 10: "Core Web Vitals je Seitentyp, Feld und Labor"). Jede
Zeile aus `pages[]` trägt bereits ihren eigenen `page_type`; im Baseline-Block
bleibt die Gruppierung also der volle Inhalt von `pages[]`, ohne eigene
Aggregation obendrauf.

## 5. GEO (geo.json)

| Kennzahl | Formel | Quellfeld | Diagnose-Schwelle |
|---|---|---|---|
| Brand-Erwähnungsquote | Zeilen mit `brand_mentioned` gleich `true` geteilt durch die Zeilen mit `brand_mentioned` ungleich `null` | `geo.json > queries[].brand_mentioned` | Einordnung wie Citation Rate, eigene Bänder gibt es dafür nicht |
| Citation Rate | siehe unten | `geo.json > queries[].domain_cited` | siehe unten |
| Share of Voice | siehe unten | `geo.json > queries[].other_citations` | siehe unten |
| Crawler-Zugang | Auszählung der acht Schlüssel | `geo.json > crawlers` | jeder blockierte AI-Crawler ist ein Befund |
| llms.txt | boolesch | `geo.json > llms_txt` | `false` ist ein Hinweis, kein Befund |

### Citation Rate

Anteil der geprüften Query-Plattform-Zeilen, in denen die eigene Domain als
Quelle auftaucht.

- **Formel,** je Gruppe (`brand`, `category` und `problem` getrennt, nie
  zusammengeworfen): Zeilen mit `domain_cited` gleich `true` geteilt durch die
  Zeilen mit `domain_cited` ungleich `null`.
- **Quellfeld:** `geo.json > queries[].domain_cited`,
  `geo.json > queries[].group`.
- **Nicht prüfbare Zeilen** (`null`) stehen weder im Zähler noch im Nenner und
  werden getrennt ausgewiesen. Sind alle Zeilen einer Gruppe `null`, gibt es
  keine Rate, sondern den Satz, wie viele Zeilen nicht prüfbar waren.
- **Verglichen wird nur innerhalb derselben Plattform und derselben `method`**
  (Regel 7 in `skills/check-geo/SKILL.md`).
- **Diagnose-Schwelle und Benchmark:** die Bänder unten, ausdrücklich als
  Fremdquelle.

### Share of Voice

Wer statt der eigenen Domain zitiert wird, über dieselben Query-Zeilen.

- **Formel:** über alle Zeilen mit `domain_cited` ungleich `null` je Domain
  zählen, in wie vielen Zeilen sie zitiert wurde. Die eigene Domain zählt über
  `domain_cited` gleich `true`, jede fremde Domain über ihr Vorkommen in
  `other_citations`. `other_citations` ist je Zeile bereits dedupliziert, eine
  Domain zählt also höchstens einmal pro Zeile. Share of Voice der eigenen Domain
  ist die eigene Zahl geteilt durch die Summe aller Nennungen.
- **Quellfeld:** `geo.json > queries[].other_citations`,
  `geo.json > queries[].domain_cited`.
- **Diagnose-Schwelle:** Befund, wenn die eigene Domain in der Rangliste einer
  Gruppe nicht unter den ersten fünf Domains auftaucht. Im Report auf die fünf
  häufigsten fremden Domains gekappt.
- **Nicht berechenbar,** wenn keine Zeile der Gruppe prüfbar war oder
  `other_citations` in allen Zeilen leer ist.

## 6. Messung (measurement)

| Kennzahl | Formel | Quellfeld | Diagnose-Schwelle |
|---|---|---|---|
| Zuordnungslücke Shopify gegen GA4 | siehe unten | `shopify.json > totals.orders`, `ga4.json > funnel.purchase.events` | siehe unten |

### Zuordnungslücke Shopify gegen GA4

Welcher Anteil der tatsächlichen Shopify-Bestellungen in GA4 nicht als
`purchase` ankommt. Formel-Quelle für den Baseline-Block `measurement` (Spec
Abschnitt 10). **Nicht zu verwechseln** mit der Zuordnungslücke Bestellungen
aus Abschnitt 1: die dortige Formel misst die Lücke innerhalb von Shopifys
eigener `sessions.conversion_rate` und gehört zum Baseline-Block
`conversion`. Der Block `measurement` hier hält ausschließlich den Abgleich
gegen GA4.

- **Formel:** `1 - (ga4.json > funnel.purchase.events / shopify.json >
  totals.orders)`, in Prozent.
- **Quellfeld:** `shopify.json > totals.orders`,
  `ga4.json > funnel.purchase.events`.
- **Diagnose-Schwelle:** Befund ab 20 Prozent nicht erfasster Bestellungen,
  dieselbe Schwelle wie die Zuordnungslücke Bestellungen in Abschnitt 1, weil
  beide dieselbe Art von Messlücke beschreiben.
- **Nicht berechenbar,** wenn `totals.orders` 0 oder `null` ist, oder wenn
  `funnel.purchase.events` fehlt (die GA4-Property misst `purchase` nicht).
- **Pilot-Beleg:** Beispielshop, Juli 2026: drei von zehn Bestellungen in
  GA4 als `purchase` erfasst, 70 Prozent Lücke, dieselbe Größenordnung wie die
  Zuordnungslücke Bestellungen aus Abschnitt 1 (deutet auf eine gemeinsame
  Ursache in der clientseitigen Erfassung).
- **Keine Benchmark,** nur die eigene Zahl gegen die eigene Historie.

## Benchmarks (Fremdquellen)

Alle Bänder in dieser Tabelle sind **Fremdquellen und von uns nicht validiert.**
Sie ordnen ein, sie bewerten nicht. In Report und Puls werden sie immer mit
Quelle und Abrufdatum genannt.

| Kennzahl | Band | Quelle | Abgerufen |
|---|---|---|---|
| Conversion Rate, Shopify-Shops | Median rund 1,4 %, Top 20 % ab 3,2 %, Top 10 % ab 4,7 % | https://karbonanalytics.com/blog/shopify-conversion-rate-benchmarks-2026/ | 2026-08-11 |
| Conversion Rate, DTC | schwach unter 1,5 %, Schnitt 1,8 bis 2,5 %, stark ab 3 % | https://www.dtcpages.com/blog/ecommerce-conversion-rate-benchmarks-2026 | 2026-08-11 |
| Conversion Rate, E-Mail | 4,0 bis 5,3 % | https://blendcommerce.com/blogs/shopify/ecommerce-conversion-rate-benchmarks-2026 | 2026-08-11 |
| Conversion Rate, organische Suche | 2,7 bis 3,0 % | https://blendcommerce.com/blogs/shopify/ecommerce-conversion-rate-benchmarks-2026 | 2026-08-11 |
| Conversion Rate, Paid Social | 0,7 bis 1,2 % | https://blendcommerce.com/blogs/shopify/ecommerce-conversion-rate-benchmarks-2026 | 2026-08-11 |
| Conversion Rate, Desktop | 3,5 bis 4,0 % | https://blendcommerce.com/blogs/shopify/ecommerce-conversion-rate-benchmarks-2026 | 2026-08-11 |
| Conversion Rate, Mobile | 1,8 bis 2,5 % | https://blendcommerce.com/blogs/shopify/ecommerce-conversion-rate-benchmarks-2026 | 2026-08-11 |
| Repeat-Customer-Rate, DTC | Schnitt 25 bis 30 %, Verbrauchsgüter und Abo 35 bis 55 %, Anschaffungen 12 bis 18 % | https://www.letstalkshop.com/blog/ecommerce-kpis | 2026-08-11 |
| GEO Citation Rate | unter 15 % deutliche Lücke, 25 bis 40 % wettbewerbsfähig, über 40 % stark | https://discoveredlabs.com/blog/geo-metrics-what-kpis-matter-how-to-track-them-2026 | 2026-08-11 |

Die Kanal-Bänder passen auf die GA4-Kanalgruppen nur ungefähr: "organische
Suche" entspricht `Organic Search`, "Paid Social" entspricht `Paid Social`,
E-Mail entspricht `Email`. Desktop und Mobile liegen im aktuellen GA4-Pull
überhaupt nicht vor (der Kanal-Call bringt keine Geräte-Dimension mit) und
werden deshalb im Report nicht verwendet, sondern hier nur festgehalten.

**Keine belastbare Benchmark gibt es für:** Engagement-Rate, Warenkorbwert,
Weiterraten der einzelnen Funnel-Schritte, CTR je Suchposition,
Brand-Erwähnungsquote in AI-Antworten, Indexierte Seiten, Anteil
Nicht-Marken-Klicks, Zuordnungslücke Shopify gegen GA4. Diese Kennzahlen
werden ausschließlich gegen den eigenen Vormonat oder gegen den eigenen
Datensatz eingeordnet.

## Parameter auf einen Blick

| Parameter | Wert | Wo er wirkt |
|---|---|---|
| Auffälligkeits-Schwelle | 20 % relatives Delta oder Null-Linie | alle Kennzahlen ohne eigene Schwelle |
| `striking_distance_min_impressions` | 50 im Monat | Striking-Distance-Query |
| Striking-Distance-Positionsfenster | 4 bis 15 inklusive | Striking-Distance-Query |
| `ctr_gap_min_impressions` | 50 im Monat | CTR-Lücke |
| `ctr_gap_position_window` | 2 Positionen | CTR-Lücke |
| `ctr_gap_min_peers` | 5 Queries | CTR-Lücke |
| `ctr_gap_factor` | 0,5 | CTR-Lücke |
| Mindestbasis Kanal-Conversion | 100 Sessions | Conversion Rate je Kanal |
| Bestandsrisiko, absolut | 5 Stück oder weniger | Sortiments-Diagnose |
| Bestandsrisiko, Reichweite | Bestand kleiner als Bestellungen im Zeitraum | Sortiments-Diagnose |
| Verfügbarkeits-Befund je Produkt | weniger als die Hälfte der Varianten bestellbar | Verfügbarkeit |
| Abandoned Carts, Befund | Warenwert ab 20 % des Monatsumsatzes | Abandoned Carts |
| Zuordnungslücke, Befund | 20 % nicht zugeordnete Bestellungen | Conversion Rate gesamt; Zuordnungslücke Shopify gegen GA4 (Messung) |
| Kappung im Report | 10 Zeilen je Diagnose-Tabelle, 5 fremde Domains bei Share of Voice | alle Diagnose-Blöcke |

## Pflege

Eine Benchmark-Quelle wird ersetzt, nicht ergänzt: pro Kennzahl steht genau ein
Band, mit genau einer Quelle und einem Abrufdatum. Ist eine Quelle offline oder
älter als zwölf Monate, wird sie beim nächsten Anfassen neu gezogen oder die
Zeile fällt auf "keine belastbare Benchmark" zurück. Schwellen, die aus dem
Pilot kommen, werden hier korrigiert, sobald echte Kundendaten dagegen sprechen.
