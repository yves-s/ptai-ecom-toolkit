---
name: pull-ga4
description: GA4-Daten für den Kunden-Report oder den Wochen-Puls ziehen (Kanäle, Landingpages, E-Commerce-Funnel) und als Snapshot ablegen. Nutzen, wenn ein Monats-Report oder Puls GA4-Zahlen braucht, oder wenn der Nutzer explizit GA4- bzw. Analytics-Daten für einen Zeitraum abrufen will. Liest reporting/config.json und .env im Kunden-Workspace.
---

# pull-ga4: GA4-Snapshot ziehen

Zieht per Analytics Data API mehrere Sichten (Kanäle, Kampagnen, Geräte, Länder,
Landingpages, Funnel, interne Suchbegriffe) für einen Zeitraum und legt sie als
Snapshot im Kunden-Workspace ab. Wird vom Report- und Puls-Lauf aufgerufen,
funktioniert aber auch solo.

## Voraussetzungen

Im Kunden-Workspace (aktuelles Arbeitsverzeichnis):

- `reporting/config.json` mit `ga4_property_id` und `sources.ga4` nicht `false`
- `.env` im Workspace-Root mit `PTAI_GOOGLE_CREDENTIALS` (Pfad zum Service-Account-JSON)

Fehlt eins davon oder steht `sources.ga4` auf `false`: GA4 als "nicht verfügbar (Grund)"
melden und aufhören. Nie den Gesamtlauf (Report/Puls) daran scheitern lassen.

## Mehr als eine Property

**Ein Shop kann denselben Kauf in mehrere GA4-Properties senden.** Der
häufigste Fall: ein serverseitiges Werkzeug wie Littledata, Elevar oder
Analyzify tritt neben das clientseitige Tag und bekommt eine eigene Property.
Der Pull zieht genau eine, und ohne den Vergleich sieht der Audit die andere
nie.

```
--compare-properties 987654321,123456789
```

Je genannter Property kommt eine Monatsreihe aus Sitzungen, Käufen und Umsatz
samt der Währung dieser Property in den Snapshot, unter `compare_properties`.
Nicht mehr: die Analysen arbeiten
weiter mit der Hauptproperty, der Vergleich beantwortet nur die eine Frage,
die alles trägt, nämlich **welche Property mit dem Shop übereinstimmt.**

Die Liste kommt aus `reporting/config.json > ga4_compare_properties`.

**Warum das im Plugin steht und nicht im Kopf des Nutzers.** Am 07.09.2026
meldete die gezogene Property vier Monate ohne einen einzigen Kauf, und der
Report schrieb "die Kaufmessung ist ausgefallen". Die Bestellungen standen die
ganze Zeit in einer zweiten Property, die zudem um den Faktor zwei über
Shopify lag. Der falsche Befund ging bis auf die erste Seite.

## Käufe und Umsatz

**Käufe kommen aus der Metrik `ecommercePurchases` und stehen im Snapshot als
`purchases`, nie aus `transactions`.** GA4 zählt in `transactions` auch
`refund`-Ereignisse mit, und serverseitige Connectoren wie Littledata senden
Refunds. Bis zum 11.09.2026 zog der Pull `transactions`, und ein echter Audit
wies deshalb eine Abweichung gegen Shopify aus, die es so nicht gab. Am
11.09.2026 gegen zwei echte Properties nachgeprüft: `ecommercePurchases` lag in
jedem Monat exakt bei der Zahl der `purchase`-Ereignisse, `transactions` bei
Käufen plus Refunds.

**Snapshots von vor dem 11.09.2026 tragen noch `transactions`**, mit Refunds.
Kein Script liest das Feld als Käufe, der Report zeigt für solche Snapshots
"nicht messbar". Wer einen alten Lauf auswertet, zieht die Käufe neu, statt
`transactions` umzudeuten.

**`purchase_revenue` ist Umsatz abzüglich Erstattungen, in der Währung der
Property.** Die Metrik `purchaseRevenue` war am 11.09.2026 in jedem Monat
gleich `grossPurchaseRevenue` minus `refundAmount`. Zwei Folgen:

- Eine Property ohne `refund`-Ereignisse meldet Bruttoumsatz, eine mit ihnen
  Nettoumsatz. Die Erstattung zählt am Datum des `refund`-Ereignisses, nicht
  am Datum der Bestellung.
- Die Währung ist die Berichtswährung der Property, nicht die des Shops.
  Dieselbe Prüfung fand eine Property in USD neben einem Shop in Euro. Sie
  steht als `currency` im Snapshot und je Vergleichs-Property. **Umsatz nur
  gegen Shopify halten, wenn `currency` die Währung des Shops ist.**

## Ablauf

1. `reporting/config.json` lesen (`ga4_property_id`), `.env` sourcen
   (`PTAI_GOOGLE_CREDENTIALS`).
2. Zeitraum bestimmen. Default ist der letzte volle Monat (Erster bis Letzter des
   Vormonats). Puls-Modus: letzte volle Woche, Montag bis Sonntag.
3. Vergleichszeitraum nur beim Erstlauf: existiert bereits ein Vormonats-Snapshot
   (jüngster `reporting/data/`-Ordner, dessen `ga4.json` einen `period` mit
   granularity `month` über den vollen Vormonat trägt; `-pulse`-Dateien ignorieren),
   dann keinen Vergleich mitziehen, der Report vergleicht gegen den Snapshot.
   Existiert keiner, den Monat davor als `--compare-start/--compare-end` mitgeben.
4. Script aufrufen. **Zielordner ist der Daten-Ordner des laufenden Audits oder
   Reports**, also `reporting/data/<run-id>`; ohne Lauf-ID gilt der heutige
   Daten-Ordner wie im Beispiel (Abschnitt Snapshot-Schema):

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/pull-ga4/scripts/ga4_pull.py" \
     --property <ga4_property_id> \
     --creds "$PTAI_GOOGLE_CREDENTIALS" \
     --start YYYY-MM-01 --end <letzter Tag des Monats> \
     --out "reporting/data/$(date +%F)"
   ```

   Optional dazu: `--compare-start YYYY-MM-DD --compare-end YYYY-MM-DD` (Erstlauf),
   `--pulse` (Wochen-Puls, schreibt `ga4-pulse.json` mit granularity `week`),
   `--config reporting/config.json` (Bot-Filter, siehe unten).

   **Trägt die `config.json` einen `bot_filter`-Block, gehört `--config` an jeden
   Aufruf.** Ohne den Schalter zieht der Lauf ungefiltert und vergleicht später
   gefiltert gegen ungefiltert.
5. Kernzahlen an den Nutzer melden: Sessions, Nutzer, Umsatz, Funnel-Schritte,
   Top-Kanal. Bei Vergleich die Richtung (mehr/weniger) dazu. Bei `--max-history`
   zusätzlich `history_from`, den gemessenen Beginn der Historie.

## Maximalzeitraum

Für eine einmalige Baseline über die volle verfügbare Historie tritt
`--max-history` an die Stelle von `--start`; `--end` ist dabei optional
(ohne Angabe gilt gestern, wie bei `--check`):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/pull-ga4/scripts/ga4_pull.py" \
  --property <ga4_property_id> \
  --creds "$PTAI_GOOGLE_CREDENTIALS" \
  --max-history \
  --out "reporting/data/$(date +%F)"
```

Zielordner ist derselbe Daten-Ordner wie bei jedem anderen Lauf, im Audit also
`reporting/data/<run-id>` statt des Tagesordners im Beispiel; das Script
schreibt dort `ga4-max-history.json` mit granularity `max_history`, neben einem
eventuell schon vorhandenen `ga4.json`. `--max-history` schließt `--start`,
`--compare-start`/`--compare-end` und `--pulse` aus (das Script bricht sonst mit
einer klaren Fehlermeldung ab).

Die GA4-Aufbewahrungseinstellung (2 oder 14 Monate) betrifft vor allem
nutzer- und ereignisbezogene Abfragen; aggregierte Standarddimensionen wie
Kanal, Kampagne, Gerät oder Land reichen oft weiter zurück, und das
unterscheidet sich je Property. Der Startpunkt wird deshalb an dieser Property
gemessen statt angenommen: das Script fragt einen sehr weiten Zeitraum ab und
liest aus der Antwort, ab welchem Tag tatsächlich Zeilen zurückkamen. Dieses
Datum steht als `history_from` im Snapshot, ungefiltert vom Bot-Filter, damit
eine kundenspezifische Regel die Messung selbst nicht verzerrt.

## Bot-Filter

Automatisierter Traffic landet in GA4 als normale Session und verdirbt jede Quote:
Sessions rauf, Verweildauer runter, Funnel-Basis rauf. Die eingebaute Bot-Erkennung
von GA4 deckt nur die bekannte IAB-Liste ab, headless Chrome und Scraper laufen
daran vorbei.

Der Filter ist deshalb kundenspezifisch und liegt in `reporting/config.json`:

```json
"bot_filter": {
  "enabled": true,
  "since": "2026-08-26",
  "note": "Warum, mit den Zahlen, die den Verdacht belegen",
  "exclude": [
    {
      "reason": "Direct und Unassigned von ausserhalb DACH: automatisierter Traffic",
      "country_not_in": ["Germany", "Austria", "Switzerland"],
      "channel_in": ["Direct", "Unassigned"]
    }
  ]
}
```

Jede Regel ist eine UND-Verknüpfung ihrer Bedingungen, die Regeln untereinander
sind ODER-verknüpft, und passende Sessions fliegen aus allen Sichten (Kanäle,
Kampagnen, Geräte, Länder, Landingpages, Funnel, interne Suchbegriffe).
Erlaubte Bedingungen: `country_in`, `country_not_in`, `channel_in`,
`channel_not_in`, `device_in`, `source_in`, `operating_system_in`,
`browser_in`, `screen_resolution_in`. Ohne `enabled: true` passiert nichts.
Die Messung von `history_from` bei `--max-history` bleibt bewusst ungefiltert,
siehe oben.

**Eine Regel beschreibt ein Muster, nie ein Land.** Ganze Länder auszuschließen
kostet echte Besuche; bei Beispielshop wären mit einem reinen US-Ausschluss
elf echte Organic-Search-Sessions mit 40,7 Sekunden und 4,27 Seiten pro Besuch
mit rausgeflogen. Die Kombination aus Herkunft und Kanal trifft nur die Bots.

**Und nie einen ganzen Kanal.** Am 13.09.2026 nachgerechnet: ein Audit hatte
empfohlen, Direct auszuschließen, weil der Kanal zwei Anzeichen automatisierten
Zugriffs zeigte. Das hätte die echten Besuche in Direct samt ihren Käufen
entfernt und die Bot-Sitzungen in Unassigned stehen lassen.
Die Bots waren ein Geräteprofil, kein Kanal. Den Vorschlag dafür baut
`--audit-checks` (unten) als `bot_profiles.filter_proposal`, mit
`enabled: false`: übernommen wird er von einem Menschen, nachdem er Anteil,
Engagement, Käufe und Zeiträume des Profils gelesen hat.

**Der Filter macht Zahlen vor und nach seiner Einführung unvergleichbar.**
Deshalb trägt jeder gefilterte Snapshot die angewandten Regeln unter `filters`,
und die Config trägt `since`. Ein Report, der über diese Grenze hinweg
vergleicht, benennt sie, statt den Sprung als Entwicklung zu verkaufen.

## Bot-Profile und Absender (`--audit-checks`)

Für jeden Audit Pflicht, für Report und Puls nicht vorgesehen; mit `--pulse`
bricht das Script ab, weil ein zweiter Absender erst ab einer Woche zählt. Der
Schalter hängt drei Abschnitte an den Snapshot, bevor irgendeine Analyse eine
Rate aus GA4 rechnet:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/pull-ga4/scripts/ga4_pull.py" \
  --property <ga4_property_id> \
  --creds "$PTAI_GOOGLE_CREDENTIALS" \
  --max-history --audit-checks \
  --out "reporting/data/<run-id>"
```

**Warum.** Am 13.09.2026 in einem echten Audit nachgerechnet: ein einziges
Geräteprofil trug die Hälfte aller Sitzungen, in Wellen über Monate, ohne
Engagement und ohne Kauf, und ein zweiter Absender schickte seit einem Stichtag
jede Stufe des Kaufwegs doppelt an dieselbe Mess-ID. Die Add-to-Cart-Rate stand
bei der Hälfte ihres Werts, die Conversion Rate auf Desktop bei einem Viertel,
und ein Befund über schwache Einstiegsseiten beschrieb fast nur Bots. Aus dem
Hauptteil allein war das nicht zu sehen.

**`bot_profiles`: Geräteprofile, die wie Bots aussehen.** Ein Profil ist die
Kombination aus Bildschirmauflösung, Betriebssystem, Gerätekategorie und
Browser. Der Pull zieht Sitzungen je Tag und Profil, zählt die Kandidaten über
den ganzen Zeitraum nach und urteilt mit `audit/bots.py`: auffällig ist ein
Profil mit mindestens einem Prozent aller Sitzungen, einer Engagement Rate unter
20 Prozent und höchstens einem Kauf auf 10.000 Sitzungen. `windows` sind die
Zeiträume, in denen es einen ungewöhnlichen Tagesanteil trägt. Fällt eins auf,
zieht der Pull den Hauptteil ein zweites Mal ohne diese Profile, als
`bot_profiles.without`, mit den angewandten Regeln unter `filter`.

**`senders`: mehr als ein Absender je Mess-ID.** Ereignisse und Sitzungen je
Tag, getrennt danach, ob `hostName` und `customEvent:app_name` gesetzt sind,
dazu die Formate der Artikel-ID; die Regeln stehen in `audit/senders.py`.
Gerechnet wird ohne die auffälligen Bot-Profile (`variant`), weil ein Bot-Netz,
das nur einer der Absender zählt, die Überschneidung verdeckt. Hat die Property
`app_name` nicht als eigene Dimension registriert, trennt allein der Hostname,
und der Grund steht unter `notes`.

**`primary_sender`: die Zahlen nur mit dem ersten Absender**, im Hauptteil und
in `bot_profiles.without`, sobald ein zweiter erkannt ist. Er trägt den Kaufweg
je Stufe und, wenn der Kauf selbst doppelt kommt, Käufe und Umsatz je Kanal und
Gerät, immer aus `ecommercePurchases`.

**Keine dieser Abfragen legt den Snapshot.** Scheitert eine, steht der Grund
unter `bot_profiles.note` oder `senders.note`, und der Abschnitt meldet keinen
Befund: `bot_profiles.checked` und `senders.measurable` sind dann falsch. Die
Analysen lesen alle Varianten über `audit/ga4_variants.py`, das aus jeder
dieselben Raten rechnet.

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

Das Script schreibt `<out>/ga4.json` (bzw. `ga4-pulse.json` oder, bei
`--max-history`, `ga4-max-history.json`):

```json
{
  "period": {"start": "...", "end": "...", "granularity": "month"},
  "currency": "Berichtswährung der Property, etwa EUR oder USD",
  "history_from": "nur bei --max-history: gemessener erster Tag mit Daten",
  "by_month": [{"month": "2025-01", "sessions": 0, "purchase_revenue": 0.0, "purchases": 0,
                "channels": [{"channel", "sessions", "total_users", "purchase_revenue", "purchases"}]}],
  "channels": [{"channel", "sessions", "total_users", "purchase_revenue", "purchases", "engaged_sessions"}],
  "campaigns": [{"campaign", "sessions", "total_users", "purchase_revenue", "purchases"}],
  "devices": [{"device", "sessions", "total_users", "purchase_revenue", "purchases"}],
  "countries": [{"country", "sessions", "total_users", "purchase_revenue", "purchases"}],
  "landing_pages": [{"landing_page", "sessions", "engagement_rate", "purchase_revenue", "purchases"}],
  "compare_properties": [{"property_id", "currency", "note",
                          "by_month": [{"month", "sessions", "purchases", "purchase_revenue"}]}],
  "site_search": [{"search_term", "events", "sessions"}],
  "funnel": {"sessions": 0,
             "view_item": {"events": 457, "sessions": 273},
             "add_to_cart": {"events": 10, "sessions": 7},
             "view_cart": {"events": 0, "sessions": 0},
             "begin_checkout": {"events": 3, "sessions": 3},
             "purchase": {"events": 3, "sessions": 3}},
  "totals": {"sessions", "total_users (null, wenn die Gesamtzeile fehlt)", "purchase_revenue"},
  "property": {"property_id", "display_name", "measurement_ids",
               "streams": [{"stream_id", "measurement_id"}], "note"},
  "bot_profiles": {"checked", "flagged", "note", "period", "dimensions", "daily_floor",
                   "profiles": [{"profile", "label", "sessions", "share_of_sessions",
                                 "engagement_rate", "purchases", "purchase_rate", "total_users",
                                 "channels", "windows", "checks", "signals", "flagged"}],
                   "filter_proposal": {"enabled": false, "exclude": ["je auffälligem Profil eine Regel"]},
                   "without": {"Hauptteil ohne die auffälligen Profile": "...", "filter", "primary_sender"}},
  "senders": {"measurable", "variant", "note", "notes", "period", "onset",
              "multiple_senders", "double_counted_events",
              "item_ids": {"basis", "multiple_formats", "formats"},
              "streams": [{"stream_id", "measurement_id", "multiple_senders",
                           "double_counted_events",
                           "events": {"view_item": {"status", "onset", "uplift", "overlap",
                                                    "primary", "second", "senders"}}}]},
  "primary_sender": {"stream_id", "signatures", "funnel", "channels", "devices"},
  "notes": {"purchases": "nur, wenn die Property die Metrik ecommercePurchases abgelehnt hat",
            "site_search": "nur, wenn customEvent:search_term in der Property fehlt"},
  "comparison": { "gleiche Struktur, eigener period, nur bei --compare-*": "..." }
}
```

Jeder Funnel-Schritt trägt zwei Zahlen: `events` (wie oft das Ereignis
ausgelöst wurde) und `sessions` (in wie vielen Besuchen es vorkam). **Für jede
Quote im Report zählt `sessions`, nie `events`** (Kennzahlen-Katalog, Abschnitt
Funnel): eine Person sieht mehrere Produkte an, im Pilotmonat standen 457
`view_item`-Ereignisse für 273 Sessions. `funnel.sessions` daneben ist die
Gesamtzahl der Besuche und damit die Basis für die erste Stufe.

Fehlt ein Ereignis komplett (typisch `view_cart` bei einem Warenkorb-Drawer
ohne eigene Adresse), steht es mit Nullen da. Das ist kein Messfehler, sondern
die Aussage, dass es diesen Schritt in dem Shop nicht gibt; der Report darf
daraus keine Abbruchquote bauen.

`purchases` je Kanal trägt die Conversion Rate je Kanal (Formel und Schwelle
im Kennzahlen-Katalog, `${CLAUDE_PLUGIN_ROOT}/reference/metrics.md`). Lehnt
eine Property den Metrik-Namen ab, fällt der Kanal-Call genau einmal auf die
übrigen Metriken zurück: `purchases` steht dann in jedem Kanal auf `null`
(unbekannt, nie 0), der Grund steht unter `notes.purchases`, und der übrige
Snapshot bleibt vollständig. `notes` fehlt, solange nichts genullt wurde.

Der `comparison`-Block liegt immer in derselben Datei, nie als eigene Datei oder
eigener Ordner, und trägt `purchases` genauso. Puls-Dateien überschreiben nie
die Monats-Vergleichsbasis.

`campaigns`, `devices` und `countries` sind einfache Aufschlüsselungen derselben
Sessions wie `channels`, nur nach Kampagne, Gerätekategorie und Land sortiert,
mit denselben Basiszahlen samt `purchases`. `site_search` zählt die internen
Suchbegriffe der Property (Ereignis `view_search_results`, Parameter
`search_term`) nach demselben events/sessions-Muster wie der Funnel: `events`
ist, wie oft gesucht wurde, `sessions`, in wie vielen Besuchen. Das setzt
voraus, dass die Property den Parameter `search_term` als Custom Dimension
registriert hat; fehlt sie, bleibt `site_search` im Snapshot ganz weg und der
Grund steht unter `notes.site_search`, ohne den restlichen Lauf zu gefährden.

`history_from` steht nur in `ga4-max-history.json`. Der Wert ist zugleich
`period.start` dieses Snapshots, weil dieser Lauf die komplette gemessene
Historie abdeckt, nicht nur einen Monat oder eine Woche.

`by_month` steht ebenfalls nur in `ga4-max-history.json`: eine Zeile je Monat
der gemessenen Historie, jede mit der Aufschlüsselung nach Kanal. Der übrige
Snapshot aggregiert über den gesamten Zeitraum zu einer Summe, die Baseline
braucht aber Sessions je Monat und Kanal. Der Feldname ist derselbe wie im
Shopify-Snapshot, damit die Baseline beide Quellen gleich liest.

**Die Monatssumme trägt bewusst keine Nutzerzahl.** Sessions, Umsatz und
Käufe addieren sich über Kanäle, `total_users` tut das nicht: GA4
entdoppelt Nutzer je Dimensionskombination, wer im selben Monat über Organic
und über E-Mail kommt, steht in beiden Kanalzeilen. Je Kanal ist die Zahl
richtig und steht dort, eine Monatssumme daraus wäre zu hoch.

**`totals` wird deshalb nicht summiert, sondern von GA4 gerechnet.** Der
Kanal-Call fordert `metricAggregations: ["TOTAL"]` an. Bis zum 06.09.2026 hat
der Pull über die Kanäle summiert, `totals.total_users` war damit systematisch
zu hoch. Kommt die Gesamtzeile ausnahmsweise nicht mit, steht `total_users` auf
`null` statt auf einer zu hohen Summe: eine fehlende Zahl fällt auf, eine um
Prozente zu hohe nicht. `sessions` und `purchase_revenue` fallen in dem Fall
auf die Summe zurück, die für sie richtig ist.

## Setup-Check

`--check` testet nur Auth plus eine 1-Tages-Mini-Query (Exit 0/1), gedacht für den
Setup-Wizard:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/pull-ga4/scripts/ga4_pull.py" \
  --property <id> --creds "$PTAI_GOOGLE_CREDENTIALS" --check
```

## Fehlerbilder

- `google-auth fehlt`: `pip3 install --user google-auth requests`, dann erneut.
- 403/Permission denied: die Service-Account-Mail hat keinen Lesezugriff auf die
  GA4-Property. In GA4 unter Verwaltung, Property-Zugriffsverwaltung freigeben.
- `error`-Objekt unter `comparison`: der Vergleichs-Pull ist fehlgeschlagen,
  nicht fatal, der Hauptteil des Snapshots ist vollständig. Der Report zieht den
  Vergleich dann später live oder lässt die Delta-Spalte weg.
- `notes.purchases` im Snapshot: die Property hat die Metrik
  `ecommercePurchases` abgelehnt. Nicht fatal, der Snapshot ist bis auf die
  Conversion Rate je Kanal vollständig; der Report lässt die Spalte dann weg.
- `notes.site_search` im Snapshot oder `site_search` fehlt ganz: die Property
  hat den Event-Parameter `search_term` nicht als Custom Dimension
  (`customEvent:search_term`) registriert. Nicht fatal, der übrige Snapshot ist
  vollständig; in GA4 unter Verwaltung, Benutzerdefinierte Definitionen
  einrichten, falls interne Suchbegriffe gebraucht werden.
- `--max-history` bricht den Lauf ab, wenn schon die Messung des Startdatums
  fehlschlägt (Auth/Netzwerk): dann ist auch für den Hauptteil keine
  verlässliche Zahl zu erwarten.
- Offener Punkt Pilot: der Dimension-Name `landingPage` vs.
  `landingPagePlusQueryString` wird im Pilot gegen die echte API validiert.
  `ecommercePurchases` ist seit dem 11.09.2026 gegen zwei echte Properties
  geprüft.
