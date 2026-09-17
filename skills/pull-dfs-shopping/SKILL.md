---
name: pull-dfs-shopping
description: Google-Shopping-Präsenz eines Shops und den Preisvergleich gegen die dort gelisteten Anbieter über die DataForSEO Merchant API ziehen, Ergebnis als Snapshot. Nutzen, wenn ein Audit wissen muss, ob die Brand bei Google Shopping überhaupt gelistet ist und zu welchen Preisen der Wettbewerb dort verkauft. Task-basiert mit Wartezeit, kostet Geld je Aufgabe, Deckel aus config.json > dfs_budget_usd. Liest reporting/config.json und .env im Kunden-Workspace.
---

# pull-dfs-shopping: Shopping-Präsenz und Preislandkarte

Fragt je Keyword die Google-Shopping-Ergebnisse ab und beantwortet zwei Dinge:
ist die Brand dort überhaupt gelistet, und wo liegen die Preise des Wettbewerbs.

## Der einzige task-basierte Pull

`task_post` legt je Keyword eine Aufgabe an, danach wird gewartet und mit
`task_get/advanced` abgeholt. **Das Anlegen kostet, das Abholen nicht**, rund
0,001 USD je Aufgabe (gemessen 12.08.2026). Im Ledger steht deshalb eine Zeile
je Post und keine je Abholung.

Er dauert wegen der Wartezeit deutlich länger als die anderen Pulls und gehört
an den **Anfang** von Phase 1, nicht ans Ende. Kadenz quartalsweise.

## Voraussetzungen

- `reporting/config.json` mit `brand`, `market`, `dfs_budget_usd`,
  `sources.shopping` nicht `false` und den Keywords, die geprüft werden sollen
- `PTAI_DFS_LOGIN` und `PTAI_DFS_PASSWORD` in der `.env` des Workspace oder
  zentral in `~/.config/ptai-ecom/.env`

## Ablauf

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/pull-dfs-shopping/scripts/shopping_pull.py" \
  --keywords "<kommagetrennt, höchstens 20>" --brand "<config.brand>" \
  --workspace . --out "reporting/data/<run-id>" \
  --run-id <run-id> --run-date <YYYY-MM-DD> \
  --account-slug <account_slug> --budget-cap <dfs_budget_usd> \
  --location-code <market.location_code> --language-code <market.language_code>
```

## Snapshot-Schema

`<out>/dfs-shopping.json`:

```json
{
  "summary": {"keywords_checked": 1, "offers_total": 40, "own_offers": 0,
               "competitor_offers": 40, "carousel_entries": 3,
               "currencies": ["EUR"], "brand_match": "beispielshop"},
  "keywords": [{"keyword", "offers": [{"seller", "title", "price", "currency",
                                        "old_price", "rank_absolute", "own"}],
                 "offers_truncated": true, "offers_total": 40,
                 "own_price_vs_median": null}],
  "notes": ["..."]
}
```

**Nur `google_shopping_serp` ist ein Angebot.** Die Antwort enthält daneben
`google_shopping_carousel`, das sind Kategoriekacheln ohne Preis und ohne
Verkäufer; in der geprüften Antwort waren 3 von 43 Einträgen solche Kacheln.
Mitgezählt blähen sie die Angebotszahl auf und verwässern genau die Aussage,
für die dieser Pull da ist. Sie stehen deshalb getrennt als
`carousel_entries`, und `own_offers + competitor_offers == offers_total` gilt
ohne sie.

**`own_price_vs_median` ist `null`, wenn es kein eigenes Angebot gibt.** Eine 0
läse sich als "gleich teuer wie der Markt", und das ist etwas ganz anderes als
"gar nicht gelistet". Verglichen wird das **günstigste** eigene Angebot gegen
den Median der übrigen Anbieter, weil der Kunde den günstigsten zuerst sieht.

**Mehrere Währungen sind ein Vermerk.** Ein Preisabstand über zwei Währungen
ist keine Zahl; `currencies` zeigt, was drin war.

**Kein eigenes Angebot ist ein Befund, kein Fehler.** `own_offers: 0` bei
40 fremden Angeboten heißt: der Wettbewerb ist bei Shopping sichtbar und die
Brand nicht. Das ist eine der klarsten Aussagen, die dieser Pull liefert.

## Die Marken-Erkennung ist eine Heuristik

Ob ein Angebot das eigene ist, entscheidet der Markenname aus `config.brand`
gegen das Verkäuferfeld, ohne Rücksicht auf Groß- und Kleinschreibung. Ein Shop,
der unter mehreren Namen oder über Reseller verkauft, wird dabei **unterzählt**.
Der Snapshot sagt das in `notes`, damit die Analyse es nicht als Tatsache liest.

## Fehlerbilder

- **Budgetdeckel erreicht:** Abbruch vor dem `task_post`, kein Geld ausgegeben.
- **Aufgabe abgelehnt:** wird übersprungen und nicht abgefragt. Eine abgelehnte
  Aufgabe ohne Ergebnis würde sonst dreißigmal gepollt und hielte den Lauf zehn
  Minuten auf.
- **Nicht rechtzeitig abgeholt:** die betroffenen Keywords stehen in `notes` als
  **ungemessen**, nicht als "ohne Angebote". Der Unterschied entscheidet, ob
  die Analyse einen Befund schreibt oder eine Lücke ausweist.
