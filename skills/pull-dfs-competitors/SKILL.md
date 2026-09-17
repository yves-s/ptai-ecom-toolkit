---
name: pull-dfs-competitors
description: Wettbewerber einer Brand über die SERP-Überschneidung der Kategorie-Keywords ermitteln und optional die Keyword-Lücken zum stärksten Wettbewerber ziehen, Ergebnis als Snapshot. Nutzen, wenn ein Audit die Wettbewerberliste braucht, wenn der Nutzer wissen will, wer für die Kategorie-Begriffe rankt, oder wenn ein Content-Gap gefragt ist. Kostet Geld je Aufruf, Deckel aus config.json > dfs_budget_usd. Liest reporting/config.json und .env im Kunden-Workspace.
---

# pull-dfs-competitors: Wettbewerber und Keyword-Lücken

Ermittelt, wer für die Kategorie-Keywords der Brand rankt, und liefert auf
Wunsch die Keywords, für die der stärkste Wettbewerber rankt und die eigene
Domain nicht.

## Gesät wird mit Keywords, nicht mit der eigenen Domain

Es gibt zwei Endpunkte, die beide "Wettbewerber" liefern und gleich viel
kosten. Die interne Exploration vom 12.08.2026 hat sie gegeneinander laufen
lassen:

| Endpunkt | Gesät mit | Ergebnis im Test | Urteil |
|---|---|---|---|
| `serp_competitors/live` | Kategorie-Keywords | 8 von 9 Wettbewerbern aus der manuellen Analyse wiedergefunden, plus zwei neue | **der richtige Weg** |
| `competitors_domain/live` | der eigenen Domain | ein soziales Netz, eine Stadt-Domain, eine Auktionsplattform | Rauschen |

Der Grund ist strukturell, kein Zufall: `competitors_domain` sucht Domains mit
Überschneidung im **eigenen** Ranking-Set. Ist das dünn, und bei einer Brand,
die noch nicht rankt, ist es das immer, dann überschneidet sich die eigene
Handvoll Marken-Keywords vor allem mit den Plattformen, auf denen die Marke ein
Profil hat. Genau bei der Brand, für die man Wettbewerber sucht, versagt der
Endpunkt also am zuverlässigsten. **Diese Skill benutzt ihn deshalb nicht.**

## Voraussetzungen

- `reporting/config.json` mit `domain`, `market`, `geo_queries.category`
  (die Seed-Keywords), `dfs_budget_usd`, `sources.competitors` nicht `false`
- `PTAI_DFS_LOGIN` und `PTAI_DFS_PASSWORD` in der `.env` des Workspace oder
  zentral in `~/.config/ptai-ecom/.env`

## Kosten

| Teil | Endpunkt | Kosten |
|---|---|---:|
| Wettbewerber | `serp_competitors/live` | 0,014 USD |
| Keyword-Lücken | `domain_intersection/live` | 0,016 USD, nur mit `--with-gaps` |

Kadenz quartalsweise. Der Deckel kommt aus `dfs_budget_usd` und wird vor jedem
Aufruf geprüft; jeder Aufruf schreibt eine Zeile in `reporting/dfs-ledger.jsonl`.

`--with-gaps` ist aus, weil der Audit zuerst die Liste braucht: die Lücken sind
die Analyse darauf und setzen voraus, dass ein Wettbewerber benannt ist.

## Ablauf

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/pull-dfs-competitors/scripts/competitors_pull.py" \
  --target <domain ohne Protokoll> \
  --seed-keywords "<geo_queries.category, kommagetrennt>" \
  --workspace . --out "reporting/data/<run-id>" \
  --run-id <run-id> --run-date <YYYY-MM-DD> \
  --account-slug <account_slug> --budget-cap <dfs_budget_usd> \
  --location-code <market.location_code> --language-code <market.language_code>
```

**Markenbegriffe gehören nicht in die Seeds.** Wer mit dem eigenen Markennamen
sät, bekommt die Plattformen zurück, auf denen die Marke ein Profil hat. Kommen
ausschließlich Plattformen zurück, sagt der Snapshot das in `notes`, und die
richtige Reaktion ist, mit Kategorie-Begriffen erneut zu säen.

## Snapshot-Schema

`<out>/dfs-competitors.json`:

```json
{
  "summary": {"competitors_found": 84, "competitors_delivered": 20,
               "competitors_without_platforms": 18, "seed_keywords": ["..."]},
  "competitors": [{"domain", "avg_position", "median_position", "rating",
                    "etv", "keywords_count", "visibility", "is_platform"}],
  "competitors_truncated": false,
  "keyword_gaps": [{"keyword", "search_volume", "competitor_rank", "competitor_url"}],
  "summary_gaps": {"keyword_gaps_found": 436, "keyword_gaps_delivered": 30,
                    "compared_against": "wettbewerb-a.example"},
  "notes": []
}
```

**Drei Zahlen, weil es drei verschiedene sind.** `competitors_found` ist der
Bestand laut API, `competitors_delivered` die Liefermenge dieses Aufrufs, und
`competitors_truncated` sagt nur, ob **diese Skill** danach noch gekürzt hat.
Ohne die mittlere Zahl liest sich "84 gefunden, 20 gelistet, nicht gekürzt" wie
ein Widerspruch.

**Sortiert nach `avg_position`, aufsteigend**, nicht nach der Reihenfolge der
API. Der Audit will die stärksten zuerst, und wer sich auf die API-Reihenfolge
verlässt, bekommt sie irgendwann anders und merkt es nicht. Eine Domain ohne
Position sortiert ans Ende.

**Plattformen werden markiert, nicht gelöscht.** Dass ein Marktplatz auf den
Kategorie-Keywords vor der Brand steht, ist selbst ein Befund. `is_platform`
trennt sie, `competitors_without_platforms` zählt die echten Shops.

**Die eigene Domain fliegt raus.** Der Endpunkt liefert sie mit, sobald sie für
die Seeds rankt; bliebe sie drin, stünde der Shop im Report als sein eigener
Wettbewerber.

## Die Richtung der Keyword-Lücken ist der Inhalt

`intersections: false` liefert Keywords, für die **`target1` rankt und
`target2` nicht**. Eine Content-Lücke ist "der Wettbewerber rankt, wir nicht",
also steht der **Wettbewerber auf `target1`** und die eigene Domain auf
`target2`. Vertauscht liefert derselbe Aufruf die eigenen Stärken, und die
stünden dann unter der Überschrift "Keyword-Lücken" im Report.

Aus demselben Grund kommt die Position aus `first_domain_serp_element`:
`second_domain_serp_element` ist in dieser Konstellation in jeder Zeile `null`,
weil die eigene Domain dort gerade nicht rankt. Wer es liest, bekommt eine
Spalte, die immer leer ist.

Die Lücken laufen nur gegen einen **Shop**, nie gegen eine Plattform. Gegen
einen Marktplatz gerechnet ist die Liste wertlos, und der Pull überspringt sie
dann mit einer Warnung.

## Die Liste ist ein Vorschlag, keine Entscheidung

Welche Domains als Wettbewerber gelten, entscheidet der Mensch, und die
Entscheidung wird laut Spec Abschnitt 10 mit der Baseline eingefroren. Diese
Skill schreibt **nie** in `config.json > competitors`.

## Fehlerbilder

- **Budgetdeckel erreicht:** Abbruch vor dem Aufruf, Quelle "nicht verfügbar
  (Budgetdeckel)", der Lauf geht weiter.
- **Keine Seed-Keywords:** Abbruch mit Meldung. Ein leerer Aufruf kostet
  dasselbe wie ein voller.
- **Nur Plattformen im Ergebnis:** kein Fehler, sondern ein Vermerk in `notes`
  plus der Hinweis, mit Kategorie-Begriffen erneut zu säen.
- **Kein Shop für die Lücken:** die Lücken werden übersprungen, der
  Wettbewerber-Teil bleibt erhalten.
