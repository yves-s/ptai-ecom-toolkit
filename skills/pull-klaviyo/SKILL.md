---
name: pull-klaviyo
description: Klaviyo-CRM-Daten für den Kunden-Report oder den CRM-Automation-Case ziehen (Flows, Kampagnen samt Betreff/Preview/Absender/Volltext, Report-Metriken, Listen, Segmente, Formulare) und als Snapshot ablegen. Nutzen, wenn ein Report oder Audit Klaviyo-Zahlen braucht, wenn ein CRM-/Voice-Profil aus echten Kampagnen- und Flow-Texten entstehen soll, oder wenn der Nutzer explizit einen Klaviyo-Pull für einen Zeitraum will. Liest reporting/config.json und .env im Kunden-Workspace. Pilot, am 11.09.2026 gegen einen echten Account validiert.
---

# pull-klaviyo: Klaviyo-Snapshot ziehen

Zieht per Klaviyo-REST-API (JSON:API, `https://a.klaviyo.com/api/`) Flows, Kampagnen,
Report-Metriken je Flow und Kampagne, Metrik-Aggregate für Placed Order, Listen,
Segmente und Formulare für einen Zeitraum und legt alles als Snapshot im
Kunden-Workspace ab. Wird vom Report- und Audit-Lauf aufgerufen, funktioniert aber
auch solo.

**Kampagnen und Flow-Nachrichten (SEND_MESSAGE-Actions) tragen zusätzlich den
tatsächlichen Content:** Betreffzeile, Preview-Text, Absender (`from_email`,
`from_label`) direkt aus der Nachricht, dazu `body_text` aus dem verknüpften
Template-HTML zu Klartext gestrippt (stdlib `html.parser`, kein Layout-Anspruch).
Das ist Marken-Content für ein CRM-Voice-Profil (wie schreibt die Brand Betreff,
Anrede, CTA, Ton), keine Kunden-PII, und fällt nicht unter die Profil-Export-Sperre
unten. Mit `--skip-content` läuft nur der schnelle Metadaten-Pull ohne Text.

**Pilot-Status:** Erster Validierungslauf am 11.09.2026 gegen einen echten Account
abgeschlossen, Kampagnen- und Flow-Nachrichten mit Volltext. Alle Endpunkte
inklusive der Report-Endpunkte (`campaign-values-reports`, `flow-values-reports`,
`metric-aggregates`) liefern bestätigt, Antwortform ist in `Fehlerbilder`
dokumentiert. Offen: `account` bleibt `null` ohne `accounts:read`-Scope,
`profile_count` bei Listen/Segmenten ist auf dieser API-Revision nicht
abrufbar, und Benchmarks für Flow-Kennzahlen sind gegen diesen Lauf noch nicht
geprüft.

## Voraussetzungen

Im Kunden-Workspace (aktuelles Arbeitsverzeichnis):

- `reporting/config.json` mit `sources.klaviyo: true`
- `.env` im Workspace-Root mit `PTAI_KLAVIYO_KEY` (Private API Key, Read-only-Scopes:
  Accounts, Campaigns, Flows, Lists, Segments, Metrics, Profiles, Events, Forms,
  Templates, Tags, Coupons; beim Anlegen in Klaviyo unter Settings > API Keys >
  Create Private API Key so wählen, danach nicht mehr änderbar)

Fehlt eins davon oder steht `sources.klaviyo` auf `false`: Klaviyo als "nicht
verfügbar (Grund)" melden und aufhören. Nie den Gesamtlauf (Report/Audit) daran
scheitern lassen.

**Kein Profil-Export.** Die Klaviyo-Profiles-API liefert Namen, Mailadressen und
Telefonnummern. `reporting/` wird ins Git-Repository des Kunden committet, ein
Profil-Export wäre dort ein Datenleck, keine Kennzahl (dieselbe Regel wie bei
`pull-shopify`, Abschnitt Kohorten). Das Script zieht deshalb nie einzelne
Profile, nur aggregierte Zähler (Listen-/Segmentgrößen, Suppression-Zähler über
den System-Segment-Filter).

## Ablauf

1. `reporting/config.json` lesen (`sources.klaviyo`), `.env` sourcen
   (`PTAI_KLAVIYO_KEY`). Zeitraum bestimmen: Default sind die letzten 365 Tage für
   Flows/Kampagnen-Bestand, die Report-Endpunkte laufen zusätzlich über ein
   90-Tage-Fenster.
2. Script aufrufen. **Zielordner ist der Daten-Ordner des laufenden Audits oder
   Reports**, `reporting/data/<run-id>`; ohne Lauf-ID der heutige Ordner:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/pull-klaviyo/scripts/klaviyo_pull.py" \
     --out "reporting/data/$(date +%F)"
   ```

   `PTAI_KLAVIYO_KEY` kommt aus der bereits gesourcten `.env`, nie als
   `--api-key`-Argument: das stünde sonst im Klartext in der Prozessliste
   (`ps`), für jeden Nutzer der Maschine sichtbar. `--api-key` bleibt nur als
   Rückfallweg, mit Warnung auf stderr.

   Optional: `--days 365` (Bestandsfenster für Flows/Kampagnen, Default 365),
   `--report-days 90` (Fenster für die Report-Endpunkte, Default 90), `--check`
   (nur Auth-Test, siehe unten), `--skip-content` (kein Betreff/Text/Template-Pull,
   nur Metadaten: deutlich weniger API-Calls, aber kein Voice-Profil daraus baubar).
3. Kernzahlen an den Nutzer melden: Zahl aktiver Flows, Zahl Kampagnen im Fenster,
   Flow-Anteil am E-Mail-Umsatz falls die Reports geliefert haben, größte Liste
   und größtes Segment, Zahl der gezogenen Kampagnen-/Flow-Nachrichten samt Text,
   Auffälligkeiten (leere Reports, fehlende Scopes, Templates ohne HTML).

## Snapshot-Schema

`reporting/data/<run-id>/klaviyo.json`. Jeder Teil scheitert isoliert: ein
Fehler macht das jeweilige Feld `null` plus Begründung in `notes`, bricht nie den
Lauf ab (Muster wie `pull-shopify`).

```json
{
  "period": {"inventory_days": 365, "report_days": 90, "pulled_at": "2026-09-14T10:00:00Z"},
  "account": {"id": "...", "timezone": "...", "public_api_key": "..."},
  "metrics": [{"id": "...", "name": "Placed Order", "integration": "Shopify"}],
  "flows": [
    {
      "id": "...", "name": "Welcome Series", "status": "live",
      "trigger_type": "List", "created": "...", "updated": "...",
      "actions": [
        {
          "id": "...", "action_type": "SEND_MESSAGE", "status": "live",
          "messages": [
            {"id": "...", "subject": "...", "preview_text": "...",
             "from_email": "...", "from_label": "...", "body_text": "..."}
          ]
        }
      ]
    }
  ],
  "campaigns": [
    {
      "id": "...", "name": "...", "status": "Sent", "channel": "email",
      "send_time": "...", "created_at": "...",
      "messages": [
        {"id": "...", "subject": "...", "preview_text": "...",
         "from_email": "...", "from_label": "...", "body_text": "..."}
      ]
    }
  ],
  "flow_reports": {
    "by_flow": [
      {"flow_id": "...", "recipients": 0, "open_rate": 0.0, "click_rate": 0.0,
       "conversion_rate": 0.0, "conversion_value": 0.0, "revenue_per_recipient": 0.0,
       "unsubscribe_rate": 0.0, "spam_complaint_rate": 0.0, "bounce_rate": 0.0}
    ],
    "raw_response_shape_confirmed": false
  },
  "campaign_reports": {
    "by_campaign": [
      {"campaign_id": "...", "recipients": 0, "open_rate": 0.0, "click_rate": 0.0,
       "conversion_rate": 0.0, "conversion_value": 0.0, "revenue_per_recipient": 0.0,
       "unsubscribe_rate": 0.0, "spam_complaint_rate": 0.0, "bounce_rate": 0.0}
    ],
    "raw_response_shape_confirmed": false
  },
  "placed_order_aggregate": {
    "by_attributed_channel": [{"$attributed_channel": "Email", "count": 0, "sum_value": 0.0}],
    "by_attributed_flow": [{"$attributed_flow": "...", "count": 0, "sum_value": 0.0}],
    "raw_response_shape_confirmed": false
  },
  "lists": [{"id": "...", "name": "...", "profile_count": 0}],
  "segments": [{"id": "...", "name": "...", "profile_count": 0}],
  "forms": [{"id": "...", "name": "...", "status": "..."}],
  "notes": {
    "flow_reports": "erster Lauf, Antwortform nicht bestaetigt",
    "profiles": "kein Einzelprofil-Export, nur aggregierte Zaehler"
  }
}
```

- `raw_response_shape_confirmed: false` steht in jedem Report-Block, bis ein
  echter Lauf die Feldnamen bestätigt hat. Nach dem ersten erfolgreichen Lauf auf
  `true` setzen (SKILL.md und Snapshot-Kommentar hier nachziehen) und diesen
  Hinweis aus dem Schema streichen.
- `notes` hält wie bei `pull-shopify` jede methodische Abweichung, nicht nur
  Totalausfälle: gekürzte Zeiträume, fehlende Scopes, Endpunkte, die 404 oder
  403 liefern.

## Setup-Check

`--check` testet nur Auth plus einen Mini-Call gegen `/api/accounts` (Exit 0/1):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/pull-klaviyo/scripts/klaviyo_pull.py" --check
```

## Fehlerbilder

**Das teuerste zuerst: `flow-values-reports` liefert nicht alle Flows.** Am
12.09.2026 fehlten im Report mehrere Flows, die senden und Umsatz tragen, darunter
Welcome-Flows. Ein Report, der nur auf `flow_reports` rechnet, weist den
Flow-Anteil am E-Mail-Umsatz dadurch viel zu niedrig aus. **Flow-Versände und
Flow-Umsatz deshalb immer über `metric-aggregates` gegenrechnen:** `Received Email` nach
`$flow` (count) und `Placed Order` nach `$attributed_flow` (sum_value). Die
Report-Endpunkte bleiben die Quelle für die Nachrichten-Ebene, nie für Summen je
Flow oder den Flow-Anteil.

Weitere Punkte aus dem Tiefen-Pull am 12.09.2026:

- Revision `2026-07-15` wird akzeptiert. Flow-Graphen (Trigger, Profilfilter,
  Splits, Wartezeiten) über `GET /api/flows/{id}/?additional-fields[flow]=definition`.
- Report-Zeilen gruppieren nach `flow_id`, `send_channel` und `flow_message_id`
  (Kampagnen: `campaign_id`, `campaign_message_id`). Die Nachrichten-ID nie
  verwerfen, sonst ist keine Diagnose innerhalb eines Flows möglich.
- `profile_count` gibt es nur auf der Einzelressource
  `GET /api/segments/{id}/?additional-fields[segment]=profile_count`, gedrosselt
  auf etwa 15 je Minute.
- `metric-aggregates`: `interval` kennt `year` nicht, `month` nehmen und summieren.
  Die Monats-Buckets tragen den Monatsbeginn in UTC (`2025-08-31T22:00:00+00:00`
  ist September in Berlin); wer das Datum auf sieben Zeichen kürzt, beschriftet
  jeden Monat um einen Monat zu früh. `by` akzeptiert nur Klaviyos feste
  Dimensionen (`$flow`, `$message`, `$attributed_flow`, `Inbox Provider`,
  `Bounce Type`, `Method` und wenige mehr), keine Shopify-Eigenschaften wie
  `Source Name`. `Method` war beim Subscribe-Event leer.
- Kampagnen-Liste liefert `audiences.included/excluded`, `send_strategy` und
  `send_options` mit; `messages.channel` kennt `whatsapp` nicht als Filterwert.
- Metriken können doppelt existieren (`Added to Cart` aus Shopify und aus der API,
  `Active on Site` zweimal). Für Abdeckungs-Rechnungen die Metrik-ID nehmen, die
  der Flow im Graphen als Trigger nutzt, nie den ersten Namens-Treffer.

Alle folgenden Punkte sind am Pilot-Lauf gegen einen echten Account (11.09.2026)
bestätigt, nicht mehr Trainings-Wissen:

- `401 Unauthorized`: Key falsch oder abgelaufen. Neuen Private API Key beim
  Kunden anfragen, nie den Key im Chat austauschen (nur direkt in `.env`).
- `403 Forbidden` bei einzelnem Endpunkt: dem Key fehlt der Read-Scope für diese
  Ressource. Feld wird `null` plus Note, Rest des Laufs geht weiter. Am
  Pilot-Key fehlte `accounts:read`, `account` blieb `null`, alles andere lief.
- `429 Too Many Requests`: Klaviyo rate-limited nach Burst- und Steady-Limit je
  Endpunkt-Kategorie. Script wartet die `Retry-After`-Sekunden und versucht es
  einmal erneut; scheitert der zweite Versuch auch, Feld `null` plus Note.
- `campaign-values-reports`/`flow-values-reports` verlangen `conversion_metric_id`
  im Body (400 ohne, sonst funktioniert die volle `REPORT_STATISTICS`-Liste
  unverändert). Das Script löst die ID über die Metrik "Placed Order" auf und
  überspringt den Report ganz, wenn sie fehlt (`account`-Scope-Fehler kaskadiert
  hierhin).
- `/api/metrics/` akzeptiert kein `page[size]` überhaupt (400 "'page_size' is
  not a valid field"); ohne den Parameter kommt die volle Liste in einer Seite.
- `/api/lists/` und `/api/segments/` erlauben maximal `page[size]=10` und lehnen
  `additional-fields=profile_count` komplett ab ("additional-fields must be in
  []"). `profile_count` bleibt deshalb `null` plus Note; eine andere Quelle für
  Listengrößen ist noch offen. Bei `page[size]=10` reichen 20 Seiten nicht für
  große Accounts; `max_pages=60` im Script.
- `metric-aggregates` liefert **Zeitreihen**, keine flachen Werte: eine Antwort
  trägt `dates` (Monatsliste) plus `data[].measurements.count`/`.sum_value` als
  parallele Arrays zu `dates`. Das Script zippt das zu einer flachen Liste
  `{dimension, month, count, sum_value}`.
- Flow-Actions heißen `SEND_EMAIL`/`SEND_SMS`/`SEND_PUSH`, nie `SEND_MESSAGE`
  (kanal-neutraler Typ existiert nicht). `SEND_MESSAGE` bleibt als Fallback im
  Code, ist aber am echten Account nie aufgetreten.
- **Content sitzt unterschiedlich tief verschachtelt:** `campaign-message`
  trägt `attributes.definition.content.{subject,preview_text,from_email,
  from_label,...}`, `flow-message` dagegen `attributes.content.{...}` direkt,
  ohne `definition`-Wrapper. Wer das verwechselt, bekommt `subject: null` trotz
  funktionierendem `body_text`, genau der Fehler im ersten Pilot-Lauf.
- `/api/flow-actions/{id}/flow-messages/` lehnt `?include=template` ab ("'template'
  include is not currently supported for the requested operation on this
  resource"), `/api/campaign-messages/{id}/?include=template` dagegen nicht.
  Flow-Nachrichten lösen das Template deshalb immer über einen eigenen
  `/api/templates/{id}`-Call auf (`resolve_template_text`, Cache je Template-ID,
  weil viele Flows sich ein Template teilen).
- A/B-Test-Flow-Actions oder -Kampagnen können mehrere Nachrichten je Action haben;
  das Snapshot-Feld heißt deshalb `messages` (Liste), nie `message` (Singular).
