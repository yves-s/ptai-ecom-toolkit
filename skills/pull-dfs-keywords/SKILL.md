---
name: pull-dfs-keywords
description: Suchvolumen, Wettbewerb und Klickpreis für eine Begriffsliste über DataForSEO ziehen, gespeist aus den Keyword-Seeds der Config und den Top-Queries der Search Console, Ergebnis als Snapshot. Nutzen, wenn ein Audit Volumen zu Katalog- und Kategoriebegriffen braucht oder der Nutzer wissen will, wie oft nach etwas gesucht wird. Kostet Geld je Anfrage, nicht je Keyword; Deckel aus config.json > dfs_budget_usd. Liest reporting/config.json und .env im Kunden-Workspace.
---

# pull-dfs-keywords: Suchvolumen zu einer Begriffsliste

Holt Suchvolumen, Wettbewerbsgrad und Klickpreis zu allen Begriffen, die der
Lauf kennt: den Keyword-Seeds aus der Config und den Top-Queries aus
`gsc.json` desselben Laufs.

## Gegen eine echte Antwort geprüft

Am 07.09.2026 einmal echt aufgerufen und als Fixture abgelegt
(`scripts/tests/fixtures/dfs/search_volume.json`, 0,09 USD). Bestätigt: die
Zeilen kommen **flach in `result`**, nicht verschachtelt, und `tag` wird
gespiegelt.

## Der Preis hängt an der Anfrage, nicht am Keyword

**Der Endpunkt kostet je Anfrage dasselbe, egal ob ein Keyword drin steht oder
tausend.** Deshalb sammelt dieser Pull erst, entdoppelt, und sendet dann in
Blöcken zu 1.000. Ein Aufruf je Keyword wäre technisch gleichwertig und
tausendmal so teuer.

Entdoppelt wird ohne Rücksicht auf Groß- und Kleinschreibung: für den Endpunkt
sind "Regenjacke" und "regenjacke" dasselbe Keyword, in zwei Blöcken wären sie
zweimal bezahlt. Begriffe über 80 Zeichen fliegen vorher raus, weil ein Fehler
in der API die ganze bezahlte Anfrage kostet.

## Voraussetzungen

- `reporting/config.json` mit `keyword_seeds`, `market`, `dfs_budget_usd`,
  `sources.dfs_keywords` nicht `false`
- `PTAI_DFS_LOGIN` und `PTAI_DFS_PASSWORD` in der `.env` des Workspace oder
  zentral in `~/.config/ptai-ecom/.env`
- **läuft nach `pull-gsc`**, weil er dessen Top-Queries mitnimmt

## Ablauf

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/pull-dfs-keywords/scripts/keywords_pull.py" \
  --seeds "<keyword_seeds, kommagetrennt>" \
  --gsc "reporting/data/<run-id>/gsc-max-history.json" \
  --workspace . --out "reporting/data/<run-id>" \
  --run-id <run-id> --run-date <YYYY-MM-DD> \
  --account-slug <account_slug> --budget-cap <dfs_budget_usd> \
  --location-code <market.location_code> --language-code <market.language_code>
```

## Snapshot-Schema

`<out>/dfs-keywords.json`:

```json
{
  "summary": {"keywords_returned": 412, "keywords_with_volume": 380,
               "keywords_without_data": 12, "search_volume_total": 184300},
  "keywords": [{"keyword", "search_volume", "competition", "competition_index",
                 "cpc", "monthly": [{"month": "2026-08", "search_volume"}]}],
  "keywords_truncated": false,
  "notes": ["..."]
}
```

**`search_volume: null` und `search_volume: 0` sind zwei verschiedene
Aussagen.** `null` heißt "Google liefert dafür keine Zahl", `0` heißt "kein
Suchvolumen". Sie werden getrennt gezählt, weil im Report daraus "ungemessen"
oder "toter Begriff" wird, und das ist nicht dasselbe. `keywords_without_data`
ist die erste, `keywords_with_volume` die zweite Sorte.

**Die Zeilen kommen flach in `result`**, nicht verschachtelt unter
`result[0].items` wie bei den DataForSEO-Labs-Endpunkten. Wer hier
`dfs_pull.unwrap()` benutzt, findet nichts und schreibt null Keywords in den
Snapshot.

**Sortiert nach Volumen, absteigend**, ungemessene Begriffe ans Ende. Die
Liste ist auf 1.000 gekappt, `keywords_returned` nennt die volle Menge.

**Ein abgebrochener Block ist eine Lücke, keine Null.** Reißt der Budgetdeckel
mitten in der Blockfolge, steht das in `notes`: die Begriffe der übrigen Blöcke
sind **ungemessen**, nicht ohne Suchvolumen. Was schon gezogen wurde, bleibt im
Snapshot.

## Was die Aufnahme bestätigt hat

- Feldnamen: `keyword`, `search_volume`, `competition`, `competition_index`,
  `cpc`, `monthly_searches` mit `year`, `month`, `search_volume`. Die
  Monatsreihe kam mit zwölf Einträgen zurück.
- Die Zeilen liegen **flach in `result`**. Wer hier `dfs_pull.unwrap()`
  benutzt, findet nichts.
- `tag` wird gespiegelt.
- Preis: **0,09 USD** für vier Keywords, also je Anfrage und nicht je Keyword.
  `ESTIMATE_USD["dfs_keywords"]` steht auf 0,15 mit Zuschlag.

Offen bleibt nur, ob der Preis bei tausend Keywords in einer Anfrage derselbe
ist. Die Doku sagt ja; belegt ist er für vier.

## Fehlerbilder

- **Keine Begriffe:** Abbruch mit Meldung. Eine leere Anfrage kostet dasselbe
  wie eine volle.
- **Budgetdeckel erreicht:** vor dem ersten Block Abbruch, mitten in der
  Blockfolge ein Vermerk plus die schon gezogenen Begriffe.
- **Zugangsdaten fehlen:** Meldung nennt `PTAI_DFS_LOGIN` und
  `PTAI_DFS_PASSWORD`.
