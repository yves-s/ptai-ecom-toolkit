---
name: pull-gsc
description: Search-Console-Daten für den Kunden-Report oder den Wochen-Puls ziehen (Top-Queries, Top-Seiten, Tagesreihe, Sitemaps, Index-Stichprobe) und als Snapshot ablegen. Nutzen, wenn ein Monats-Report oder Puls GSC-Zahlen braucht, oder wenn der Nutzer explizit Search-Console- bzw. GSC-Daten für einen Zeitraum abrufen will. Liest reporting/config.json und .env im Kunden-Workspace.
---

# pull-gsc: Search-Console-Snapshot ziehen

Zieht per Search Console API die Suchleistung (Top-Queries, Top-Seiten, Tagesreihe)
für einen Zeitraum plus den Indexierungs-Stand (Sitemaps, URL-Stichprobe) und legt
alles als Snapshot im Kunden-Workspace ab. Wird vom Report- und Puls-Lauf
aufgerufen, funktioniert aber auch solo.

## Voraussetzungen

Im Kunden-Workspace (aktuelles Arbeitsverzeichnis):

- `reporting/config.json` mit `gsc_site` (z. B. `sc-domain:example.de`) und
  `sources.gsc` nicht `false`; `cwv_urls` liefert die Index-Stichprobe
- `.env` im Workspace-Root mit `PTAI_GOOGLE_CREDENTIALS` (Pfad zum Service-Account-JSON)

Fehlt eins davon oder steht `sources.gsc` auf `false`: GSC als "nicht verfügbar (Grund)"
melden und aufhören. Nie den Gesamtlauf (Report/Puls) daran scheitern lassen.

## Ablauf

1. `reporting/config.json` lesen (`gsc_site`, `cwv_urls`), `.env` sourcen
   (`PTAI_GOOGLE_CREDENTIALS`).
2. Zeitraum bestimmen. Default ist der letzte volle Monat (Erster bis Letzter des
   Vormonats). Puls-Modus: letzte volle Woche, Montag bis Sonntag.
3. Vergleichszeitraum nur beim Erstlauf: existiert bereits ein Vormonats-Snapshot
   (jüngster `reporting/data/`-Ordner, dessen `gsc.json` einen `period` mit
   granularity `month` über den vollen Vormonat trägt; `-pulse`-Dateien ignorieren),
   dann keinen Vergleich mitziehen, der Report vergleicht gegen den Snapshot.
   Existiert keiner, den Monat davor als `--compare-start/--compare-end` mitgeben.
4. Script aufrufen. **Zielordner ist der Daten-Ordner des laufenden Audits oder
   Reports**, also `reporting/data/<run-id>`; ohne Lauf-ID gilt der heutige
   Daten-Ordner wie im Beispiel (Abschnitt Snapshot-Schema). Die `--inspect-urls`
   sind die `cwv_urls` aus der Config (gleiche Stichprobe wie beim CWV-Pull, keine
   zweite Liste pflegen), kommagetrennt in einem Argument:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/pull-gsc/scripts/gsc_pull.py" \
     --site <gsc_site> \
     --creds "$PTAI_GOOGLE_CREDENTIALS" \
     --start YYYY-MM-01 --end <letzter Tag des Monats> \
     --inspect-urls "<cwv_urls, kommagetrennt>" \
     --out "reporting/data/$(date +%F)"
   ```

   Optional dazu: `--compare-start YYYY-MM-DD --compare-end YYYY-MM-DD` (Erstlauf),
   `--pulse` (Wochen-Puls, schreibt `gsc-pulse.json` mit granularity `week`),
   `--max-history` für einen einmaligen Baseline-Pull über die ganze vorhandene
   Historie: `--start` entfällt dabei, das Script ermittelt es selbst und schreibt
   `gsc-max-history.json` mit granularity `max_history`. Schließt sich mit `--pulse`
   und `--compare-start`/`--compare-end` aus.
5. Kernzahlen an den Nutzer melden: Klicks, Impressionen, CTR, Position, Top-Query,
   Auffälligkeiten in der Index-Stichprobe (alles, was nicht indexiert ist). Bei
   Vergleich die Richtung (mehr/weniger) dazu.

## Snapshot-Schema

**Der Zielordner kommt vom Aufrufer.** Solo ist `reporting/data/<heute>` der
sinnvolle Vorgabewert, und `report` und `pulse` legen ihre Snapshots dort ab,
solange sie ohne Lauf-ID laufen (Spec Abschnitt 14, Umstellung in Stufe 3).
**Läuft der Pull dagegen in einem Audit oder Report mit Lauf-ID, ist der
Zielordner `reporting/data/<run-id>`**, also Datum plus Kadenz
(`2026-10-01-audit`, `2026-11-01-month`), und `--out` zeigt dorthin. Der
Orchestrator gibt den Ordner vor; wer den Pull während eines Laufs von Hand
startet, muss dieselbe Lauf-ID verwenden. Ein Snapshot im falschen Ordner ist
für die Analyse nicht vorhanden, und sie meldet keinen Fehler, sondern rechnet
ohne ihn weiter.

Das Script schreibt `<out>/gsc.json` (bzw. `gsc-pulse.json` oder, bei
`--max-history`, `gsc-max-history.json`):

```json
{
  "period": {"start": "...", "end": "...", "granularity": "month"},
  "totals": {"clicks", "impressions", "ctr", "position"},
  "top_queries": [{"query", "clicks", "impressions", "ctr", "position"}],
  "top_pages": [{"page", "clicks", "impressions", "ctr", "position"}],
  "top_countries": [{"country", "clicks", "impressions", "ctr", "position"}],
  "devices": [{"device", "clicks", "impressions", "ctr", "position"}],
  "search_types": [{"search_type", "clicks", "impressions", "ctr", "position"}],
  "daily": [{"date", "clicks", "impressions", "ctr", "position"}],
  "by_month": [{"month": "2026-08", "clicks", "impressions", "ctr", "position"}],
  "sitemaps": [{"path", "last_submitted", "is_pending", "errors", "warnings"}],
  "index_sample": [{"url", "verdict", "coverage_state", "last_crawl_time"}],
  "comparison": { "totals, top_queries, top_pages, top_countries, devices, search_types, daily plus eigener period, nur bei --compare-*": "..." },
  "history_from": "nur bei --max-history: gemessenes ältestes Datum mit Daten"
}
```

Der `comparison`-Block liegt immer in derselben Datei, nie als eigene Datei oder
eigener Ordner. Er enthält keine `sitemaps` und kein `index_sample`: beides sind
punktuelle Momentaufnahmen, die nur in den Hauptteil gehören. Scheitert eine
Inspektion, steht statt des Ergebnisses `{"url", "error"}` im `index_sample`.
Scheitert die Sitemap-Liste, steht unter `sitemaps` statt der Liste ein Objekt
`{"error": "..."}`; die Suchdaten bleiben davon unberührt. Puls-Dateien
überschreiben nie die Monats-Vergleichsbasis.

`by_month` ist die Tagesreihe zu Kalendermonaten verdichtet, chronologisch
sortiert, Monat zweistellig aufgefüllt. Die Baseline verlangt Klicks,
Impressionen, CTR und Position **je Monat** (Spec Abschnitt 10), und aus einer
Lebenszeit-Summe lässt sich später kein Vergleich gegen denselben
Kalendermonat rechnen. CTR und Position werden dabei neu gerechnet, nie
gemittelt: die Position ist der impressionsgewichtete Mittelwert, genau wie in
`totals`. Ein Monat ohne Impressionen hat `position: null`, nicht 0, sonst
stünde er im Report als Platz 0 und damit besser als Platz 1.

`top_countries` und `devices` kommen aus echten API-Dimensionen wie `top_queries`
und `top_pages`. `search_types` nicht: die Search-Analytics-API kennt Suchtyp nur
als Filter (`type`, ehemals `searchType`), keine Dimension zum Gruppieren, daher
ein Query je Typ (web, image, video, news, discover, googleNews); ein Typ ohne
Daten im Zeitraum fehlt in der Liste ganz.

`history_from` steht nur in `gsc-max-history.json`. Der Wert ist gemessen, nicht
angenommen: das Script fragt testweise deutlich weiter zurück als die von Google
dokumentierten 16 Monate und nimmt das älteste Datum, für das die API tatsächlich
eine Zeile liefert. Das ist zugleich `period.start` des Snapshots, weil dieser
Lauf die komplette vorhandene Historie abdeckt, nicht nur einen Monat oder eine
Woche.

## Setup-Check

`--check` testet nur Auth plus eine 1-Tages-Mini-Query (Exit 0/1), gedacht für den
Setup-Wizard:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/pull-gsc/scripts/gsc_pull.py" \
  --site <gsc_site> --creds "$PTAI_GOOGLE_CREDENTIALS" --check
```

## Fehlerbilder

- `google-auth fehlt`: `pip3 install --user google-auth requests`, dann erneut.
- 403/Permission denied: die Service-Account-Mail hat keinen Lesezugriff auf die
  Property. In der Search Console unter Einstellungen, Nutzer und Berechtigungen
  freigeben.
- `error`-Objekt unter `sitemaps` oder einzelne `error`-Einträge im
  `index_sample`: nicht fatal, der Rest des Snapshots ist vollständig.
- `error`-Objekt unter `comparison`: der Vergleichs-Pull ist fehlgeschlagen,
  nicht fatal, der Hauptteil des Snapshots ist vollständig. Der Report zieht den
  Vergleich dann später live oder lässt die Delta-Spalte weg.
- Offener Punkt Pilot: ob der readonly-Scope
  `webmasters.readonly` für die URL-Inspection-API reicht, wird im Pilot gegen die
  echte API validiert; scheitert die Stichprobe daran flächig, im Report als
  "Index-Stichprobe nicht verfügbar" ausweisen.
