---
name: pull-shopify
description: Shopify-Shop-Daten für den Kunden-Report oder den Wochen-Puls ziehen (Umsatz, Bestellungen, AOV, Top-Produkte, Sessions, Bestand, Kundentyp) und als Snapshot ablegen. Nutzen, wenn ein Monats-Report oder Puls Shop-KPIs braucht, oder wenn der Nutzer explizit Shopify-Zahlen für einen Zeitraum abrufen will. Werkzeug ist die Shopify CLI (store execute), kein Script; liest reporting/config.json im Kunden-Workspace.
---

# pull-shopify: Shopify-Snapshot ziehen

Zieht per Shopify CLI Umsatz, Bestellungen, AOV, Top-Produkte, Sessions und
Bestand für einen Zeitraum und legt alles als Snapshot im Kunden-Workspace ab.
Kein Script: ShopifyQL läuft über das Admin-GraphQL-Feld `shopifyqlQuery`
(so dokumentiert es Shopify, rohes ShopifyQL direkt in `--query` ist nicht
dokumentiert), der Bestand über eine normale Admin-GraphQL-Query. Diese Session
baut aus den CLI-Antworten selbst die Snapshot-Datei nach dem Schema unten.
Wird vom Report- und Puls-Lauf aufgerufen, funktioniert aber auch solo.

## Voraussetzungen

Im Kunden-Workspace (aktuelles Arbeitsverzeichnis):

- `reporting/config.json` mit `shopify_store` (die echte myshopify.com-Domain,
  nie ein Alias) und `sources.shopify` nicht `false`
- Shopify CLI installiert (`shopify version`); fehlt sie:
  `npm install -g @shopify/cli@latest`
- Store-Auth für die Domain vorhanden (Scope-Regel unten)

Fehlt eins davon oder steht `sources.shopify` auf `false`: Shopify als "nicht
verfügbar (Grund)" melden und aufhören. Nie den Gesamtlauf (Report/Puls) daran
scheitern lassen.

## Scope-Regel (hart): vor jeder Re-Auth die Union senden

Die CLI mergt Scopes nicht verlässlich. Eine Auth mit nur den Report-Scopes
(`--scopes read_reports,read_products`) schrumpft den Grant des Stores auf genau
diese zwei zusammen; alles andere (Themes, Content, Files, Inventory) ist danach
weg. Der Zustimmungsdialog zeigt dabei nur Zugewinne an, nie Verluste; der
Schwund fällt erst auf, wenn ein anderer Workflow scheitert. Deshalb immer in
dieser Reihenfolge:

**Benötigte Scopes für den vollen Audit-Umfang:**

| Scope | Wofür |
|---|---|
| `read_reports` | ShopifyQL, Umsatz, Sessions |
| `read_products` | Katalog, Varianten, Bilder |
| `read_orders` | Bestellungen der letzten 60 Tage |
| `read_all_orders` | volle Bestellhistorie. Ohne diesen Scope entsteht still eine 60-Tage-Baseline |
| `read_inventory` | Bestand, tote Artikel |
| `read_themes` | Theme und Version |
| `read_script_tags` | eingebundene Fremdskripte |
| `read_discounts`, `read_price_rules` | Rabattstruktur |
| `read_locales`, `read_markets` | Sprach- und Marktkonfiguration |

Die Liste wächst mit dem Audit-Scope, die Union-Regel unten bleibt davon
unberührt: bei einer Re-Auth immer alle bestehenden plus alle hier gelisteten
Scopes senden, nie nur die neu benötigten.

1. **Auth-Status prüfen:** `shopify store auth list --json` (dokumentierte
   Form; `auth:list` mit Doppelpunkt zeigt dasselbe Kommando). Steht die
   Store-Domain aus der Config nicht drin, ist es eine Erst-Auth: direkt mit
   der vollständigen Scope-Liste oben authentifizieren. Hat das
   Kundenprojekt eine dokumentierte Scope-Liste (CLAUDE.md des Kunden-Repos,
   Notizen im Kundenordner), die verwenden.
2. **Bestehenden Grant lesen** (Store ist authentifiziert):

   ```bash
   shopify store execute --store <shopify_store> --json \
     --query 'query { currentAppInstallation { accessScopes { handle } } }' 2>/dev/null
   ```

   Deckt die zurückgegebene Liste alle Scopes aus der Tabelle oben schon ab:
   nichts tun, keine Re-Auth. Scheitert der Call, weil der Online-Token (etwa
   24h Laufzeit) abgelaufen ist, den bisherigen Scope-Satz aus der
   CLI-Konfiguration lesen (macOS:
   `~/Library/Preferences/shopify-cli-store-nodejs/config.json`, pro
   Store-Domain inklusive Scopes) statt ihn zu raten.
3. **Re-Auth nur mit Union:** die Vereinigungsmenge aus allen bestehenden plus
   den benötigten Scopes in einer einzigen `--scopes`-Liste senden, nie nur die
   neu benötigten:

   ```bash
   shopify store auth --store <shopify_store> \
     --scopes <bestehende Scopes>,read_reports,read_products,read_orders,read_all_orders,read_inventory,read_themes,read_script_tags,read_discounts,read_price_rules,read_locales,read_markets
   ```

## Ablauf

1. `reporting/config.json` lesen (`shopify_store`). Zeitraum bestimmen: Default
   ist der letzte volle Monat (Erster bis Letzter des Vormonats), Puls-Modus die
   letzte volle Woche, Montag bis Sonntag. `SINCE`/`UNTIL` nehmen explizite
   Datumsgrenzen, beide inklusiv.
2. Auth nach der Scope-Regel oben sicherstellen. **Historie-Check direkt
   danach:** im gerade gelesenen Grant (`currentAppInstallation { accessScopes
   { handle } }`, Scope-Regel Schritt 2) prüfen, ob `read_all_orders`
   tatsächlich dabeisteht. Der Zustimmungsdialog kann den Scope trotz Anfrage
   in der Union stillschweigend verweigern, etwa weil die App für „Protected
   Customer Data" nicht freigegeben ist; das fällt sonst erst auf, wenn die
   Kohorten- und Repeat-Rate-Zahlen weiter unten leer bleiben. Fehlt
   `read_all_orders`, ist die Bestellhistorie hart auf 60 Tage begrenzt: das
   ist ein Befund und kein Ergebnis, nicht still eine Kurz-Baseline. Melden
   als „Historie auf 60 Tage begrenzt, `read_all_orders` fehlt" und als
   `notes.order_history` in den Snapshot schreiben (Schritt 5).

   **Der Scope allein beweist die Historie nicht, deshalb kommt danach die
   empirische Probe.** Ein Shop, der auf Shopify migriert ist, hat den Scope und
   trotzdem keine Vorgeschichte in der Admin-API: die importierten Bestellungen
   tragen das Importdatum als `createdAt`, nicht das Kaufdatum. Am ersten echten
   Lauf lag die älteste Bestellung dort Jahre nach dem ersten Monat mit Umsatz,
   und die beiden Monate rund um den Import zeigten ein Vielfaches der realen
   Bestellzahl. Zwei Werte holen und vergleichen:

   ```bash
   # aelteste Bestellung laut Admin-API
   shopify store execute --store <shopify_store> --json --query 'query {
     orders(first: 1, sortKey: CREATED_AT, reverse: false) {
       nodes { createdAt }
     }
   }' 2>/dev/null
   ```

   Dagegen der erste Monat mit Umsatz aus der Zeitreihe (Schritt 4). Liegen die
   beiden weit auseinander, ist der Shop migriert. Dann gilt: **Historie
   ausschließlich über ShopifyQL, nie über einen Admin-API-Datumsfilter**, und
   `notes.order_history` hält beide Daten samt dem Satz, dass Admin-seitige
   Datumsfilter vor dem Importdatum falsche Zahlen liefern.
3. Vergleichszeitraum nur beim Erstlauf: existiert bereits ein
   Vormonats-Snapshot (jüngster `reporting/data/`-Ordner, dessen `shopify.json`
   einen `period` mit granularity `month` über den vollen Vormonat trägt;
   `-pulse`-Dateien ignorieren), dann keinen Vergleich mitziehen, der Report
   vergleicht gegen den Snapshot. Existiert keiner, dieselben Teil-Pulls (ohne
   Bestand) zusätzlich für den Monat davor laufen lassen und als `comparison`
   ablegen.
4. Teil-Pulls ausführen. Jeder Teil scheitert isoliert: ein Fehler macht das
   jeweilige Feld im Snapshot `null` plus Begründung in `notes`, bricht aber
   nie den Lauf ab. stdout von `store execute --json` ist reines JSON,
   Fortschritt landet auf stderr, deshalb überall `2>/dev/null`.

   **Genau deshalb muss der Exit-Code geprüft werden, und zwar bei jedem Call.**
   Die Admin-API arbeitet mit einem Punktebudget, und die ShopifyQL-Abfragen
   eines Audits über die volle Historie sind teuer: am ersten echten Lauf war
   rund die Hälfte der Calls beim ersten Versuch gedrosselt. Die CLI meldet das
   auf stderr, beendet sich mit Exit 1 und schreibt nichts nach stdout. Mit
   `2>/dev/null` sieht der Aufrufer eine leere Antwort und hält sie für "keine
   Daten", während in Wahrheit nichts abgefragt wurde. Deshalb:

   ```bash
   if ! antwort="$(shopify store execute ... 2>/dev/null)"; then
     # gedrosselt oder Netzwerkfehler: warten und erneut versuchen
     sleep 20 && antwort="$(shopify store execute ... 2>/dev/null)" || true
   fi
   ```

   Zwei Wiederholungen mit wachsender Pause (20, dann 40 Sekunden) reichten am
   ersten Lauf für jeden gedrosselten Call. Scheitert ein Teil-Pull danach
   weiterhin, wird sein Feld `null` plus Begründung in `notes`, wie jeder andere
   Fehlschlag auch. **Eine leere Antwort ohne Exit-Code-Prüfung darf nie als
   "keine Daten" in den Snapshot gehen.**

   Nach jedem
   ShopifyQL-Call `parseErrors` prüfen: nicht leer heißt Query kaputt, gegen
   die ShopifyQL-Referenz korrigieren und erneut ausführen.

   **Umsatz-Totals** (Zahlen kommen aus `tableData.rows`, Spaltennamen aus
   `tableData.columns`, beides 1:1 übernehmen, nie selbst rechnen):

   ```bash
   shopify store execute --store <shopify_store> --json --query 'query {
     shopifyqlQuery(query: """
       FROM sales
       SHOW total_sales, net_sales, orders, average_order_value
       SINCE 2026-07-01 UNTIL 2026-07-31
     """) { tableData { columns { name dataType } rows } parseErrors }
   }' 2>/dev/null
   ```

   **Zeitreihe** (gleiche Query plus `TIMESERIES month`; Puls: `TIMESERIES day`
   über die Woche; den AOV nie aus der Zeitreihe mitteln, der kommt aus der
   Totals-Query):

   ```bash
   shopify store execute --store <shopify_store> --json --query 'query {
     shopifyqlQuery(query: """
       FROM sales
       SHOW total_sales, net_sales, orders
       TIMESERIES month
       SINCE 2026-07-01 UNTIL 2026-07-31
     """) { tableData { columns { name dataType } rows } parseErrors }
   }' 2>/dev/null
   ```

   **Top-Produkte nach Umsatz** (ShopifyQL, nicht GraphQL: der Admin-Enum
   `ProductSortKeys` kennt kein `BEST_SELLING`):

   ```bash
   shopify store execute --store <shopify_store> --json --query 'query {
     shopifyqlQuery(query: """
       FROM sales
       SHOW net_sales, orders
       GROUP BY product_title
       SINCE 2026-07-01 UNTIL 2026-07-31
       ORDER BY net_sales DESC
       LIMIT 50
     """) { tableData { columns { name dataType } rows } parseErrors }
   }' 2>/dev/null
   ```

   **Eine Zeile ohne `product_title` ist kein Produkt.** Ein migrierter Shop
   bringt Bestellungen ohne Artikelbezug mit, und ShopifyQL fasst sie in einer
   einzigen Zeile mit `product_title: null` zusammen. Am 07.09.2026 trug diese
   Zeile 67,6 Prozent des gesamten Nettoumsatzes und stand damit an der Spitze
   der Top-Produkte. Wer sie als Produkt zählt, bekommt "das stärkste Produkt
   trägt zwei Drittel des Umsatzes" und friert diese Aussage in der Baseline
   ein.

   Die Zeile bleibt unverändert im Snapshot, sie ist eine echte Messung. Aber
   sie gehört in `notes.top_products` mit Betrag und Anteil, und **jede
   Sortimentsrechnung läuft ausschließlich über die benannten Zeilen**, mit
   dem benannten Umsatz als Nenner. Der unbenannte Anteil wird daneben
   ausgewiesen, nie stillschweigend mitgerechnet und nie weggelassen.

   **`LIMIT` wird so lange erhöht, bis die Liste nachweislich vollständig ist.**
   Kommen genau so viele Zeilen zurück, wie das Limit erlaubt, ist sie
   abgeschnitten, und die Sortiments-Diagnose zählt Produkte fälschlich als
   umsatzlos. Am ersten echten Lauf brauchte es drei Erhöhungen (50, 1.000,
   5.000), bis die Liste unter dem Limit blieb. Der Snapshot hält immer die
   vollständige Liste, der Report zeigt daraus die Top 10. Die erreichte
   Zeilenzahl und das benutzte Limit gehören nach `notes.top_products`.

   `LIMIT 50` als Startwert statt 10, weil die Sortiments-Diagnose "Ware ohne Umsatz"
   (Kennzahlen-Katalog) den vollen Produktbestand gegen die Umsatzzeilen hält:
   bei `LIMIT 10` zählte ein Produkt auf Rang 11 fälschlich als umsatzlos. Der
   Report zeigt weiterhin nur die Top 10, der Snapshot hält bis zu 50 Zeilen.
   Kommen genau 50 Zeilen zurück, ist die Liste womöglich abgeschnitten: dann
   das Limit erhöhen, sonst ist die Diagnose falsch.

   **Sessions, Conversion Rate und Kaufweg:** das `sessions`-Schema liefert
   neben `sessions` und `conversion_rate` auch die beiden Kaufweg-Stufen
   `sessions_with_cart_additions` und `sessions_that_reached_checkout` (am
   Pilot-Shop bestätigt). Die Query enthält einfache Anführungszeichen, deshalb
   in eine Datei schreiben und mit `--query-file` ausführen:

   ```graphql
   query {
     shopifyqlQuery(query: """
       FROM sessions
       SHOW sessions, sessions_with_cart_additions,
            sessions_that_reached_checkout, conversion_rate
       WHERE human_or_bot_session = 'human'
       SINCE 2026-07-01 UNTIL 2026-07-31
     """) { tableData { columns { name dataType } rows } parseErrors }
   }
   ```

   ```bash
   shopify store execute --store <shopify_store> --json \
     --query-file <pfad>/sessions.graphql 2>/dev/null
   ```

   Den `WHERE`-Filter nie weglassen: ohne ihn zählen Bots mit, am Pilot-Shop
   waren das im Juni rund 40 Prozent der Sessions. Ergebnis nach `sessions` schreiben
   (`sessions`, `conversion_rate`) und nach `session_funnel` (alle vier Felder).
   Kommt ein Fehler oder keine Daten: beide Felder `null` plus Note, der Report
   nimmt Traffic und Kaufweg dann aus GA4. Nicht fatal.

   **Die beiden unteren Kaufweg-Stufen sind bei kleinen Shops unzuverlässig**
   und werden deshalb nur roh abgelegt, nie zu einer Quote verrechnet. Am
   Pilot-Shop meldete in einem Monat weniger erreichte Checkouts als echte
   Bestellungen und in einem anderen weniger Warenkorb-Sessions als erreichte
   Checkouts, beides rechnerisch unmöglich. Widerspricht
   `sessions_that_reached_checkout` der Bestellzahl,
   gehört das als Note in den Snapshot.

   **Abandoned Carts** (Admin GraphQL, Scope `read_orders`). Die
   Query enthält Anführungszeichen im Filter, deshalb ebenfalls per
   `--query-file`:

   ```graphql
   query {
     abandonedCheckouts(first: 50, query: "created_at:>=2026-07-01 created_at:<=2026-07-31") {
       nodes {
         createdAt
         completedAt
         totalPriceSet { shopMoney { amount currencyCode } }
         lineItems(first: 5) { nodes { title quantity } }
       }
     }
   }
   ```

   Das Feld heißt im Snapshot `abandoned_checkouts` wie das Admin-Objekt, im
   Report heißt die Kennzahl **Abandoned Cart**. Feldnamen folgen der API,
   Anzeigenamen dem Sprachgebrauch.

   **Shopify hält abgebrochene Warenkörbe nur begrenzt vor.** Ein Filter über
   den vollen Audit-Zeitraum liefert trotzdem nur die letzten Monate, und
   `count` und `total_value` sehen danach aus wie Zahlen über den ganzen
   Zeitraum. Den tatsächlich abgedeckten Zeitraum aus dem ältesten `createdAt`
   der Antwort bestimmen und nach `notes.abandoned_checkouts` schreiben, jedes
   Mal, auch wenn der Call sauber durchläuft.

   Nach `abandoned_checkouts` schreiben: `count`, `total_value` (Summe über die
   Zeilen mit `completedAt` gleich `null`), `currency` und die Einzelzeilen.
   Nur nicht abgeschlossene zählen, ein Checkout mit `completedAt` ist eine
   Bestellung geworden. Scheitert der Call, Feld `null` plus Note.

   **Bestand und Verfügbarkeit** (Admin GraphQL, Scope `read_products`). Ein
   Call über **alle aktiven Produkte**, nicht über eine Stichprobe:

   ```bash
   shopify store execute --store <shopify_store> --json --query 'query {
     products(first: 250, query: "status:active") {
       pageInfo { hasNextPage endCursor }
       nodes {
         title handle status totalInventory tracksInventory
         variants(first: 100) {
           pageInfo { hasNextPage }
           nodes { title inventoryQuantity inventoryPolicy availableForSale }
         }
       }
     }
   }' 2>/dev/null
   ```

   **Nie `products(first: 50, sortKey: TITLE)` verwenden.** Das ist keine
   Stichprobe, sondern der Anfang des Alphabets, und es erwischt systematisch
   nicht die Umsatzträger: am Pilot-Shop reichten die 50 Zeilen nur bis
   „Beispielartikel Drei“ und enthielten keines der Eigenprodukte, die den
   Großteil des Umsatzes trugen. Der Bestand der Top-Produkte stand deshalb
   einen ganzen Report lang auf `null`.

   Aus dieser einen Antwort entstehen drei Snapshot-Felder:

   - `products`: je Produkt `product_title`, `handle`, `status`,
     `total_inventory`, `tracks_inventory`. Grundgesamtheit der
     Sortiments-Diagnosen im Kennzahlen-Katalog.
   - `top_products[].total_inventory` und `.status` per Titel-Match. Bleibt ein
     Top-Produkt ohne Match (Titel im Umsatzbericht weicht ab, Produkt
     archiviert), den Bestand für genau diese Titel gezielt nachfragen
     (`query: "title:*<Titel>*"`) statt `null` stehen zu lassen.
   - `availability`: die Aggregate über alle aktiven Produkte, nämlich
     `active_products`, `variants_total`, `variants_available`,
     `products_fully_unavailable`, `products_partially_available`,
     `zero_stock_active`, `zero_stock_still_buyable`, dazu die Listen
     `fully_unavailable_titles` und `partially_available` (Titel plus
     `available_variants` und `total_variants`).

   **`total_inventory: 0` heißt nicht „nicht kaufbar“.** Entscheidend ist
   `availableForSale` je Variante, und die hängt an `inventoryPolicy`: bei
   `CONTINUE` ist das Produkt trotz Bestand 0 bestellbar (Fertigung auf
   Bestellung), bei `DENY` nicht. Am Pilot-Shop waren fast alle Produkte mit
   Bestand 0 normal bestellbar. Ein Report, der Bestand 0 als Kaufhindernis
   liest, behauptet damit das Gegenteil der Wahrheit.

   Mehr als 250 aktive Produkte: über `pageInfo.hasNextPage` und `endCursor`
   blättern, bis alle da sind. Die Aggregate müssen über den vollen Bestand
   laufen, sonst sind sie wertlos. **`pageInfo` steht deshalb in jeder
   Beispiel-Query oben**; ohne das Feld lässt sich gar nicht feststellen, ob
   noch etwas fehlt, und der Aufrufer bekommt die erste Seite und merkt nichts.
   Dasselbe gilt für `variants(first: 100)`: meldet dort `hasNextPage` wahr, ist
   die Variantenliste dieses Produkts unvollständig und die
   Verfügbarkeits-Aggregate stimmen nicht. Die Zahl der geblätterten Seiten
   gehört nach `notes.availability`.

   **Bestellungen nach Quelle** (Admin GraphQL, Scope `read_orders`), damit die
   Abweichung zwischen Bestellzahl und zugeordneter Conversion einzuordnen ist:

   **Gezählt wird, nicht exportiert.** Ein Zeilen-Export über einen
   Audit-Zeitraum sind hunderte Seiten zu je 250 Bestellungen, und er ist genau
   der Bestell-Export auf Zeilenebene, den der Abschnitt "Was nie in den
   Snapshot geht" weiter unten verbietet. `ordersCount` liefert die Zahl je
   Quelle in einem Call ohne eine einzige Bestellzeile:

   ```bash
   shopify store execute --store <shopify_store> --json --query 'query {
     web: ordersCount(query: "source_name:web") { count precision }
     draft: ordersCount(query: "source_name:shopify_draft_order") { count precision }
     alle: ordersCount(query: "") { count precision }
   }' 2>/dev/null
   ```

   **`precision` ist Pflicht, nicht Zierde.** Shopify kappt die Zählung und
   meldet dann `precision: AT_LEAST` statt `EXACT`. Ohne das Feld sieht der
   Aufrufer eine runde Zahl und hält sie für eine Messung. Am 07.09.2026 kam
   für `web` und für `alle` jeweils `10000` zurück, während ShopifyQL für
   denselben Shop ein Vielfaches davon führte: die 10.000 waren die
   Kappungsgrenze, keine Bestellzahl.

   **Meldet auch nur eine Zeile `AT_LEAST`, geht `orders_by_source` als `null`
   in den Snapshot**, zusammen mit einer Note, die die Kappung benennt. Eine
   gekappte Zahl ist schlimmer als keine: die Deutung im nächsten Absatz
   ("tragen praktisch alle Bestellungen `web`") beruht dann auf einem Anteil,
   den niemand gemessen hat.

   Nach `orders_by_source` schreiben (`source_name`, `orders`). **Ein
   numerischer Quellname lässt sich nicht filtern**: eine App-Quelle wie
   `12345678901` liefert über `source_name:` null Treffer, auch in
   Anführungszeichen. Ihre Zahl entsteht als Differenz zwischen `alle` und der
   Summe der benannten Quellen, und dass sie so entstanden ist, gehört in die
   Note.

   Tragen praktisch alle Bestellungen `web`, ist eine niedrige zugeordnete
   Conversion ein Zuordnungsverlust und kein anderer Bestellweg; genau das
   gehört in die Note. **Trägt die Mehrheit eine andere Quelle, gilt der Schluss
   nicht.** Bei einem migrierten Shop ist das der Normalfall, und der Snapshot
   trennt Tracking-Verlust und anderen Bestellweg dann nicht. Dann steht in der
   Note, dass die Ursache offen ist, nie eine der beiden Deutungen.

   `ordersCount` kennt keine Zeitdimension. Die Zahlen decken damit den vollen
   Zeitraum ab und lassen sich nicht auf das Sessions-Fenster schneiden; auch
   das gehört in die Note, sonst werden sie später gegen eine Monatsreihe
   gehalten.

   **Kundentyp** (ShopifyQL, für die Repeat-Rate):

   ```bash
   shopify store execute --store <shopify_store> --json --query 'query {
     shopifyqlQuery(query: """
       FROM sales
       SHOW orders, total_sales
       GROUP BY customer_type
       SINCE 2026-07-01 UNTIL 2026-07-31
     """) { tableData { columns { name dataType } rows } parseErrors }
   }' 2>/dev/null
   ```

   `customer_type` ist laut ShopifyQL-Referenz eine Dimension des
   `sales`-Schemas mit Werten wie `first-time` und `returning`. Die Zeilen 1:1
   übernehmen, nie Werte zusammenfassen oder umbenennen: die Repeat-Rate rechnet
   der Report daraus nach dem Kennzahlen-Katalog.

   **Nicht jeder Shop hat die Dimension.** Am Pilot-Shop meldet ShopifyQL
   `Column Not Found: Column 'customer_type' not found`, ebenso für
   `returning_customer_type`, `customer_segment` und `billing_customer_type`;
   das `orders`-Dataset ist dort gar nicht ansprechbar
   (`Invalid dataset in FROM clause - orders`). Bei diesem Fehler höchstens
   diese Alternativen durchprobieren, dann aufhören: `"customer_type": null`
   plus Note, die Repeat-Rate entfällt im Report. Nie aus einem anderen Schema
   zusammenrechnen, das wäre eine andere Kennzahl unter demselben Namen.

   **Kohorten und Repeat-Rate ausschließlich aus aggregierten Abfragen wie
   dieser.** Verboten: kein Bestell-Export auf Zeilenebene, keine Namen, keine
   Adressen, keine Mailadressen im Snapshot (Spec Abschnitt 13). `reporting/`
   wird ins Git-Repository des Kunden committet; eine Bestellzeile mit
   Klardaten wäre dort ein Datenleck, kein Zwischenstand. Die ShopifyQL-
   Aggregation oben liefert nur `customer_type`, `orders` und `total_sales` je
   Zeile, nie ein personenbezogenes Feld, und das bleibt auch dann so, wenn
   `read_all_orders` künftig eine Kohorten-Zeitreihe über die volle Historie
   liefert.

   **Top-Collections:** in der ShopifyQL-Doku-Recherche wurde keine
   Collection-Dimension im `sales`-Schema gefunden (Dimensionen dort:
   `product_title`, `product_type`, `sales_channel`, Länder, Kundentyp). Vor
   dem Aufgeben die aktuelle Schema-Referenz prüfen
   (shopify.dev/docs/api/shopifyql, Abschnitt Schemas); gibt es keine
   Dimension, `"top_collections": null` plus Note. Machbarkeit wird im Pilot
   validiert.

**Der Zielordner kommt vom Aufrufer.** Solo ist `reporting/data/<heute>` der
sinnvolle Vorgabewert. **Innerhalb eines Audit- oder Report-Laufs ist es
`reporting/data/<run-id>`**, also Datum plus Kadenz (`2026-10-01-audit`,
`2026-11-01-month`). Der Orchestrator gibt den Ordner vor; wer den Pull
während eines Laufs von Hand startet, muss dieselbe Lauf-ID verwenden. Ein
Snapshot im falschen Ordner ist für die Analyse nicht vorhanden, und sie meldet
keinen Fehler, sondern rechnet ohne ihn weiter.

5. Snapshot schreiben: `reporting/data/<heute>/shopify.json`, im Puls-Modus
   `shopify-pulse.json` (granularity `week`). Diese Session schreibt das JSON
   selbst aus den CLI-Antworten, exakt nach dem Schema unten.
6. Kernzahlen an den Nutzer melden: Umsatz, Bestellungen, AOV, Sessions und
   Conversion Rate (falls vorhanden), Top-Produkt, Repeat-Rate (falls
   `customer_type` da ist), Add-to-Cart-Sessions, Abandoned Carts und
   die Verfügbarkeits-Quote. Bei Vergleich die Richtung (mehr/weniger) dazu.
   Widerspricht die zugeordnete Conversion der Bestellzahl, das ausdrücklich
   melden statt es im Snapshot zu vergraben.

## Snapshot-Schema

`reporting/data/<heute>/shopify.json` (bzw. `shopify-pulse.json`). Die
Kern-Felder `period`, `totals`, `by_month`, `top_products`, `top_collections`,
`sessions`, `session_funnel`, `abandoned_checkouts`, `orders_by_source`,
`products`, `availability` und `customer_type` sind immer vorhanden,
gescheiterte Teile als `null`; `comparison` steht nur beim Erstlauf drin,
`notes` nur, wenn mindestens ein Feld genullt wurde:

```json
{
  "period": {"start": "2026-07-01", "end": "2026-07-31", "granularity": "month"},
  "totals": {"total_sales": 0, "net_sales": 0, "orders": 0, "average_order_value": 0},
  "by_month": [
    {"month": "2026-07", "total_sales": 0, "net_sales": 0, "orders": 0}
  ],
  "top_products": [
    {"product_title": "Outdoorjacke", "net_sales": 0, "orders": 0, "total_inventory": 0, "status": "ACTIVE"}
  ],
  "top_collections": null,
  "sessions": {"sessions": 0, "conversion_rate": 0.0},
  "session_funnel": {
    "sessions": 1782, "sessions_with_cart_additions": 9,
    "sessions_that_reached_checkout": 2, "conversion_rate": 0.0016835
  },
  "abandoned_checkouts": {
    "count": 1, "total_value": 24.9, "currency": "EUR",
    "items": [{"created_at": "2026-07-22", "total": 24.9, "line_items": ["Hammerring"]}]
  },
  "orders_by_source": [{"source_name": "web", "orders": 10}],
  "products": [
    {"product_title": "Beispielartikel", "handle": "beispielartikel", "status": "ACTIVE", "total_inventory": 12, "tracks_inventory": true}
  ],
  "availability": {
    "active_products": 174, "variants_total": 3370, "variants_available": 3323,
    "products_fully_unavailable": 1, "products_partially_available": 13,
    "zero_stock_active": 120, "zero_stock_still_buyable": 119,
    "fully_unavailable_titles": ["Beispielartikel Vier"],
    "partially_available": [
      {"title": "Hoodie, Grau", "available_variants": 1, "total_variants": 8}
    ]
  },
  "customer_type": [
    {"customer_type": "first-time", "orders": 0, "total_sales": 0},
    {"customer_type": "returning", "orders": 0, "total_sales": 0}
  ],
  "notes": {
    "top_collections": "keine Collection-Dimension im sales-Schema",
    "order_history": "Historie auf 60 Tage begrenzt, read_all_orders fehlt"
  },
  "comparison": {"totals, by_month, top_products, sessions, session_funnel, abandoned_checkouts, customer_type plus eigener period, nur beim Erstlauf": "..."}
}
```

- `by_month` heißt in beiden Läufen so (einheitliches Schema); im Puls trägt
  jede Zeile `"date"` statt `"month"` und die Reihe ist täglich.
- `products` ist die Vollerhebung über alle aktiven Produkte, `availability`
  die daraus gerechneten Aggregate, `customer_type` die Kundentyp-Zeilen wie
  von ShopifyQL geliefert. Alle drei sind im Puls `null` plus Note ("im Puls
  nicht gezogen"): Repeat-Rate, Verfügbarkeit und Sortiments-Diagnosen sind
  Monats-Diagnosen. `session_funnel` und `abandoned_checkouts` laufen dagegen
  auch im Puls mit, sie sind billig und tragen die Kaufweg-Aussage.
- `notes` hält je genulltem Feld eine Begründung und entfällt, wenn nichts
  `null` ist. Ausnahme `order_history`: der Historie-Check (Ablauf Schritt 2)
  schreibt diese Note auch dann, wenn kein Feld selbst `null` wurde, weil eine
  60-Tage-Baseline für sich genommen kein leeres Feld ist, sondern ein
  verkürzter Zeitraum.
- **`notes` nimmt außerdem jede methodische Abweichung auf, auch wenn das Feld
  gefüllt ist.** Ein Audit über die volle Historie produziert davon
  zwangsläufig welche: ein erhöhtes `LIMIT`, ein über Differenz ermittelter
  Quellname, ein Zeitraum, den die API kürzer vorhält als angefragt, zwei
  Felder mit verschiedenen Anfangsdaten. Wer sie weglässt, liefert einen
  Snapshot, dessen Zahlen stimmen und dessen Bedeutung niemand mehr
  rekonstruiert. Der Schlüssel heißt wie das betroffene Feld.
- Der `comparison`-Block liegt immer in derselben Datei, nie als eigene Datei
  oder eigener Ordner, und trägt einen eigenen `period` bei gleicher Struktur.
  Er enthält `customer_type` (damit die Repeat-Rate ein Delta bekommt),
  `session_funnel` und `abandoned_checkouts`, aber kein `top_collections`, kein
  `products`, kein `availability` und keinen Bestand: `total_inventory`,
  `status` und die Verfügbarkeit sind Momentaufnahmen von heute und gehören nur
  in den Hauptteil. Scheitert
  ein Teil-Pull des Vergleichsmonats, wird das Feld auch im `comparison`
  `null` und der Grund steht in einem eigenen `notes`-Eintrag innerhalb von
  `comparison`. Puls-Dateien überschreiben nie die Monats-Vergleichsbasis.

## Setup-Check

Kein Script, drei Prüfungen für den Setup-Wizard:

1. `shopify version` läuft (CLI installiert).
2. `shopify store auth list --json` enthält die `shopify_store`-Domain aus der
   Config.
3. Mini-Query als Test-Call, Exit 0 und leere `parseErrors` heißt ok:

   ```bash
   shopify store execute --store <shopify_store> --json --query 'query {
     shopifyqlQuery(query: """FROM sales SHOW total_sales SINCE -1d""") { parseErrors }
   }' 2>/dev/null
   ```

## Fehlerbilder

- `command not found: shopify`: `npm install -g @shopify/cli@latest`, dann
  erneut.
- Store fehlt in `auth list` oder der Online-Token (etwa 24h) ist abgelaufen:
  Auth nach der Scope-Regel oben, immer mit der Union, nie narrow.
- Access denied bei `shopifyqlQuery`: dem Grant fehlt `read_reports`; bei der
  Produkt-Query fehlt `read_products`. Re-Auth mit Union.
- `read_all_orders` steht nicht im Grant, obwohl die Union es angefragt hat:
  der Zustimmungsdialog hat den Scope stillschweigend verweigert. Re-Auth
  bringt hier nichts, solange die Freigabe fehlt; `"Historie auf 60 Tage
  begrenzt, read_all_orders fehlt"` melden und `notes.order_history` in den
  Snapshot schreiben, kein Absturz.
- `parseErrors` nicht leer: die ShopifyQL-Query ist ungültig, gegen die
  ShopifyQL-Referenz (shopify.dev/docs/api/shopifyql) korrigieren und erneut.
- `sessions` liefert Fehler oder keine Zeilen: plan-abhängig, `"sessions": null`
  plus Note, Report verweist auf GA4. Nicht fatal.
- `customer_type` liefert Fehler oder keine Zeilen: `"customer_type": null` plus
  Note, die Repeat-Rate entfällt im Report. Nicht fatal.
- Einzelner Teil-Pull kaputt: Feld wird `null` plus Note, die übrigen Teile
  laufen weiter. Nur wenn CLI oder Auth komplett fehlen, gilt die Quelle als
  "nicht verfügbar".
- Shell-Quoting: Queries mit einfachen Anführungszeichen oder mit Datums-Filtern
  (`sessions`, `abandonedCheckouts`, `orders`) immer per `--query-file`. In
  einer `--query`-Zeichenkette zerlegt die Shell das `SINCE ... UNTIL ...` und
  ShopifyQL antwortet mit einem ANTLR-Syntaxfehler, der wie ein Query-Fehler
  aussieht, aber keiner ist.

  **Diese Regel gewinnt gegen die Beispiele im Ablauf.** Die Umsatz-, Zeitreihen-
  und Top-Produkt-Queries dort zeigen `SINCE`/`UNTIL` inline in `--query`, weil
  sie ohne einfache Anführungszeichen auskommen und in dieser Form auch laufen.
  Wer sich das nicht Zeichen für Zeichen ansehen will, nimmt für **jede** Query
  mit Datumsgrenzen `--query-file`; das ist immer richtig und spart die
  Unterscheidung.
- Ein Top-Produkt ohne Bestand nach dem Titel-Match: nicht auf `null` stehen
  lassen, sondern gezielt per `query: "title:*<Titel>*"` nachfragen. Ein
  unbekannter Bestand beim Umsatzträger ist der Fall, in dem der Report am
  meisten wert wäre.
- Am Pilot-Shop bestätigt (nicht mehr offen): der `shopifyqlQuery`-Wrapper ist
  der richtige Weg, rohes ShopifyQL an `--query` ist nicht dokumentiert; das
  `sessions`-Schema liefert Daten inklusive der beiden Kaufweg-Stufen; eine
  Collection-Dimension gibt es nicht, `top_collections` bleibt `null`;
  `customer_type` existiert dort nicht und die Repeat-Rate entfällt.
