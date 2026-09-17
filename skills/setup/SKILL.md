---
name: setup
description: Geführter Setup-Wizard für ptai-ecom. Prüft Rechner und Anschlüsse per check_env.sh, gruppiert nach Pflicht, Empfohlen und Optional, und führt in zwei Teilen durch das Fehlende. Teil 1 einmal je Rechner, die Schlüssel des Betreibers zentral in ~/.config/ptai-ecom/.env (DataForSEO, PageSpeed, GEO, Google-Ads-Token). Teil 2 je Kunde im Workspace (Config, Dienstkonto, GA4, Search Console, Shopify). Schreibt reporting/config.json und bietet am Ende den ersten Lauf an. Nutzen bei der Ersteinrichtung, wenn eine Quelle fehlt oder kaputt ist, oder bei /ptai-ecom:setup. Idempotent, jederzeit wieder aufrufbar.
---

# setup: geführter Anschluss-Wizard

Der Einstiegspunkt für einen neuen Kunden-Workspace. Der Wizard setzt keinerlei
Vorwissen voraus: er zeigt, was fehlt, und führt durch jeden Anschluss, bis der
erste Report laufen kann. Idempotent: jeder Re-Run startet beim Check und macht
genau dort weiter, wo etwas fehlt oder kaputt ist. Nichts wird doppelt
eingerichtet, nichts geht durch einen Re-Run verloren.

Arbeitsverzeichnis ist der Kunden-Workspace (dort, wo `reporting/` liegen soll).

## Ablauf

1. **Check laufen lassen und Haken-Liste zeigen:**

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/check_env.sh" .
   ```

   Die Ausgabe ist nach Rechner, Pflicht, Empfohlen, Optional und Workspace
   gruppiert. Unter jeder offenen Quelle steht, was ohne sie fehlt, am Ende
   stehen "Pflicht vollständig." oder "Pflicht offen: ..." und die offenen
   empfohlenen und optionalen Quellen. Der Exit-Code zählt nur offene Punkte in
   Rechner, Pflicht und Workspace. Die Liste unverändert zeigen, dann kurz
   einordnen, was steht und was ansteht. Welche Quelle welche Stufe hat, steht
   in `scripts/audit/tiers.py` und nirgends sonst.

   Offene Zeilen unter Rechner kommen vor Teil 1: jede nennt, was fehlt, die
   Shopify-CLI steht unter "Shopify", der Browser unter "PDF und
   Screenshots". Ohne python3 ab 3.10 laufen die Test-Calls aus Teil 1 und 2
   nicht.

2. **Teil 1, Betreiber, einmal je Rechner.** Nur wenn der Check bei
   PageSpeed-Key, DataForSEO oder GEO-Keys etwas als offen meldet, und nur
   durch diese Punkte. Jeder lässt sich mit "jetzt nicht" überspringen, der
   nächste Setup-Lauf zeigt ihn wieder.

   Fehlt `~/.config/ptai-ecom/.env`, legt der Wizard den Ordner und die Datei
   mit leeren Zeilen für `PTAI_PSI_KEY`, `PTAI_DFS_LOGIN`,
   `PTAI_DFS_PASSWORD`, `PTAI_OPENAI_KEY`, `PTAI_PERPLEXITY_KEY`,
   `PTAI_GEMINI_KEY`, `PTAI_GOOGLE_ADS_TOKEN`, `PTAI_ACCOUNTS_ROOT`,
   `PTAI_OPERATOR_NAME`, `PTAI_OPERATOR_CONTACT`, `PTAI_OPERATOR_EMAIL`,
   `PTAI_OPERATOR_BOOKING_URL` und `PTAI_CLOSING_FILE` an und setzt die Rechte
   auf `600` (`chmod 600`). Eine
   leere Zeile zählt als nicht gesetzt. Dann in dieser Reihenfolge:

   1. Google-Cloud-Projekt mit den fünf APIs, sofern noch keins steht
      (`${CLAUDE_PLUGIN_ROOT}/reference/access.md` Teil A, Schritte 1 und 2).
   2. PageSpeed-Key (Abschnitt "PSI-Key" unten).
   3. DataForSEO (Abschnitt "DataForSEO" unten).
   4. GEO-Keys (Abschnitt "GEO" unten, Teil "Keys anlegen").
   5. Am Ende, nur wenn es fehlt, ein Angebot zum Google-Ads-Entwicklertoken
      (`${CLAUDE_PLUGIN_ROOT}/reference/access.md` Teil A, Schritt 6), mit dem Satz, dass die
      Freigabe durch Google dauert und der Audit ohne Token läuft. Ein
      fehlendes Token allein lässt Teil 1 nicht erscheinen.
   6. Sechs Einstellungen, alle nur auf Wunsch. Zwei haben eine Vorgabe und
      erscheinen im Check deshalb nur als Hinweis: `PTAI_ACCOUNTS_ROOT`, der
      Ordner mit den Kundenordnern (Vorgabe `~/ptai-ecom/accounts`; audit-light
      legt neue Kunden dort an), und `PTAI_OPERATOR_NAME`, der eigene Name oder
      Firmenname als Verantwortlicher in Maßnahmen und Report (Vorgabe
      "Dienstleister"). Nur ausdrücklich gesetzt zeigt er zusätzlich die Zeile
      Unternehmen im Schluss von Audit, Monats-Report und audit-light. Drei
      haben keine Vorgabe und füllen dort je eine weitere Zeile:
      `PTAI_OPERATOR_CONTACT`, wer ansprechbar ist, etwa ein Name, als Zeile
      Ansprechpartner; `PTAI_OPERATOR_EMAIL`, die Mailadresse, als Zeile E-Mail;
      `PTAI_OPERATOR_BOOKING_URL`, der Terminlink, nur mit `https://` oder
      `http://`, als Zeile Termin. Der Schluss zeigt eine Zeile je gesetztem und
      gültigem Wert, keinen Satz dazu; ohne eine einzige gültige Einstellung
      endet jedes Dokument mit der Herkunftszeile allein. Die sechste,
      `PTAI_CLOSING_FILE`, hat ebenfalls keine Vorgabe: der Pfad zu einer
      eigenen Schlussseite als HTML-Datei außerhalb des Plugins. Ist sie gesetzt
      und lesbar, enden Audit, Monats-Report und audit-light mit dieser Seite
      statt mit den Zeilen. Die Datei hält genau ein `<section>`-Element als
      volle A4-Seite, alle Selektoren unter dessen Klasse und alle Bilder und
      Schriften als `data:`-URIs (README, Abschnitt "Eigene Marke"). Keine der
      sechs lässt Teil 1 erscheinen.

3. **Teil 2, Kunden-Workspace, je Kunde.**

   - Config schreiben oder aktualisieren (Vorlage unten). Secrets gehören nie
     in die Config.
   - Jede offene Zeile unter Pflicht und Workspace mit der passenden Anleitung
     unten abarbeiten. Die Klicks in Konsolen und Adminflächen macht der
     Mensch; der Wizard erklärt den Weg und prüft nach jedem erledigten Schritt
     per Test-Call oder erneutem Check nach. Erst wenn der Haken auf `[x]`
     springt, gilt der Schritt als erledigt. Durchleitungen kurz und
     imperativ, keine Theorie, keine Vorab-Warnungen.
   - **Schließt der Kunde eine Quelle nicht an**, setzt der Wizard **jeden**
     ihrer Lauf-Quellen-Schlüssel unter `sources` auf `false`, bei Shopify also
     `shopify`, `catalogue` und `shop_tech`, statt ein leeres Feld stehen zu
     lassen. Die Zuordnung steht in `tiers.py` (`run_sources`).

4. **Was nur der Kunde kann, wird zur Anforderung, nicht zur offenen Zeile.**
   `check_env.sh` gibt am Ende einen eigenen Block aus, überschrieben mit "Das
   kann der Kunde freischalten, nicht du". Eine Analytics-Property lässt sich
   nur mit Administratorrechten teilen, eine Search-Console-Property nur von
   einem Eigentümer; beides sitzt beim Kunden, auch wenn der Operator die
   Quelle selbst öffnen kann.

   Steht dort mindestens ein Eintrag, baut der Wizard daraus eine
   **Anforderung an den Kunden**: Grundlage ist `${CLAUDE_PLUGIN_ROOT}/reference/access.md` Teil B,
   aber **nur die Teilmenge, die der Check gerade als offen meldet**. Sie
   enthält je Punkt die Dienstkonto-Adresse, den Klickweg samt Direktlink und
   einen Satz, wozu der Zugang dient. Die Platzhalter `<betreiber-mail>`,
   `<dienstkonto-mail>`, `<shop-domain>` und `<datum>` füllt der Wizard; die
   eigene Mailadresse fragt er beim Betreiber ab. Der Text geht als Entwurf an
   den Nutzer, gesendet wird nichts.

5. **Abschluss-Angebot:** "Ersten Lauf jetzt starten?" (Skill `report` oder
   `audit`). Offene empfohlene Quellen blockieren nichts: sie erscheinen als
   "nicht verfügbar (Grund)", der Rest läuft. Fehlt eine Pflichtquelle, fragt
   der Audit vor dem Start selbst noch einmal nach.

## Config-Vorlage

`reporting/config.json` im Kunden-Workspace. Alle Werte kundenspezifisch, keine
Secrets:

```json
{
  "brand": "Beispielshop",
  "domain": "https://beispielshop.de",
  "shopify_store": "beispielshop-de.myshopify.com",
  "ga4_property_id": "000000000",
  "ga4_compare_properties": [],
  "gsc_site": "sc-domain:beispielshop.de",
  "cwv_urls": ["https://beispielshop.de/", "https://beispielshop.de/products/BELIEBIG"],
  "account_slug": "beispielshop",
  "drive_path": "/pfad/zum/kundenordner/beispielshop",
  "geo_brand_terms": ["Beispielshop", "Beispiel Shop"],
  "geo_queries": {
    "brand": ["Beispielshop", "Beispielshop Outdoorjacken"],
    "category": ["Outdoorjacke kaufen", "Outdoorjacken nach Maß", "Kinderset"],
    "problem": []
  },
  "google_domain": "google.de",
  "geo_method": "api",
  "checkout_capture": true,
  "sources": {
    "shopify": true, "catalogue": true, "shop_tech": true,
    "ga4": true, "gsc": true, "ads": true, "cwv": true, "crawl": true, "geo": true,
    "dfs_rankings": true, "dfs_keywords": true, "competitors": true,
    "shopping": true, "backlinks": true
  },
  "pulse_kpis": ["sessions", "revenue", "orders", "conversion_rate", "aov", "gsc_clicks", "gsc_impressions"],
  "page_types": { "product": "https://beispielshop.de/products/BELIEBIG", "collection": "https://beispielshop.de/collections/BELIEBIG" },
  "cadences": {},
  "market": { "location_code": 2276, "language_code": "de" },
  "dfs_budget_usd": 10.0,
  "crawl_max_urls": 5000,
  "crawl_delay_sec": 0.3,
  "google_ads_customer_id": null
}
```

- `shopify_store` ist die echte myshopify.com-Domain, nie ein Alias.
- `geo_brand_terms` sind die Schreibweisen, gegen die `check-geo` eine
  Marken-Erwähnung in einer AI-Antwort erkennt. **Bewusst getrennt von
  `brand`**: `brand` ist der Name auf dem Dokument und wird gelegentlich
  angefasst (Zusatz, Schreibweise, ein Vermerk für einen Testlauf), und jede
  solche Änderung hat vorher still den Erwähnungs-Abgleich zerlegt, ohne dass
  irgendwo ein Fehler auftauchte. Fehlt das Feld, gilt `brand` wie bisher.
  Varianten gehören hier hinein, etwa mit und ohne Umlaut.
- **`ga4_compare_properties` sind weitere GA4-Properties, die derselbe Shop
  beliefert.** Der häufigste Fall ist ein serverseitiges Werkzeug wie
  Littledata, Elevar oder Analyzify, das neben das clientseitige Tag getreten
  ist und eine eigene Property bekommen hat. Der Audit zieht `ga4_property_id`
  vollständig und holt von jeder hier genannten Property nur eine Monatsreihe
  aus Sitzungen, Käufen und Umsatz, um zu sehen, welche mit dem Shop
  übereinstimmt. **Im Zweifel eintragen:** ohne den Vergleich kann keine
  Aussage über fehlende oder doppelt gezählte Käufe stimmen, und ein falscher
  Befund darüber landet auf der ersten Seite. Lädt der Shop mehr als eine
  `G-...`-Mess-ID im Quelltext, ist das der Hinweis, dass es eine zweite gibt.
- `gsc_site` muss exakt der Property-Form in der Search Console entsprechen
  (Unterscheidung im GSC-Abschnitt unten).
- `account_slug` und `drive_path` sind Pflichtfelder für den Audit: ohne sie
  weiß der Lauf nicht, in welchen Kundenordner Screenshots und Deliverables
  gehören, und legt sie sonst im Repo ab (verletzt die PII-Regel).
  `account_slug` ist der Name des Kundenordners unter `PTAI_ACCOUNTS_ROOT`,
  `drive_path` der absolute Pfad dorthin. Beide gibt
  `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" python3 -m audit.account create <domain> --brand=<brand>`
  aus; es findet einen vorhandenen Kunden und legt nur einen fehlenden an.
- `google_domain` ist optional (Default `google.de`): die Google-Domain für
  den GEO-SERP-Check im Browser-Weg, für nicht-deutsche Brands die passende
  Locale-Domain (etwa `google.com`).
- **`checkout_capture` ist die eine Frage, die der Wizard wirklich stellen
  muss**, und er stellt sie hier, damit der Audit sie nicht mitten im Lauf
  stellt. Sie steuert, ob der Audit den Kaufweg bis zur Zahlungsart-Auswahl
  fotografiert. Das legt einen echten Testwarenkorb im Produktivshop an, und
  daraus entsteht ein Abandoned-Checkout-Datensatz, auf den ein E-Mail-Werkzeug
  eine Warenkorbabbrecher-Strecke auslösen kann. Fehlt das Feld, läuft der
  Kaufweg nicht und die Lücke steht im Report. Standard `true`. Auf `false` setzen, wenn
  die Kasse des Shops ein Konto verlangt oder der Kunde keinen Testwarenkorb
  will; die Seitentyp-Aufnahmen laufen dann trotzdem.
- `geo_method` steuert den GEO-Weg: `api` (empfohlen), `browser` oder `off`.
  Die Entscheidung fällt im GEO-Abschnitt unten; Report und check-geo folgen
  ihr still, der Report fragt nie nach.
- `sources` schaltet Quellen einzeln an und aus. **Ein fehlender Schlüssel
  heißt an, nur `false` schaltet ab.** Die Vorlage führt alle vierzehn
  trotzdem auf, damit sichtbar ist, was läuft. Eine Quelle, die der Kunde
  (noch) nicht anschließt, bekommt `false` auf allen ihren Schlüsseln statt
  eines halben Anschlusses.
- `page_types` legt je Seitentyp eine Beispiel-URL fest, für Crawl,
  Core Web Vitals und Screenshots. Defaults sind `start, collection, product,
  cart, search, blog`; nur die abweichenden Typen müssen überschrieben werden.
- **`competitors` und `keyword_seeds` gibt es nicht mehr.** Sie standen bis
  zum 08.09.2026 in dieser Vorlage, und der Wizard mahnte sie an, wenn sie leer
  waren. Gelesen hat sie kein einziger Pull: `pull-dfs-competitors` sät mit den
  Kategorie-Begriffen aus `geo_queries` und findet die Wettbewerber über die
  Überschneidung in den Suchergebnissen, `pull-dfs-keywords` nimmt die
  Top-Anfragen aus der Search Console. Wer sie trotzdem in einer Config stehen
  hat, kann sie stehen lassen: sie stören nicht, sie tun nur nichts.
- `cadences` überschreibt die Kadenz einzelner Quellen (`run`, `month`,
  `quarter`) gegenüber der Voreinstellung aus Abschnitt 3; leer heißt, jede
  Quelle behält ihre Voreinstellung.
- `market` ist Pflicht und legt fest, welchen Markt die DataForSEO-Abfragen
  messen: `location_code` ist der numerische Standortcode (Deutschland 2276,
  Österreich 2040, Schweiz 2756, weitere in der DataForSEO-Standortliste),
  `language_code` der Sprachcode ("de", "en"). Es gibt bewusst keinen
  Vorgabewert: ein still angenommenes Deutschland liefert für einen Shop in
  einem anderen Markt Zahlen, die plausibel aussehen und zum falschen Land
  gehören. `google_domain` bleibt davon unberührt und behält seinen eigenen
  Default, weil `report` und `pulse` es in laufenden Workspaces von dort lesen.
- `google_ads_customer_id` ist die Kundennummer des Werbekontos, mit oder ohne
  Bindestriche. `null`, solange kein Zugang besteht: `pull-ads` meldet sich dann
  als "nicht verfügbar", der Baseline-Block SEA bleibt leer und wird später mit
  `--backfill` nachgetragen. Das ist der dokumentierte Normalfall.
- `crawl_max_urls` und `crawl_delay_sec` begrenzen den Crawl. Beide gehören
  in die Config und nie in den Prompt eines Laufs: der Umfang hängt am Shop
  und ist jedes Mal dieselbe Antwort. Den richtigen Wert kennt man erst nach
  dem ersten Crawl, dann steht er in der Sitemap-Zeile des Laufs ("Sitemap:
  4.200 URLs"). Führt der Shop mehrere Sprachversionen, deckt die Hälfte
  davon meist schon alles ab, was ein Relaunch betrifft. Antwortet er langsam
  oder sitzt eine Bot-Erkennung davor, gehört `crawl_delay_sec` höher.
- `dfs_budget_usd` ist der Kostendeckel für DataForSEO je Lauf, in US-Dollar.
  Default 10.0, konservativ, weil der reale Wert erst nach dem ersten Lauf
  feststeht (Spec Abschnitt 20).

## Secrets (.env)

Secrets liegen in zwei Dateien, nie in der Config und nie in Git:

Zentral, einmal je Rechner, `~/.config/ptai-ecom/.env` (Rechte `600`):

```
PTAI_PSI_KEY=<API-Key>
PTAI_DFS_LOGIN=<DataForSEO-Login>
PTAI_DFS_PASSWORD=<DataForSEO-API-Passwort, nicht das Konto-Passwort>
PTAI_OPENAI_KEY=<optional, GEO über die ChatGPT-API>
PTAI_PERPLEXITY_KEY=<optional, GEO über die Perplexity-API>
PTAI_GEMINI_KEY=<optional, GEO über Gemini-Grounding>
PTAI_GOOGLE_ADS_TOKEN=<Google-Ads-Entwicklertoken, sobald freigegeben>
PTAI_ACCOUNTS_ROOT=<optional, Ordner mit den Kundenordnern, Vorgabe ~/ptai-ecom/accounts>
PTAI_OPERATOR_NAME=<optional, eigener Name oder Firmenname in Maßnahmen und Report, Zeile Unternehmen>
PTAI_OPERATOR_CONTACT=<optional, Zeile Ansprechpartner im Schluss von Audit, Monats-Report und audit-light>
PTAI_OPERATOR_EMAIL=<optional, Zeile E-Mail im Schluss von Audit, Monats-Report und audit-light>
PTAI_OPERATOR_BOOKING_URL=<optional, Terminlink mit https://, Zeile Termin im Schluss von Audit, Monats-Report und audit-light>
PTAI_CLOSING_FILE=<optional, Pfad zur eigenen Schlussseite als HTML-Datei, ersetzt den Schluss aus den Zeilen>
```

Im Workspace, je Kunde, `<workspace>/.env`:

```
PTAI_GOOGLE_CREDENTIALS=<workspace>/secrets/google-sa.json
```

Jeder Betreiber-Schlüssel darf zusätzlich in der Workspace-`.env` stehen und
schlägt dort den zentralen, etwa wenn ein Kunde sein eigenes DataForSEO-Konto
mitbringt. Gesucht wird überall gleich: Umgebung, Workspace-`.env`, zentrale
Datei (`scripts/audit/env.py`). `PTAI_GOOGLE_CREDENTIALS` steht nie zentral.

- `PTAI_DFS_LOGIN` und `PTAI_DFS_PASSWORD` sind der DataForSEO-Zugang. Das
  Passwort ist das API-Passwort aus dem API-Access-Bereich, nie das Passwort des
  Kontos. Der Zugang gehört dem Betreiber und steht zentral. Die Zuordnung der
  Kosten je Kunde läuft über den Tag und `reporting/dfs-ledger.jsonl` (Spec Abschnitt 13).
  **Das Plugin liest nur diese beiden Namen.** `DATAFORSEO_USERNAME` und
  `DATAFORSEO_PASSWORD`, wie andere DataForSEO-Werkzeuge sie nutzen, zählen nicht.
  Stehen sie in der Workspace-`.env`, nennt der Wizard nur die Namen
  (`grep -oE '^[[:space:]]*(export[[:space:]]+)?DATAFORSEO_[A-Z_]+' .env`) und
  fasst die Datei nicht an. Umtragen macht der Betreiber: die Zeilen löschen und
  den Zugang, falls noch nicht geschehen, zentral eintragen. Ein `PTAI_DFS_*`-Paar
  in der Workspace-`.env` schlägt das zentrale und gehört nur dorthin, wenn der
  Kunde ein eigenes Konto mitbringt.
- `PTAI_GOOGLE_ADS_TOKEN` ist das Google-Ads-Entwicklertoken. Es gehört
  ebenfalls dem Betreiber und steht zentral. Beantragt wird es im eigenen
  Verwaltungskonto; der **Zugang zum Werbekonto des Kunden** ist etwas anderes
  und kommt vom Kunden.
  Fehlt der Schlüssel, fällt `pull-ads` als "nicht verfügbar" aus und der Lauf
  geht weiter. Das ist kein Fehler, sondern der dokumentierte Stand.
- `.env` muss in der `.gitignore` des Kunden-Workspace stehen. `check_env.sh`
  prüft das; fehlt der Eintrag, legt der Wizard ihn an (die eine Zeile `.env`),
  bevor irgendein Secret geschrieben wird.
- **Die Service-Account-JSON liegt im Kunden-Workspace, nicht zentral**, und
  zwar unter `secrets/` im Workspace-Root. Ein Kunde, ein Ort: wer den Workspace
  hat, hat alles dazu, und niemand sucht später einen Key in einem globalen
  Ordner. `PTAI_GOOGLE_CREDENTIALS` zeigt auf `<workspace>/secrets/google-sa.json`.
  Diese Regel ist nicht verhandelbar: kein `~/.config`, kein anderer zentraler
  Pfad, auch dann nicht, wenn dasselbe Dienstkonto mehrere Kunden bedienen
  könnte. Ob ein Dienstkonto für alle Kunden wiederverwendet wird oder jeder
  Kunde ein eigenes bekommt, entscheidet der Betreiber. In beiden Fällen
  entsteht je Kunde ein eigener JSON-Schlüssel, und der liegt hier.
- Vor dem Ablegen legt der Wizard `secrets/` in die `.gitignore` **und** in
  `.git/info/exclude` (letzteres gilt sofort und für alle Worktrees, auch bevor
  die `.gitignore`-Änderung gemergt ist). Danach mit
  `git check-ignore -v secrets/google-sa.json` nachweisen, dass es greift, erst
  dann die Datei dorthin verschieben.
- **Der Nutzer trägt jeden Key selbst in die zentrale Datei oder die
  Workspace-`.env` ein, der Wizard fragt ihn nie ab.** Ein im Chat genannter
  Key steht danach im Sitzungsprotokoll, und das ist genau der Ort, an dem er
  nicht landen soll. Der Wizard legt die Datei mit den leeren Zeilen an, nennt
  den Dateipfad, und prüft nach dem Eintragen
  per Test-Call nach. Nur der Pfad zur Service-Account-JSON darf genannt
  werden, das ist kein Geheimnis.
- Der Wizard fasst Secrets sonst nur als Durchreiche an: er schreibt den Pfad,
  den der Nutzer nennt, in `.env` und sonst nirgendwohin. Er gibt
  Key-Werte nie in Ausgaben, Logs oder Zusammenfassungen wieder und liest den
  Inhalt des Service-Account-JSON nicht. Logins in Browser oder Konsolen macht
  immer der Mensch.

## Was im Repo landet

Der Workspace ist in aller Regel das Shop-Repo des Kunden. Was dort versioniert
wird, entscheidet sich an der Wiederholbarkeit, nicht am Ordner: was ein
späterer Lauf jederzeit neu ziehen kann, darf ignoriert bleiben.

| Gehört ins Repo | Darf ignoriert bleiben |
|---|---|
| `reporting/config.json` | `reporting/data/<run-id>/` eines **Report**-Laufs |
| `reporting/baseline/` | `reporting/**/*.pdf` (liegt im Kundenordner) |
| `reporting/measures.json` | |
| `reporting/runs/<run-id>/` | |
| `reporting/data/<run-id>/` eines **Audit**-Laufs | |

**Die letzte Zeile ist der Grund für diese Tabelle.** Ein Report-Lauf darf
seine Snapshots wegwerfen, der nächste zieht sie neu. Ein Audit-Lauf nicht:
`crawl.json` und die Core Web Vitals halten den Zustand vor einem Relaunch
fest, und danach stellt ihn keine Abfrage mehr her. Trägt die `.gitignore`
eines Kunden-Repos ein pauschales `reporting/data/`, gehört vor dem Audit eine
Ausnahme dazu, etwa `!reporting/data/*-audit/`.

`check_env.sh` prüft das mit `git check-ignore` und meldet jede Abweichung. Ist
der Workspace gar kein git-Repo, sagt der Check auch das: dann wird nirgends
etwas festgehalten.

## Anschluss je Quelle

Teil 1 nutzt die Abschnitte PSI-Key, DataForSEO und aus GEO "Keys anlegen";
Teil 2 die übrigen samt der GEO-Entscheidung.

### Google Service-Account (Basis für GA4 und GSC)

Regie für den Wizard, nie an den Nutzer vorlesen: Durchleitungen kurz und
imperativ, ein Schritt pro Zeile, keine Zeitangaben, keine Theorie, keine
Vorab-Warnungen. Was schiefgehen kann, steht unten unter "Wenn bei Google
etwas klemmt" und wird **nur** gezeigt, wenn der passende Fehler wirklich
auftritt. Der Nutzer sieht ausschließlich die Schritte.

Beide Google-Quellen nutzen denselben Service-Account. Die Klick-Anleitung
dafür (Google-Cloud-Projekt, die fünf APIs, Dienstkonto samt JSON-Schlüssel)
steht in `${CLAUDE_PLUGIN_ROOT}/reference/access.md`, Teil A, Schritte 1 bis 3, und wird hier
nicht zweites Mal geführt: zwei Quellen für dieselbe Liste laufen sonst
auseinander. Dort abschließen (oder, falls Projekt und Dienstkonto aus einem
früheren Kunden schon stehen, nur den JSON-Schlüssel für diesen Kunden neu
erzeugen), danach hier weiter:

1. "Datei ist da" sagen. Der Wizard findet die frisch heruntergeladene JSON im
   Downloads-Ordner selbst, legt sie nach `<workspace>/secrets/google-sa.json`
   (Ignore-Regel vorher setzen und per `git check-ignore` prüfen, siehe
   Abschnitt Secrets), trägt den Pfad als `PTAI_GOOGLE_CREDENTIALS` in `.env`
   ein und liest aus der Datei nur die Dienstkonto-Mail aus, sonst nichts.
2. Weiter mit den zwei nächsten Abschnitten: die Dienstkonto-Mail
   (`...@...iam.gserviceaccount.com`, siehe `${CLAUDE_PLUGIN_ROOT}/reference/access.md`
   Teil A Schritt 3) in GA4 und GSC einladen. Beides führt der Wizard als eigene
   Durchleitung, Schritt für Schritt.

### GA4: Dienstkonto einladen

Eigene Durchleitung mit denselben Regie-Regeln:

1. analytics.google.com öffnen und die Property der Brand auswählen.
2. Unten links auf das Zahnrad "Verwaltung" (englisch "Admin").
3. Unter "Property, Property-Zugriffsverwaltung" (englisch "Property access
   management") auf das Plus, "Nutzer hinzufügen".
4. Die Dienstkonto-Mail einfügen, Rolle "Betrachter" (englisch "Viewer"),
   Häkchen "Per E-Mail benachrichtigen" ausschalten (die Mail kommt nicht an,
   das Konto ist eine Maschine), speichern.
5. Die Property-ID (nur die Zahl) steht unter "Property, Property-Einstellungen"
   (englisch "Property settings") oben rechts; der Wizard trägt sie als
   `ga4_property_id` in die Config ein.

   **Direktlinks brauchen die IDs, deshalb diese Reihenfolge.** Ein Link auf
   `analytics.google.com/analytics/web/#/admin` landet im Dashboard der zuletzt
   geöffneten Property, nicht in der Zugriffsverwaltung der richtigen. Erst mit
   Konto- und Property-Nummer entsteht ein Link, der trifft:
   `https://analytics.google.com/analytics/web/#/a<konto>p<property>/admin`.
   Beide Nummern stehen in der Adresszeile, sobald der Nutzer die Property
   einmal geöffnet hat (`#/a1234567p987654321/...`). Der Wizard fragt sie
   deshalb zuerst ab und bietet den fertigen Link danach an, statt einen
   Klickweg zu beschreiben.
6. Nachprüfen:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/pull-ga4/scripts/ga4_pull.py" \
     --property <ga4_property_id> --creds secrets/google-sa.json --check
   ```

   Der Pfad ist der aus Schritt 1 oben, oder der Pfad aus
   `PTAI_GOOGLE_CREDENTIALS` in der `.env`, falls er abweicht.

   Fehlerbilder (403, google-auth) stehen in der Skill `pull-ga4`. Meldet
   `check_env.sh` zusätzlich einen fehlenden GA4-Tag auf der Live-Site, ist das
   ein Hinweis an den Kunden: ohne Tag misst GA4 nichts, das Setup gehört dann
   auf Kundenseite geklärt.

### GSC: Dienstkonto einladen

**Eigener Schritt, nicht Teil der Analytics-Runde.** Die Search Console ist ein
eigenes Produkt mit eigener Nutzerverwaltung; ein Analytics-Zugang schaltet dort
nichts frei. Der Schritt bekommt in der Haken-Liste eine eigene Zeile und wird
auch dann geführt, wenn Analytics längst steht.

**Nutzer hinzufügen kann dort ausschließlich ein Eigentümer der Property.** Wer
die Property nur lesen darf, sieht unter Einstellungen die Meldung "You must be
a property owner to view or change these settings". Das ist kein Fehler im
Setup, sondern der Fall aus Ablauf-Schritt 4: die Anforderung geht an den
Kunden.

Der Direktlink führt bei bekannter Property-Form direkt auf die richtige Seite:
`https://search.google.com/search-console/users?resource_id=sc-domain%3Abeispielshop.de`
(für eine URL-Präfix-Property stattdessen die URL-kodierte Adresse einsetzen).

Eigene Durchleitung mit denselben Regie-Regeln:

1. search.google.com/search-console öffnen und oben links die Property der
   Brand auswählen.
2. Links unten "Einstellungen" (englisch "Settings").
3. "Nutzer und Berechtigungen" (englisch "Users and permissions"), Button
   "Nutzer hinzufügen".
4. Die Dienstkonto-Mail einfügen, Berechtigung "Uneingeschränkt" (englisch
   "Full") wählen, damit auch die URL-Inspektion geht, hinzufügen.
5. Der Wizard trägt `gsc_site` in die Config ein und achtet auf die
   Property-Form: eine Domain-Property heißt `sc-domain:example.de`, eine
   URL-Präfix-Property heißt `https://example.de/` (mit Schema und Slash).
6. Nachprüfen:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/pull-gsc/scripts/gsc_pull.py" \
     --site <gsc_site> --creds secrets/google-sa.json --check
   ```

   Der Pfad ist der aus Schritt 1 des Google-Service-Account-Abschnitts, oder
   der Pfad aus `PTAI_GOOGLE_CREDENTIALS` in der `.env`, falls er abweicht.

### Wenn bei Google etwas klemmt

Diese Fälle zeigt der Wizard nur, wenn der jeweilige Fehler tatsächlich
auftritt, nie vorab.

- **"Service account key creation is disabled"** beim Key-Erstellen: die
  Org-Policy `iam.disableServiceAccountKeyCreation` greift (Googles
  Secure-by-Default, sitzt auf der Organisation, nicht auf dem Projekt). Weg
  raus: auf Org-Ebene die Rolle "Organization Policy Administrator" haben,
  dann im **Projekt** unter "IAM & Admin, Organization policies" den
  Constraint öffnen, "Override parent's policy", Regel mit "Enforcement: Off",
  speichern. Achtung, es gibt zwei fast gleichnamige Constraints; entscheidend
  ist der aus der Fehlermeldung, meist `iam.disableServiceAccountKeyCreation`
  (Managed Legacy), nicht `iam.managed.disableServiceAccountKeyCreation`.
- **401 "API keys are not supported by this API"**: jemand hat versucht, GA4
  oder GSC mit einem API-Key abzufragen. API-Keys tragen keine Identität und
  funktionieren nur für öffentliche Daten (wie beim PSI-Key); private
  Property-Daten gibt Google nur an eine eingeladene Identität heraus. Die
  Console lässt einen API-Key trotzdem anlegen und sogar auf diese APIs
  einschränken, das ist eine UI-Falle. Zurück zum Service-Account-Weg oben.
- **403 bei GSC-Test-Call**: fast immer die falsche Property-Form in
  `gsc_site` (siehe GSC-Abschnitt) oder die Mail ist noch nicht als Nutzer
  eingeladen.

### PSI-Key (Core Web Vitals)

Die API ist schon aktiviert (Google-Cloud-Projekt, Teil 1). Die Klick-Anleitung
für den Key selbst steht in `${CLAUDE_PLUGIN_ROOT}/reference/access.md`, Teil A, Schritt 4, hier
nicht zweites Mal geführt. Bleibt nur:

1. Den Key selbst als `PTAI_PSI_KEY` in `~/.config/ptai-ecom/.env` eintragen,
   nicht im Chat nennen. Der Key muss **zwei** APIs erlauben, PageSpeed
   Insights und Chrome UX Report; ohne die zweite fehlt später die
   Wochenhistorie der Core Web Vitals, und der Abruf meldet 403 "blocked".
2. Nachprüfen:

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/skills/pull-cwv/scripts/psi_pull.sh" --check -
   ```

### DataForSEO (Betreiber)

Eigene Durchleitung mit denselben Regie-Regeln:

1. Konto auf dataforseo.com anlegen.
2. Im Dashboard unter "API Access" Login und API-Passwort ablesen. Das
   API-Passwort ist nicht das Konto-Passwort. Es wird nur in den ersten
   24 Stunden nach der Anmeldung angezeigt, danach über "Send by e-mail".
3. Beides selbst als `PTAI_DFS_LOGIN` und `PTAI_DFS_PASSWORD` in
   `~/.config/ptai-ecom/.env` eintragen, nie im Chat nennen.
4. Nachprüfen, kostet nichts und zeigt den Kontostand:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/dfs_client.py" --check
   ```

5. Ein Satz zum Guthaben: das Startguthaben von 1 USD reicht nicht sicher für
   einen Audit, der erste echte Lauf kostete gut einen Dollar. Aufladen geht ab
   50 USD, das Guthaben verfällt nicht. Den Deckel je Lauf setzt
   `dfs_budget_usd` in der Config, Vorgabe 10.

Stand der Angaben: DataForSEO Help Center, abgerufen am 11.09.2026.

### Shopify

1. CLI installieren, falls `check_env.sh` sie vermisst:
   `npm install -g @shopify/cli@latest`.
2. **Erst starten, wenn ein Mensch vor dem Bildschirm sitzt.** `shopify store
   auth` öffnet die Freigabeseite im Browser und wartet nur kurz auf den
   Rückruf; danach bricht es mit "Timed out waiting for OAuth callback" ab und
   hinterlässt keine URL, die sich später öffnen ließe. Ohne jemanden, der
   sofort bestätigt, scheitert der Schritt still und beliebig oft. Er gehört
   damit in dieselbe Klasse wie `capture-screens`: Vordergrund, angekündigt,
   und nicht im Hintergrund gestartet.

   **Zeigt die Freigabeseite "Oops, something went wrong. Unauthorized
   Access", ist meist das falsche Konto angemeldet**, nicht ein fehlendes
   Recht. Im Browser mit dem Konto anmelden, das Zugriff auf den Store hat, und
   den Aufruf wiederholen.

   Auth für die Store-Domain aus der Config, mindestens mit
   `read_reports,read_products`. Dabei gilt die harte Scope-Union-Regel der
   Skill `pull-shopify` (Abschnitt "Scope-Regel"): vor jeder Re-Auth den
   bestehenden Grant lesen und die Vereinigungsmenge aller Scopes senden, nie
   nur die zwei Report-Scopes. Der Ablauf steht dort komplett, hier nicht
   duplizieren.
3. Nachprüfen: die drei Prüfungen im Abschnitt "Setup-Check" der Skill
   `pull-shopify` (CLI-Version, `auth list` enthält die Domain, Mini-Query).

### GEO

Eigene Durchleitung mit denselben Regie-Regeln. Einzige Ausnahme von "keine
Theorie": diese zwei Sätze sagt der Wizard dem Nutzer vorweg:

> GEO misst, ob die Brand in AI-Antworten auftaucht (ChatGPT, Perplexity,
> Googles AI-Antworten): erwähnt ja/nein, als Quelle verlinkt ja/nein, Monat
> für Monat. Das ist der Teil des Reports, den klassische SEO-Tools nicht
> abdecken.

Dann genau eine Entscheidungsfrage, mit Empfehlung:

- **Per API, empfohlen:** drei kleine Keys, einmal angelegt, danach läuft
  jeder Report vollautomatisch und vergleichbar.
- **Per Browser:** keine Keys, dafür klickt jeder Report-Lauf durch
  Browser-Sitzungen, ChatGPT braucht dann den Login des Nutzers.
- **Erstmal aus:** jederzeit nachrüstbar.

Der Wizard schreibt die Wahl als `geo_method` in die Config (`api`, `browser`
oder `off`), in Teil 2 je Kunde. Danach:

**Bei `api`** nichts weiter, sofern der Check mindestens einen GEO-Key findet
(zentral oder im Workspace). Sonst die Keys wie unter "Keys anlegen (Teil 1)".

**Bei `browser`** eine Zeile an den Nutzer: jeder Report-Lauf prüft die drei
Plattformen in Browser-Sitzungen, für ChatGPT loggt sich der Nutzer vorher
selbst ein (nie der Agent).

**Bei `off`** nichts weiter.

Die Wahl gilt für alle Report- und Puls-Läufe, der Report fragt nie nach.
Migration: ältere Configs ohne `geo_method` behandeln die Skills wie `api`,
wenn mindestens ein GEO-Key gesetzt ist, sonst wie `browser`; ein
`/ptai-ecom:setup`-Lauf trägt das Feld nach.

**Keys anlegen (Teil 1)**, drei Stück, jeder einzeln optional.

**Jeden Key selbst in `~/.config/ptai-ecom/.env` eintragen, nie im Chat
nennen.** Als Namen im jeweiligen Portal `ptai-ecom` vergeben. Wer je Kunde
getrennt widerrufen will, legt einen eigenen Schlüssel mit Kundennamen an und
trägt ihn in die `.env` des Workspace ein, dort schlägt er den zentralen.

1. OpenAI (`PTAI_OPENAI_KEY`): https://platform.openai.com/api-keys öffnen,
   "Create new secret key".
2. Perplexity (`PTAI_PERPLEXITY_KEY`): https://www.perplexity.ai/account/api/group
   öffnen, Key erzeugen.
3. Gemini (`PTAI_GEMINI_KEY`): https://aistudio.google.com/apikey öffnen,
   "API-Schlüssel erstellen". **Am besten über "Create API key in new project".**
   Ein Schlüssel in einem bestehenden Projekt kann an dessen Einschränkungen
   scheitern und antwortet dann mit "Your project has been denied access".
4. Nachprüfen je gesetztem Key:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/check-geo/scripts/geo_api.py" \
     --check <chatgpt|perplexity|google-ai> -
   ```

   Eine Plattform ohne Key erscheint im Report als "nicht angeschlossen";
   der Key ist jederzeit über `/ptai-ecom:setup` nachrüstbar, ein fehlender
   Key blockiert das Setup nicht.

### PDF und Screenshots

Monats-PDF und Audit-Screenshots laufen über einen headless Browser,
bevorzugt die Headless Shell von Playwright. Steht unter Rechner "Browser:
weder die Headless Shell von Playwright noch Google Chrome oder Chromium
gefunden": `npx playwright install chromium-headless-shell` ausführen, mehr
ist nicht nötig. Google Chrome oder Chromium gehen auch.

## Abschluss

Wenn die Haken-Liste steht (oder der Nutzer bewusst mit einer Teilmenge
weitermacht): den ersten Lauf anbieten wie in Ablauf-Schritt 5. Für einen neuen
Kunden ist das der Audit (Skill `audit`), er friert die Baseline unter
`reporting/baseline/01/` ein. Danach folgt monatlich der Report (Skill `report`).
Wer später startet, ruft wieder `/ptai-ecom:setup` auf: der Wizard beginnt erneut beim Check.
