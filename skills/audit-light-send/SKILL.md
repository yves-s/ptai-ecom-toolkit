---
name: audit-light-send
description: Den fertigen Report aus einem audit-light-Lauf an den Lead verschicken, als Teaser-Mail im Path-to-AI-CI mit dem PDF im Anhang, und den Lead in Supabase auf sent setzen. Nutzen bei /ptai-ecom:audit-light-send, oder wenn der Nutzer den geprüften Audit-Report rausschicken will. Setzt voraus, dass der Lauf durch ist und der Report geprüft wurde. Für einen Dry-Run ohne Lead gibt es nichts zu senden.
---

# audit-light-send: Report an den Lead

Das ist der Lead-Funnel von Path to AI. Wer ihn selbst nutzen will, passt ihn
an, bevor die erste Mail rausgeht. Er braucht ein eigenes Supabase-Projekt mit
den Tabellen `audits` und `findings` in der Form, die
`${CLAUDE_PLUGIN_ROOT}/scripts/report/sales/db.mjs` liest und schreibt, ein
Resend-Konto mit verifiziertem Absender und die beiden Einstellungen
`PTAI_MAIL_FROM` und `PTAI_MAIL_REPLY_TO`, die keine Vorgabe haben. Die
Teaser-Mail stellt Yves vor und verlinkt seinen Kalender; wer den Funnel selbst
nutzt, passt `${CLAUDE_PLUGIN_ROOT}/scripts/report/sales/report-email.mjs` an.
Das Formular auf path-to-ai.com, über das die Leads in `audits` landen, ist
nicht Teil des Plugins.

**Argument:** die `audit-id` aus der Supabase-Tabelle `audits`, also die UUID, mit
der der Lead über den Funnel reinkam. Optional `--run <lauf-ordner>`, dann gilt
genau dieser Lauf.

Ohne Lead-Zeile gibt es keinen Empfänger. Ein Lauf, den du selbst gegen eine
fremde Domain gestartet hast, wird nicht verschickt; sein Report liegt im
Account und im `deliverables/`-Ordner, das reicht.

## Voraussetzungen

- Der Lauf ist durch, im Lauf-Ordner liegen `content.json` und `report.pdf`.
- **Du hast das PDF angesehen.** Nicht überflogen, angesehen. Es geht an einen
  Menschen, der Path to AI danach beurteilt.
- `RESEND_API_KEY`, `SUPABASE_URL` und `SUPABASE_SERVICE_ROLE_KEY` stehen in
  `~/.config/ptai-ecom/.env`. Die Skripte lesen sie von dort selbst, es braucht
  kein `--env-file`. Prüfen: `python3 -m audit.env`.
- `PTAI_MAIL_FROM` (Absender im Format `Name <adresse>`, bei Resend
  verifiziert) und `PTAI_MAIL_REPLY_TO` (wohin die Antworten der Leads gehen)
  stehen ebenfalls dort oder in der Umgebung. `python3 -m audit.env` zeigt, woher
  die beiden kommen, zählt sie aber nie als fehlend; fehlt eine, bricht
  `send-report.mjs` vor dem Versand mit einer Meldung ab.

## Ablauf

**1. Lauf-Ordner finden.** Mit `--run` ist er gesetzt: `RUN_DIR=<lauf-ordner>`.
Sonst liegt er beim Kunden unter `PTAI_ACCOUNTS_ROOT`, nicht in einem Repo. Der
jüngste Lauf mit dieser ID gewinnt, auch ein zweiter vom selben Tag
(`<datum>-light-2`):

```bash
ACCOUNTS_ROOT=$(PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" python3 -c 'from audit import account; print(account.accounts_root())')
RUN_DIR=$(grep -l "<audit-id>" "$ACCOUNTS_ROOT"/*/audit-runs/*-light*/run-config.json 2>/dev/null \
          | sed 's#/run-config.json$##' | LC_ALL=C sort -r | head -1)
```

`LC_ALL=C` ist Absicht: eine andere Sortierung übergeht Bindestriche, und dann
steht `-light` vor `-light-2`.

Bleibt `RUN_DIR` leer, nimm den Kunden über die Shop-URL aus der Lead-Zeile und
such in seinem Ordner:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/report/sales/db.mjs" get <audit-id>
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" python3 -m audit.account '<shop_url>'
ls -d "<drive_path aus der Ausgabe>"/audit-runs/*-light*
```

**2. Beleg-Gate nicht erneut abfragen.** Das Gate in `audit-light` Stufe 2 hat
jeden nicht bestätigten Befund schon selbst korrigiert oder gestrichen. Hier wird
nichts zur Freigabe vorgelegt, auch keine Liste aus `verify.json`.

**3. Senden.**

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/report/sales/send-report.mjs" \
  <audit-id> "$RUN_DIR/content.json" "$RUN_DIR/report.pdf"
```

Das Skript baut die Teaser-Mail (Score-Schnappschuss, drei Befunde, Soft-CTA,
Abbinder), hängt das PDF an, verschickt über Resend an die Adresse aus der
Lead-Zeile und setzt `status='sent'` plus `sent_at`.

**4. Beim Kunden festhalten, wenn es dort eine `entity.md` gibt.** Sie liegt zwei
Ebenen über dem Lauf, `"$RUN_DIR/../../entity.md"`. Gibt es sie, eine Zeile unter
`## Audits`: Datum, dass der Report raus ist, Pfad zum Lauf. Sonst weiß beim
nächsten Kontakt niemand, dass dieser Lead schon etwas bekommen hat. Fehlt die
Datei, nichts anlegen: der Lauf-Ordner und `status='sent'` in Supabase belegen
den Versand.

## Was die Mail aus dem Report zieht

Der Teaser liest `exec.scores` für den Schnappschuss und **`exec.teaserFindings`
für den Block mit den drei Punkten**. Fehlt `teaserFindings` in der
`content.json`, geht die Mail mit einem leeren Block raus, ohne Fehler. Das Feld
ist deshalb Pflicht, drei Einträge, `{title, body}`, `body` ein bis zwei Sätze,
**reiner Plaintext**: die Mail escaped HTML und würde die Tags als Text zeigen.

## Fehlerbilder

- **`Versand abgebrochen: PTAI_MAIL_FROM fehlt`** (oder `PTAI_MAIL_REPLY_TO`):
  die Absenderangaben stehen weder in der Umgebung noch in
  `~/.config/ptai-ecom/.env`. Eintragen und erneut senden, es ist noch nichts
  rausgegangen.
- **`audit not found`:** die UUID gehört zu keiner Zeile. Tippfehler, oder der
  Lauf war ein Dry-Run ohne Lead.
- **Resend antwortet 4xx:** meist eine ungültige Empfängeradresse. Die Lead-Zeile
  prüfen, bevor du es erneut versuchst; jeder Versuch ist eine echte Mail.
- **`status` steht schon auf `sent`:** der Report ist raus. Nicht ungefragt
  zweimal senden, erst fragen.
