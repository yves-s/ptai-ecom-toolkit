---
name: pull-dfs-backlinks
description: Das Backlinkprofil einer Domain über DataForSEO ziehen (Bestand, verweisende Domains, Ankertexte) plus den normalisierten Autoritäts-Score und den Toxizitäts-Score im Vergleich zu den Wettbewerbern, Ergebnis als Snapshot. Nutzen, wenn ein Audit den Baseline-Block SEO Sichtbarkeit braucht oder der Nutzer wissen will, wie stark und wie sauber das Linkprofil ist. Kostet Geld je Aufruf, Deckel aus config.json > dfs_budget_usd. Liest reporting/config.json und .env im Kunden-Workspace.
---

# pull-dfs-backlinks: Linkprofil, Autorität und Toxizität

Zieht das Backlinkprofil und die beiden Kennzahlen, die im Vergleich mit
Semrush und Ahrefs den Ausschlag geben.

## Gegen echte Antworten geprüft, und das hat sich gelohnt

Am 07.09.2026 alle vier Endpunkte echt aufgerufen und als Fixtures abgelegt
(rund 0,10 USD). **Der Abgleich hat einen Fehler gefunden, der eine zu hundert
Prozent falsche Zahl erzeugt hätte:**

Ein Feld `dofollow` gibt es an den verweisenden Domains **nicht**. Die Items
führen `referring_pages` und `referring_pages_nofollow`. Der erste Entwurf las
`dofollow`, bekam in jeder Zeile `falsy` und schrieb eine Dofollow-Quote von
**0,0** für ein Profil, dessen Links zu **83 Prozent** folgen. Im Report hätte
das als "kein einziger Link folgt" gestanden, also als schwerer Befund, und
niemandem wäre es aufgefallen.

## Warum Autorität und Toxizität mitmüssen

Der Benchmark gegen Semrush und Ahrefs (interne Endpoint-Bewertung vom
12.08.2026) ergab: rohe
Backlink-Zahlen sagen wenig. Den Ausschlag geben zwei andere Kennzahlen, und
DataForSEO hat für beide ein Äquivalent.

Der Unterschied ist nicht kosmetisch. Im Testfall lag der Autoritäts-Score der
Brand deutlich hinter den Wettbewerbern, aber **nicht in einer anderen Liga**,
wie es die reinen Traffic-Zahlen nahegelegt hatten: der Rückstand war real und
aufholbar. Der Toxizitäts-Score dagegen war der **höchste im Feld**, um ein
Vielfaches über dem stärksten Wettbewerber. Daraus folgt eine andere Maßnahme
als aus "zu wenig Autorität": erst das Profil bereinigen, dann aufbauen. Ohne
die zweite Kennzahl hätte der Report die falsche Empfehlung gegeben, und zwar
mit Zahlen belegt.

## Fünf Endpunkte, rund 0,12 USD

| Teil | Endpunkt | Kosten | Wofür |
|---|---|---:|---|
| Profil | `backlinks/summary/live` | 0,024 USD | Bestand, Link-Typen, defekte Links |
| Domains | `backlinks/referring_domains/live` | 0,024 USD plus Zeilen | verweisende Domains |
| Anker | `backlinks/anchors/live` | 0,024 USD plus Zeilen | Ankertext-Verteilung |
| Autorität | `backlinks/bulk_ranks/live` | 0,024 USD je 5 Domains | eigener Score gegen Wettbewerber |
| Toxizität | `backlinks/bulk_spam_score/live` | 0,024 USD je 5 Domains | Disavow-Bedarf statt Linkaufbau |

Kadenz quartalsweise. Nur das Summary ist fatal: die vier übrigen scheitern
isoliert, der Snapshot ist dann ohne den jeweiligen Teil geschrieben.

## Voraussetzungen

- `reporting/config.json` mit `domain`, `competitors`, `dfs_budget_usd`,
  `sources.backlinks` nicht `false`
- `PTAI_DFS_LOGIN` und `PTAI_DFS_PASSWORD` in der `.env` des Workspace oder
  zentral in `~/.config/ptai-ecom/.env`

## Ablauf

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/pull-dfs-backlinks/scripts/backlinks_pull.py" \
  --target <domain ohne Protokoll> \
  --competitors "<competitors, kommagetrennt, höchstens vier>" \
  --workspace . --out "reporting/data/<run-id>" \
  --run-id <run-id> --run-date <YYYY-MM-DD> \
  --account-slug <account_slug> --budget-cap <dfs_budget_usd> \
  --location-code <market.location_code> --language-code <market.language_code>
```

**Ohne Wettbewerber ist der Autoritäts-Score keine Aussage.** Ein Wert von 154
sagt nichts; gegen 391 und 423 wird daraus "der Rückstand ist real und
aufholbar". Die eigene Domain ist im Snapshot mit `own: true` markiert, damit
die Analyse sie findet.

## Snapshot-Schema

`<out>/dfs-backlinks.json`:

```json
{
  "summary": {"backlinks", "referring_domains", "referring_main_domains",
               "referring_ips", "rank", "broken_backlinks", "broken_pages",
               "link_types", "referring_domains_nofollow"},
  "summary_domains": {"referring_domains_returned": 310, "dofollow_share": 0.83,
                       "domains_without_follow_data": 0},
  "referring_domains_top": [{"domain", "backlinks", "rank", "follows",
                              "referring_pages", "referring_pages_nofollow",
                              "spam_score", "first_seen"}],
  "referring_domains_truncated": true,
  "summary_anchors": {"anchors_returned": 480},
  "anchors_top": [{"anchor", "backlinks", "referring_domains"}],
  "authority": [{"domain", "rank", "own"}],
  "spam_score": [{"domain", "spam_score", "own"}],
  "notes": []
}
```

**Quoten gehen über die volle Menge, nie über die gekürzte Liste.**
`dofollow_share` rechnet über alle gelieferten Domains, die Liste ist auf 200
gekappt. Eine Quote über einen Ausschnitt wäre eine andere Zahl mit demselben
Namen.

**Eine Domain folgt, wenn mindestens eine ihrer Seiten folgt**, also wenn
`referring_pages` größer ist als `referring_pages_nofollow`. Fehlen beide
Felder, ist es unbekannt: die Domain zählt dann weder als folgend noch als
nicht folgend, sondern in `domains_without_follow_data`. Weder 1 noch 0 wäre
hier eine Messung.

**Ohne verweisende Domains gibt es keine Dofollow-Quote**, also `null` statt 0.
Eine 0 läse sich als "keine einzige folgt".

**Beim Toxizitäts-Score heißt `null` nicht gemessen und `0` sauber.** Der
Unterschied entscheidet, ob eine Disavow-Empfehlung im Report steht.

**Ein leeres Ergebnis ist ein Befund.** Eine Domain ohne Backlinks hat keine;
der Snapshot trägt dann Nullen und einen Vermerk, kein Fehler.

## Was die Aufnahme bestätigt hat

- **Die Verschachtelung ist festgeschrieben:** `referring_domains`, `anchors`,
  `bulk_ranks` und `bulk_spam_score` liefern unter `result[0].items`, nur
  `summary` ist flach. `_items()` liest jetzt genau diese Form; die frühere
  Toleranz für zwei Formen ist raus, weil eine Funktion, die zwischen zweien
  rät, später eine dritte verdeckt.
- **Der Autoritäts-Score läuft bis 1.000**, bestätigt an zwei großen
  Vergleichsdomains (680 und 812). Auf einer 0-bis-100-Skala gelesen würde die
  Verwechslung aus einem schwachen Profil ein starkes machen.
- **Alle übergebenen Domains kommen zurück**, drei von drei.
- **Der Toxizitäts-Score kommt als ganze Zahl von 0 bis 100.**
- Preis: **0,024 USD je Aufruf**, fünf Aufrufe also rund 0,12 USD.
  `ESTIMATE_USD["backlinks"]` steht auf 0,15 mit Zuschlag.

## Wogegen geprüft, und was offen bleibt

Die **Struktur** ist an echten Antworten geprüft (siehe oben). Die **Zahlen**
sind es nur teilweise:

| Frage | Stand |
|---|---|
| Skala des Autoritäts-Scores | geprüft: bis 1.000, an zwei großen Vergleichsdomains (680 und 812) |
| Kommen alle übergebenen Domains zurück? | geprüft: drei von drei |
| Dofollow-Quote | jetzt korrekt gerechnet, aber gegen keine zweite Quelle gehalten |
| Zahl der verweisenden Domains | **offen** |

**Der Abgleich der Domain-Zahl geht nicht über die API.** Die
Search-Console-API kennt keinen Endpunkt für den Links-Bericht; er steht nur in
der Oberfläche. Der Vergleich ist deshalb ein manueller Schritt: in der Search
Console unter Links die Zahl der verweisenden Domains ablesen und gegen
`summary.referring_domains` halten.

DataForSEO findet in der Regel **mehr** als die Search Console, weil es einen
eigenen Index hat. Findet es **weniger**, stimmt etwas nicht: entweder ist
`target` falsch geschrieben (mit `www.`, mit Protokoll) oder
`backlinks_status_type` filtert mehr weg als gedacht.

## Fehlerbilder

- **Budgetdeckel erreicht:** Abbruch vor dem Aufruf, Quelle "nicht verfügbar".
- **Ein Teil scheitert:** nur das Summary ist fatal, die übrigen vier hinterlassen
  eine Warnung und einen Snapshot ohne diesen Teil.
- **Keine Wettbewerber in der Config:** Autorität und Toxizität kommen nur für
  die eigene Domain zurück. Das ist ein Wert ohne Maßstab; die Analyse muss ihn
  als solchen behandeln.
