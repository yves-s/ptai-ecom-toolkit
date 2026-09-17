---
name: pull-dfs-rankings
description: Ranking-Keywords einer Domain, Share of Voice gegen die Wettbewerber und optional die Sichtbarkeitshistorie über DataForSEO ziehen und als Snapshot ablegen. Nutzen, wenn ein Audit oder Report den organischen Ranking-Bestand braucht, oder wenn der Nutzer wissen will, für wie viele Keywords ein Shop rankt und wie er gegen den Wettbewerb steht. Kostet Geld je Aufruf, Deckel aus config.json > dfs_budget_usd. Liest reporting/config.json und .env im Kunden-Workspace.
---

# pull-dfs-rankings: Ranking-Bestand und Sichtbarkeit ziehen

Zieht den organischen Ranking-Bestand der Domain, den geschätzten Traffic je
Domain im Vergleich zu den Wettbewerbern und auf Wunsch die
Sichtbarkeitshistorie. Legt alles als einen Snapshot ab. Wird vom Audit-Lauf
aufgerufen, funktioniert aber auch solo.

## Voraussetzungen

Im Kunden-Workspace (aktuelles Arbeitsverzeichnis):

- `reporting/config.json` mit `domain`, `market` (`location_code` und
  `language_code`), `dfs_budget_usd` und `sources.dfs_rankings` nicht `false`;
  `competitors` liefert die Vergleichsdomains für den Share of Voice
- `PTAI_DFS_LOGIN` und `PTAI_DFS_PASSWORD` in der `.env` des Workspace oder
  zentral in `~/.config/ptai-ecom/.env`

Fehlt eins davon oder steht `sources.dfs_rankings` auf `false`: als "nicht
verfügbar (Grund)" melden und aufhören. Nie den Gesamtlauf daran scheitern
lassen.

## Kosten

**Jeder Aufruf kostet Geld, auf Rechnung des Betreibers.** Gemessen am
12.08.2026 (interne Endpoint-Bewertung):

| Teil | Endpunkt | Kosten | Wann |
|---|---|---:|---|
| Bestand | `ranked_keywords/live` | 0,0144 USD | jeder Lauf |
| Share of Voice | `bulk_traffic_estimation/live` | 0,0126 USD je 5 Domains | jeder Lauf |
| Historie | `historical_rank_overview/live` | **0,127 USD** | nur mit `--with-history` |

Die Historie ist die teuerste Labs-Abfrage überhaupt, rund das Neunfache des
Bestands, und die Exploration hat sie ausdrücklich als "einmalig nützlich,
nicht in den Monats-Report" bewertet. Sie gehört in den Erstlauf, nicht in die
Kadenz. Der Share of Voice ist ihr günstiger Ersatz im laufenden Betrieb: die
Zeitreihe entsteht über die Läufe hinweg.

Der Deckel kommt aus `config.json > dfs_budget_usd` und wird **vor** jedem
Aufruf geprüft. Ist er erreicht, bricht der Pull ab, bevor Geld fließt; die
Quelle gilt dann als `skipped` mit Grund, nicht als `failed`. Jeder Aufruf
schreibt eine Zeile nach `reporting/dfs-ledger.jsonl`, mit Tag, Endpunkt und
echtem Betrag.

Der Schalter `--sandbox` läuft gegen `sandbox.dataforseo.com` und kostet
nichts, liefert aber **Dummy-Werte**. Er ist ein Rauchtest der Verkabelung und
nie eine Quelle für Zahlen; ein damit erzeugter Snapshot trägt `"sandbox": true`
und gehört in keinen Kundenordner.

## `top_keywords` sind die besten Positionen, nicht ein Querschnitt

Am 07.09.2026 gegen einen echten Shop gemessen: **alle 500 gelieferten
`top_keywords` lagen in den Top 10**, während der Ranking-Bestand des Shops ein
Vielfaches davon umfasst. Die übrigen Begriffe auf Position 11 bis 100 kommen in
dieser Liste gar nicht vor.

Das macht die naheliegendste Auswertung unmoeglich: eine Chancenliste "knapp
vor Seite eins" laesst sich aus `top_keywords` nicht bilden, und wer es
versucht, bekommt eine leere Tabelle statt einer Fehlermeldung.

**Wer Striking-Distance-Begriffe braucht, nimmt die Search Console.** Dort sind
die Positionen gemessen statt geschaetzt, und die Impressionen sagen, wie viel
an einem Begriff haengt: `gsc.json > top_queries[]` mit `position` zwischen 8
und 25, absteigend nach `impressions`. Das ist der bessere Wert und kostet
nichts extra.

`summary.ranked_keywords_total` bleibt davon unberuehrt: der Bestand ist
vollstaendig gezaehlt, nur die gelieferten Zeilen sind die Spitze davon.

## Ablauf

1. `reporting/config.json` lesen: `domain`, `market`, `competitors`,
   `dfs_budget_usd`. Die Zugangsdaten findet das Skript selbst.
2. Script aufrufen. **Zielordner ist der Daten-Ordner des laufenden Audits**,
   also `reporting/data/<run-id>`:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/pull-dfs-rankings/scripts/rankings_pull.py" \
     --target <domain ohne Protokoll> \
     --competitors "<competitors, kommagetrennt>" \
     --workspace . --out "reporting/data/<run-id>" \
     --run-id <run-id> --run-date <YYYY-MM-DD> \
     --account-slug <account_slug> --budget-cap <dfs_budget_usd> \
     --location-code <market.location_code> --language-code <market.language_code>
   ```

   Optional: `--with-history` für die Sichtbarkeitshistorie (siehe Kosten),
   `--sandbox` für einen Rauchtest ohne Kosten.
3. Kernzahlen an den Nutzer melden: Zahl der Ranking-Keywords, Top-3 und
   Top-10, geschätzter Traffic, Position im Share of Voice, verbrauchter Betrag.

## Snapshot-Schema

`<out>/dfs-rankings.json`:

```json
{
  "source": "dfs_rankings", "endpoint": "...", "tag": "<kunde>/<datum>/dfs_rankings",
  "cost_usd": 0.027, "sandbox": false, "run_id": "...", "pulled_at": "...",
  "summary": {
    "ranked_keywords_total": 396, "ranked_keywords_delivered": 20,
    "top_3": 141, "top_10": 216, "top_100": 396,
    "etv": 13857.4, "is_new": 215, "is_up": 57, "is_down": 20, "is_lost": 0,
    "serp_features_in_sample": {"organic": 20}
  },
  "top_keywords": [{"keyword", "rank_absolute", "rank_group", "search_volume",
                     "cpc", "competition_level", "etv", "url", "serp_type",
                     "last_updated_time"}],
  "top_keywords_truncated": false,
  "share_of_voice": [{"domain", "etv", "ranked_keywords"}],
  "visibility_history": [{"month": "2026-08", "ranked_keywords", "etv"}],
  "notes": ["..."]
}
```

Vier Dinge daran sind nicht selbstverständlich und bestimmen, ob die Zahlen
stimmen:

**`ranked_keywords_total` ist der Bestand, `ranked_keywords_delivered` die
Liefermenge.** Die API gibt je Aufruf höchstens tausend Zeilen zurück, kennt
aber den vollen Bestand. In der geprüften Antwort standen 396 gegen 20. Wer den
Zähler aus der Länge der Liste bildet, meldet die Liefermenge als Bestand, und
zwar plausibel genug, dass es niemand merkt.

**Die Positionsbänder kommen aus `metrics.organic`, nicht aus den Zeilen.**
Die API liefert `pos_1`, `pos_2_3`, `pos_4_10` und so weiter über den vollen
Bestand. Über die gelieferte Teilmenge gezählt käme ein Bruchteil heraus.
Die Bänder der API sind **disjunkt**, im Snapshot stehen sie kumuliert, weil
im Report jeder "Top 3" kumulativ liest.

**Fehlt `metrics.organic`, stehen die Bänder auf `null`, nicht auf 0.** Eine 0
läse sich als "kein einziges Keyword in den Top 3" und wäre ein erfundener
Befund.

**`rank_absolute` ist ein Datenbankwert, keine Live-Position.** Am 12.08.2026
wich er in einem Gegencheck von der Live-SERP ab. Deshalb reist
`last_updated_time` je Keyword mit, und `notes` sagt es noch einmal. Im Report
darf die Zahl nie als tagesaktuelle Position auftreten.

## Wogegen geprüft

Am 07.09.2026 gegen die Search Console derselben Domain gehalten, also gegen
eine zweite, unabhängige Messung derselben Suchleistung. Geprüft wurde an einer
Domain, für die beides vorliegt.

| Frage | Ergebnis |
|---|---|
| Gibt es überhaupt eine Schnittmenge? | Ja. Null Schnittmenge hieße, `location_code` oder `language_code` messen den falschen Markt |
| Liegen die Positionen in derselben Größenordnung? | Ja, Median-Abweichung rund **zwei Ränge** |
| Gibt es Ausreißer? | Ja, einer von zwölf weicht um mehr als 20 Ränge ab |
| Passt das Suchvolumen zu den Impressionen? | Ja, kein einziger Widerspruch: kein Keyword mit Volumen und Top-10-Position hatte null Impressionen |
| Ist `etv` eine Trafficzahl oder ein Preis? | **Trafficzahl.** Die Summe der Zeilen-`etv` ergibt exakt `summary.etv`, und die Größenordnung passt zu den GSC-Impressionen |

**Der Ausreißer ist kein Fehler, sondern die Bestätigung der Einschränkung
oben.** `rank_absolute` ist ein Datenbankwert mit eigenem `last_updated_time`,
keine Live-Position. Bei rund zwei Rängen Median-Abweichung ist er als Trend
brauchbar; als tagesaktuelle Position darf er nie im Report stehen. Dieselbe
Abweichung war schon in der Exploration vom 12.08.2026 aufgefallen.

**Noch nicht gegengeprüft:** die Sichtbarkeitshistorie (`--with-history`)
gegen einen unabhängigen Verlauf. Dafür fehlt eine zweite Quelle mit
Monatsauflösung über denselben Zeitraum.

## Fehlerbilder

- **Budgetdeckel erreicht:** der Pull bricht ab, bevor er aufruft. Die Quelle
  ist "nicht verfügbar (Budgetdeckel)", der Lauf geht weiter.
- **Share of Voice oder Historie scheitern:** der Ranking-Bestand bleibt
  erhalten, der Snapshot ist ohne den jeweiligen Teil geschrieben, eine Warnung
  steht auf der Konsole.
- **Zugangsdaten fehlen:** Meldung nennt `PTAI_DFS_LOGIN` und
  `PTAI_DFS_PASSWORD`, Exit ungleich 0.
- **Leeres Ergebnis:** ein Shop ohne Rankings hat schlicht keine. Der Snapshot
  trägt dann `ranked_keywords_total: 0` und eine leere Liste, das ist ein
  Befund und kein Fehler.
