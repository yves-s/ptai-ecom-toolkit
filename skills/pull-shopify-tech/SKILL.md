---
name: pull-shopify-tech
description: Die technische Ausstattung eines Shopify-Shops erfassen (Theme und Version, Skript-Tags, Sprach- und Marktkonfiguration, Zahlungsarten) und dazu die Fremdtechnik aus dem Crawl desselben Laufs, Ergebnis als Snapshot. Nutzen, wenn ein Audit wissen muss, welche Werkzeuge im Shop eingebunden sind, ob doppelt gemessen wird oder welches Theme läuft. Werkzeug ist die Shopify CLI plus die vorhandene crawl.json; liest reporting/config.json im Kunden-Workspace.
---

# pull-shopify-tech: Shop-Technik erfassen

Zwei Quellen, ein Snapshot: was die Admin-API über die Konfiguration weiß, und
was der Crawl über die tatsächlich eingebundene Fremdtechnik gesehen hat.

## Der Crawl wird wiederverwendet, nicht wiederholt

`crawl-site` besucht den Shop in derselben Phase und hält je Seite die
Skript-Quellen (`script_sources`) und die inline eingebauten Container- und
Mess-IDs (`inline_tag_ids`) fest, aggregiert im `findings_index`. Diese Skill
liest daraus.

Ein zweiter Abruf derselben Seiten wäre doppelte Arbeit und könnte einen
**anderen Zustand** sehen als der Crawl, gegen den die technische Analyse
rechnet. Zwei Zustände in einem Lauf sind schlimmer als einer.

Deshalb läuft dieser Pull **nach** `crawl-site`. Fällt der Crawl aus, entsteht
der Snapshot trotzdem, nur ohne den Storefront-Teil, und
`crawl_pages_scanned` steht auf `null`.

## Voraussetzungen

- `reporting/config.json` mit `shopify_store` und `sources.shop_tech` nicht `false`
- Shopify CLI installiert, Store authentifiziert
- Scopes `read_themes`, `read_script_tags`, `read_locales`, `read_markets`

Die Scope- und Union-Regel steht in `pull-shopify/SKILL.md`, ebenso der Umgang
mit der Drosselung: **Exit-Code prüfen, warten, erneut versuchen**, nie eine
leere Antwort als "keine Daten" werten. Beide Shopify-Pulls teilen sich
dasselbe Punktebudget.

Kadenz quartalsweise, die Abfrage ist billig und der Shop ändert sich selten.

## Ablauf

1. Eine Abfrage holt alle Blöcke in einem Zug:

   ```graphql
   query {
     themes(first: 20) { nodes { name role updatedAt } }
     scriptTags(first: 100) { nodes { src displayScope } }
     shopLocales { locale primary published }
     markets(first: 50) { nodes { name enabled primary } }
     shop { name currencyCode ianaTimezone }
   }
   ```

2. Antwort nach `/tmp` schreiben, dann aggregieren:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/pull-shopify-tech/scripts/shop_tech_build.py" \
     --shop /tmp/shop-tech-raw.json \
     --crawl "reporting/data/<run-id>/crawl.json" \
     --out "reporting/data/<run-id>"
   ```

3. Kernzahlen melden: Theme, Zahl der Skript-Tags, Fremd-Hosts, Mess-IDs, und
   jeden Hinweis aus `notes` wörtlich.

**`paymentSettings` gibt es auf `QueryRoot` nicht.** Am 07.09.2026 gegen einen
echten Store geprueft: die Admin-API antwortet mit `undefinedField`, und weil
GraphQL die Abfrage als Ganzes ablehnt, scheitert damit **jeder** Block, nicht
nur dieser eine. Das Feld steht deshalb nicht mehr in der Abfrage oben.

Die Zahlarten sind damit im Audit nicht erhoben, und die Fachsektion Shop im
Kunden-PDF traegt fuer sie "nicht erhoben" statt einer Liste. Wer sie braucht,
prueft zuerst in der aktuellen Schema-Referenz, unter welchem Namen sie heute
erreichbar sind (Kandidaten: `shop.paymentSettings`, oder gar nicht ueber die
Admin-API), und ergaenzt die Abfrage erst danach.

## Feldnamen vor dem ersten Lauf verifizieren

`themes` ist in der Admin-GraphQL erst ab einer bestimmten API-Version
verfügbar, und ob aktive Apps ohne zusätzlichen Scope lesbar sind, ist offen.
Was nicht lesbar ist, kommt **nicht** in die Abfrage, sondern als offener Punkt
in diese Skill. Werkzeug für die Prüfung ist der Shopify-Dev-MCP.

Das Script fängt den Fall ab: ein Block, den die Antwort gar nicht enthält oder
der auf `null` steht, wird zu einem Vermerk in `notes` und **nicht** zu einer
Null. "Keine Skript-Tags installiert" und "nicht lesbar" sind zwei verschiedene
Aussagen, und nur eine davon ist ein Befund. Ein Block, der leer
zurückkommt, ist dagegen eine Messung und bekommt keinen Vermerk.

## Snapshot-Schema

`<out>/shop-tech.json`:

```json
{
  "source": "shop_tech",
  "summary": {"themes_total": 3, "script_tags_total": 4, "locales_total": 2,
               "markets_total": 1, "third_party_script_hosts": 12,
               "inline_tag_ids": 3, "crawl_pages_scanned": 300},
  "theme": {"name": "Dawn", "role": "MAIN", "updated_at": "..."},
  "themes": [{"name", "role"}],
  "script_tags": [{"src", "display_scope"}],
  "locales": [{"locale", "primary", "published"}],
  "markets": [{"name", "enabled", "primary"}],
  "payments": {"supported_digital_wallets": ["..."]},
  "storefront_script_hosts": {"connect.example": 300},
  "storefront_script_hosts_truncated": false,
  "storefront_inline_tag_ids": {"G-XXXX": 300, "GTM-YYYY": 300},
  "notes": []
}
```

**Die Mess-IDs sind der interessantere Teil.** Ein Host sagt, dass ein Anbieter
eingebunden ist; eine ID sagt, **welches Konto**. Zwei GA4-IDs auf denselben
300 Seiten heißen doppelte Messung, und das ist genau die Sorte Befund, nach der
die Analyse Datenqualität sucht. Deshalb steht je ID die Zahl der Seiten dabei:
eine ID auf drei von 300 Seiten ist ein Rest, eine auf allen ist ein aktiver
zweiter Zähler.

**`crawl_pages_scanned: null` heißt "nicht gemessen".** Eine 0 hieße "gecrawlt
und nichts gefunden". Der Unterschied entscheidet, ob die Analyse einen Befund
schreibt oder eine Lücke ausweist.

**Die Host-Liste ist auf 100 gekappt**, `third_party_script_hosts` im
`summary` nennt aber immer die volle Menge, und `_truncated` sagt, ob gekürzt
wurde. Eine gekappte Liste ohne Merker erzeugt eine falsche Zahl: der Leser
hält 100 für alles.

**Skript-Hosts zählen Seiten, nicht Einbindungen.** Zwei Snippets desselben
Anbieters auf einer Seite sind eine Seite. Die Frage lautet, wie weit ein
Anbieter im Shop verbreitet ist.

## Fehlerbilder

- **Gedrosselt:** wie bei `pull-shopify`, warten und erneut versuchen.
- **Block fehlt in der Antwort:** Vermerk in `notes`, kein Nullwert. Meist
  fehlt ein Scope oder der Feldname stimmt für diese API-Version nicht.
- **Kein Crawl im Lauf:** der Storefront-Teil bleibt leer,
  `crawl_pages_scanned` ist `null`, der Rest des Snapshots ist gültig.
