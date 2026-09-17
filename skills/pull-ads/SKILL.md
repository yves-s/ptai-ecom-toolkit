---
name: pull-ads
description: SEA-Zahlen aus einem Google-Ads-Konto ziehen (Ausgaben je Monat, ROAS, Impression Share und was ihn begrenzt, Kampagnen, Anzeigengruppen, tatsächliche Suchbegriffe und Ausgaben ohne Conversion) und als Snapshot ablegen. Nutzen, wenn ein Audit den Baseline-Block SEA braucht oder der Nutzer wissen will, wofür das Werbebudget tatsächlich ausgegeben wird. Braucht ein Entwicklertoken des Betreibers und einen Lesezugang zum Kundenkonto; liest reporting/config.json und .env im Kunden-Workspace.
---

# pull-ads: SEA-Snapshot ziehen

Zieht Ausgaben, Leistung und Verschwendung aus einem Google-Ads-Konto und legt
alles als Snapshot ab.

## Stand: ungeprüft gegen die echte API

**Dieser Pull ist gebaut, aber nie gegen ein echtes Konto gelaufen.** Zum
Zeitpunkt des Baus war das Entwicklertoken nicht beantragt. Der Code ist gegen
die REST-Referenz gebaut und gegen von Hand erstellte Fixtures geprüft
(`scripts/tests/fixtures/ads/HERKUNFT.md` sagt das ausdrücklich).

**Vor dem ersten echten Lauf ist die Verifikationsliste unten abzuarbeiten.**
Bis dahin darf keine Zahl aus diesem Pull in ein Kundendokument. Der Snapshot
trägt den Vorbehalt in `notes` mit.

## Zwei verschiedene Zugänge, und nur einer kommt vom Kunden

| | Wem gehört es | Woher |
|---|---|---|
| **Entwicklertoken** | dem Betreiber | eigenes Google-Ads-Verwaltungskonto, API-Center. Google gibt es frei, das dauert Kalenderzeit |
| **Zugang zum Werbekonto** | dem Kunden | der Kunde fügt die **Dienstkonto-Mailadresse** als Nutzer mit "Nur Lesen" hinzu |

Beides ist nötig. Der Zugriff läuft über dasselbe Dienstkonto wie GA4 und GSC,
mit dem Scope `adwords`; eine Personenadresse als Ads-Nutzer reicht **nicht**,
weil die API über das Dienstkonto geht.

## Voraussetzungen

- `reporting/config.json` mit `sources.ads` nicht `false` und
  `google_ads_customer_id`, der Kundennummer des Werbekontos mit oder ohne
  Bindestriche (Beispiel: `"123-456-7890"`)

  **Der Feldname war bis zum 07.09.2026 nirgends festgelegt.** Diese Skill
  verlangte "die Kundennummer des Werbekontos", aber weder `config.py` noch die
  Config-Vorlage im Setup-Wizard kannten ein Feld dafuer. Sobald das
  Entwicklertoken vorliegt, haette der Nachtrag an einem Feld gestanden, das
  niemand benennen kann.
- `PTAI_GOOGLE_CREDENTIALS` in der `.env` des Workspace, `PTAI_GOOGLE_ADS_TOKEN`
  dort oder zentral in `~/.config/ptai-ecom/.env`

Fehlt das Token oder der Zugang: als "nicht verfügbar (Grund)" melden und
aufhören. Der Baseline-Block SEA bleibt dann leer und wird später mit
`--backfill` nachgetragen. **Das ist der dokumentierte Normalfall**, kein
Fehler: solange kein Token vorliegt, kommt die SEA-Baseline aus einem
Berichtsexport des Kunden (Spec Abschnitt 4).

## Ablauf

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/pull-ads/scripts/ads_pull.py" \
  --customer-id <kundennummer> --creds "$PTAI_GOOGLE_CREDENTIALS" \
  --max-history --out "reporting/data/<run-id>"
```

`--login-customer-id` nur, wenn der Zugriff über ein Verwaltungskonto läuft.
`--check` prüft nur Zugang und Währung, ohne Snapshot.

Der Kontobeginn wird **gemessen, nicht angenommen**: `--max-history` fragt ab
2010 und nimmt den frühesten Tag mit Daten, wie `pull-gsc` und `pull-ga4`.

## Snapshot-Schema

`<out>/ads.json`:

```json
{
  "source": "ads", "period": {"start", "end", "granularity"},
  "currency": "EUR", "history_from": "2023-04-01",
  "account": {"id", "name", "time_zone"}, "api_version": "v21",
  "by_month": [{"month": "2026-08", "impressions", "clicks", "cost",
                 "conversions", "conversions_value", "roas",
                 "search_impression_share",
                 "search_budget_lost_impression_share",
                 "search_rank_lost_impression_share"}],
  "campaigns": [{"name", "status", "channel_type", "impressions", "clicks",
                  "cost", "conversions", "conversions_value", "roas"}],
  "summary_search_terms": {"search_terms_total", "terms_without_conversion",
                            "cost_without_conversion"},
  "search_terms_without_conversion": [{"term", "campaign", "cost", "clicks", "impressions"}],
  "notes": ["..."]
}
```

**Die Währung steht im Snapshot, nicht in der Annahme.** Ein Euro-Betrag aus
einem Konto in Franken fällt in keiner Tabelle auf.

**Beträge kommen als Micros.** `cost_micros` durch eine Million; `null` bleibt
`null`, weil "kein Wert" etwas anderes ist als "null ausgegeben".

**Der Impression Share wird impressionsgewichtet gemittelt**, nie ungewichtet:
der Mittelwert eines Tages mit zehn und eines mit zehntausend Impressionen ist
eine Zahl, die es nicht gibt. Ein Monat ohne Impressionen bekommt `null`, nicht
0, denn 0 hieße "nie ausgeliefert".

**Ein Monat ohne Ausgaben hat keinen ROAS**, also `null`. Eine 0 läse sich als
"nichts eingebracht".

**"Ausgaben ohne Conversion" zählt Bruchteile mit.** Google zählt Conversions
als Dezimalzahl; 0,5 ist eine Conversion und keine Verschwendung. Die Summe geht
über alle Suchbegriffe, die Liste ist auf 300 gekappt.

**Nur die Kampagnen-Abfrage ist fatal.** Ohne sie gibt es keine SEA-Baseline.
Anzeigengruppen und Suchbegriffe scheitern isoliert: statt des Blocks steht ein
`error`-Eintrag im Snapshot, genau wie `sitemaps` in `gsc_pull.py`.

## Vor dem ersten echten Lauf zu verifizieren

1. **Zugriffsebene des Tokens.** Ein Token auf "Test Account Access" darf
   ausschließlich Testkonten abfragen. Für einen Kundenaudit reicht das nicht.
   Prüfen: `--check` gegen das echte Kundenkonto. Schlägt es mit einer
   Berechtigungsmeldung fehl, ist die Ebene das Problem, nicht der Code.
2. **API-Version.** `ads_client.DEFAULT_VERSION` gegen die Liste der
   unterstützten Versionen halten und anpassen. `--api-version` übersteuert.
3. **Feldnamen der vier Abfragen**, insbesondere die drei
   Impression-Share-Metriken und ob sie zusammen mit `segments.date` überhaupt
   geliefert werden. Prüfen gegen den Field-Reference-Report der eingesetzten
   Version.
4. **`login-customer-id`.** Ob der Header nötig ist, hängt davon ab, ob über ein
   Verwaltungskonto zugegriffen wird. Der Schalter existiert, sein Bedarf ist
   ungeprüft.
5. **Dienstkonto statt Personenzugang.** Die Dienstkonto-Mail muss als Nutzer im
   Kundenkonto stehen. `--check` sagt, ob das greift.
6. **Währung.** `--check` gibt sie aus. Passt sie nicht zum Shop, ist jede
   spätere Zahl im Report falsch beschriftet.
7. **Historienanfang.** Ob die gemessene `history_from` plausibel ist, zeigt
   erst ein echtes Konto.

Danach die von Hand gebauten Fixtures durch aufgezeichnete Antworten ersetzen
und `notes` aus dem Snapshot-Aufbau entfernen.

## Fehlerbilder

- **`PTAI_GOOGLE_ADS_TOKEN` fehlt:** klare Meldung, Exit 1, kein Aufruf.
- **Berechtigung verweigert:** meist die Zugriffsebene des Tokens oder die
  fehlende Dienstkonto-Freigabe im Kundenkonto, nicht der Code.
- **Anzeigengruppen oder Suchbegriffe scheitern:** `error`-Eintrag im Snapshot,
  der Rest bleibt vollständig.
