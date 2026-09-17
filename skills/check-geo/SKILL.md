---
name: check-geo
description: GEO- bzw. AI-Sichtbarkeit der Kunden-Brand prüfen (Google-AI, ChatGPT, Perplexity) plus Crawler-Matrix aus robots.txt und llms.txt-Status, Ergebnis als Snapshot ablegen. Den Weg entscheidet geo_method in der Config mit den Werten api (Default, per Script über OpenAI, Perplexity, Gemini-Grounding), browser oder off; der Lauf fragt nie nach. Nutzen, wenn der Monats-Report GEO-Zahlen braucht, oder wenn der Nutzer explizit wissen will, ob Brand oder Domain in AI-Antworten auftauchen. Liest reporting/config.json und .env im Kunden-Workspace.
---

# check-geo: GEO-Sichtbarkeit prüfen

Arbeitet das GEO-Query-Set aus der Config ab: je Query und Plattform wird
erhoben, ob die Brand in der AI-Antwort erwähnt wird und ob die Domain als
Quelle zitiert oder verlinkt ist. Welchen Weg der Check nimmt, steht als
`geo_method` in der Config: `api` (Default, über das Script `geo_api.py`),
`browser` (Browser-Protokoll unten) oder `off` (kein Lauf). Die Entscheidung
fällt im Setup, nie im Lauf: während eines Report- oder Puls-Laufs stellt GEO
dem Nutzer keine Fragen und öffnet nichts unangekündigt. Dazu die
Crawler-Matrix aus `robots.txt` und der llms.txt-Status per `curl` (beides
braucht nie einen Browser). Wird vom Monats-Report aufgerufen, funktioniert
aber auch solo. Für GEO gibt es keine Historien-API: der Vormonats-Snapshot
ist die einzige Vergleichsbasis, deshalb ist das Protokoll fixiert. Query-Set
und Wettbewerberliste werden mit dem ersten Lauf eingefroren (Regel 9): jeder
folgende Lauf arbeitet mit genau dieser Baseline weiter, unabhängig davon, was
später in der Config steht.

## Voraussetzungen

Im Kunden-Workspace (aktuelles Arbeitsverzeichnis):

- `reporting/config.json` mit `brand`, `domain`, `geo_queries` (drei Gruppen:
  `brand`, `category` und `problem`; `problem` sind Fragen ohne Markenbezug,
  die zur Kategorie führen, etwa "wo bekomme ich Outdoorjacken her"),
  `competitors` (Wettbewerberliste, leer erlaubt), `sources.geo` nicht `false` und
  `geo_method` (`api`, `browser` oder `off`; fehlt das Feld in einer älteren
  Config: wie `api` behandeln, wenn mindestens ein GEO-Key gefunden wird
  (Workspace-`.env` oder zentral), sonst wie `browser`); optional
  `google_domain` (nur für den Browser-Weg des Google-Checks relevant, Default
  `google.de`)
- Bei `geo_method: "api"`: die API-Keys in der `.env` des Workspace oder
  zentral in `~/.config/ptai-ecom/.env`, jeder einzeln optional:
  `PTAI_OPENAI_KEY` (Plattform `chatgpt`),
  `PTAI_PERPLEXITY_KEY` (Plattform `perplexity`), `PTAI_GEMINI_KEY`
  (Plattform `google-ai`); eine Plattform ohne Key wird "nicht angeschlossen",
  nie im Browser improvisiert
- `python3` (3.10 oder neuer) für `geo_api.py`, `curl` für robots.txt und
  llms.txt
- Bei `geo_method: "browser"`: ein Browser-Werkzeug in der Session; für
  ChatGPT dort eine eingeloggte Session auf chatgpt.com (der Login ist Sache
  des Menschen, nie des Agents)

Fehlt die Config oder steht `sources.geo` auf `false`: GEO als "nicht verfügbar
(Grund)" melden und aufhören. Nie den Gesamtlauf (Report/Puls) daran scheitern
lassen. Ein fehlender Key blockiert nichts, und der Lauf stellt zu keiner
dieser Weichen eine Frage: alle Entscheidungen stehen in der Config.

## Protokoll-Regeln (hart, für die Vergleichbarkeit)

Die Snapshots sind nur als Zeitreihe etwas wert. Deshalb:

1. **Queries wörtlich aus der Config.** Jede Query exakt so verwenden, wie sie
   in `geo_queries` steht. Nie umformulieren, nie ergänzen, nie "verbessern".
   Eine geänderte Formulierung ist eine andere Zeitreihe.
2. **Feste Plattform-Liste, feste Werte.** Genau drei Plattformen, im Snapshot
   genau diese Strings: `google-ai`, `chatgpt`, `perplexity`. Je Query und
   Plattform genau eine Zeile, immer, auch wenn nicht prüfbar. Die Zeilenzahl
   ist damit fix: Anzahl Queries mal drei.
3. **Zwei Booleans, die Fremdquellen und ein Beleg.** Je Zeile:
   `brand_mentioned` (die Brand aus `config.brand` wird in der AI-Antwort
   genannt, jede Schreibweise zählt), `domain_cited` (die Domain aus
   `config.domain` taucht in den Quellen oder Links der Antwort auf, Subdomains
   zählen mit), `other_citations` (die zitierten Fremd-Domains derselben
   Antwort, ohne die eigene, dedupliziert; Ableitung unten) und `evidence` (ein
   Satz, was die Antwort inhaltlich enthielt, plus bis zu 3 Citation-Hosts).
   `other_citations` steht in derselben Zeile, damit der Report den Share of
   Voice ohne zweiten Lauf rechnen kann.
4. **Ein Lauf je Query und Plattform, keine Wiederholungen.** AI-Antworten sind
   nicht deterministisch, per API genauso wie im Browser: dieselbe Query
   liefert beim zweiten Mal eine andere Antwort. Wer nachfasst, bis ein
   besseres Ergebnis kommt, verzerrt die Zeitreihe. Also: einmal fragen,
   Ergebnis nehmen, weiter. Wiederholt wird nur bei technischem Fehlschlag
   (API-Fehler, Seite nicht geladen), nie wegen des Inhalts.
5. **Nur, was wirklich zurückkam.** Im API-Pfad zählen ausschließlich
   `answer_text` und `citations` aus dem Script-Output, im Browser-Pfad nur,
   was auf dem Bildschirm stand. Kein Ergebnis aus Modellwissen, kein "wird
   wohl", nichts erfinden. Unsicherheit gehört benannt ins `evidence`-Feld,
   nicht in einen geratenen Boolean.
6. **Nicht prüfbar heißt null, nicht false.** Ist eine Plattform nicht
   erreichbar (API-Fehler nach Wiederholung, kein Login, Captcha), bekommt
   jede betroffene Zeile `"brand_mentioned": null, "domain_cited": null` und
   als Beleg `"evidence": "nicht prüfbar: <Grund>"`. Fehlt der Key und gibt es
   keinen Browser, lautet der Beleg
   `"evidence": "nicht angeschlossen: kein API-Key"`. So bleibt die
   Zeilenstruktur über die Monate konstant und ein Ausfall ist von einem
   echten Nein unterscheidbar.
7. **Gleiche Methode, Monat für Monat.** Jede Zeile trägt `method` (`api` oder
   `browser`). Verglichen wird nur innerhalb derselben Kombination aus
   Plattform und Methode; ein Methodenwechsel (etwa von `browser` auf `api`)
   wird im Report als Satz benannt, nie still vermischt. Für den
   Browser-Weg gilt zusätzlich die alte Session-Regel: den
   Google-SERP-Check ausgeloggt und im Desktop-Viewport, jeden Monat gleich;
   Abweichungen vom Standard ins `evidence`-Feld.
8. **Der Lauf fragt nie.** Während eines Report- oder Puls-Laufs stellt GEO
   dem Nutzer keine Fragen und öffnet nichts unangekündigt; alle
   Entscheidungen (Methode, Query-Set, Umfang) stehen vorher in der Config
   bzw. fallen im Setup. Fehlende Voraussetzungen werden zu `null`-Zeilen
   oder zu "nicht verfügbar (Grund)", nie zu einer Rückfrage mitten im Lauf.
9. **Query-Set und Wettbewerberliste sind mit der Baseline eingefroren.** Der
   erste Lauf (kein vorhandener `geo.json`-Snapshot mit `query_set`, siehe
   Ablauf) übernimmt beide Listen unverändert aus der Config und schreibt sie
   als `query_set` und `competitors` in den eigenen Snapshot; das ist die
   Baseline. Jeder folgende Lauf übernimmt beide Listen wörtlich aus dem
   jüngsten vorhandenen Snapshot, bildet sie nie neu aus der aktuellen Config,
   und schreibt sie unverändert weiter. Weicht die aktuelle Config von der
   eingefrorenen Liste ab (Query ergänzt, entfernt oder umformuliert;
   Wettbewerber geändert), bleibt trotzdem die eingefrorene Liste maßgeblich
   für diesen Lauf, und die Abweichung steht als `config_drift`-Satz im
   Snapshot sowie im Kernergebnis. Ohne diese Meldung fiele eine geänderte
   Zeitreihe niemandem auf, der Vergleich über die Monate wäre aber trotzdem
   hin.

## Ablauf

1. `reporting/config.json` lesen: `brand`, `domain`, `geo_queries`,
   `competitors`, `geo_method`, optional `google_domain` und
   `geo_brand_terms`.

   **Query-Set und Wettbewerber bestimmen (Regel 9):** den jüngsten
   vorhandenen `reporting/data/<datum>/geo.json`-Snapshot suchen (dieselbe
   Suche wie unten für den Vormonats-Vergleich).
   - Kein Snapshot vorhanden, oder der jüngste trägt noch kein `query_set`
     (ältere Snapshots von vor diesem Protokoll): dieser Lauf ist die
     Baseline. Geltendes Query-Set = Vereinigung aller drei Gruppen aus
     `geo_queries` (`brand`, `category`, `problem`), geltende Wettbewerber =
     `competitors`, beide unverändert aus der aktuellen Config übernommen.
   - Ein Snapshot mit `query_set` vorhanden: dessen `query_set` und
     `competitors` gelten wörtlich für diesen Lauf, unabhängig davon, was
     aktuell in der Config steht.
   - In beiden Fällen: das geltende Query-Set gegen die aktuelle Config
     abgleichen. Weichen sie ab, bleibt das geltende Set maßgeblich; die
     Abweichung wird als `config_drift`-Satz notiert (Regel 9), sonst ist
     `config_drift` `null`.

   Jede Query merkt sich ihre Gruppe (`brand`, `category` oder `problem`) für
   das `group`-Feld im Snapshot. Dann `geo_method` still befolgen, ohne
   Rückfrage (Regel 8):
   - `"off"`: der Check endet hier. An den Report geht nur die eine Zeile,
     dass GEO bewusst abgeschaltet ist und sich über `/ptai-ecom:setup`
     aktivieren lässt.
   - `"api"`: welche der drei Keys gefunden werden, sagt
     `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" python3 -m audit.env .`
     (Quelle je Schlüssel, nie der Wert). Genau die Plattformen mit Key
     laufen über das Script (Schritt 4); Plattformen ohne Key bekommen
     `null`/`null`-Zeilen mit "nicht angeschlossen: kein API-Key", nie einen
     Browser-Ersatz, auch wenn ein Browser da wäre.
   - `"browser"`: alle drei Plattformen laufen über das Browser-Protokoll
     (Schritt 5). Fehlt das Browser-Werkzeug, ist GEO "nicht verfügbar
     (geo_method browser, aber kein Browser-Werkzeug in der Session)".
   - Feld fehlt (ältere Config): wie `"api"` behandeln, wenn die Suche oben
     mindestens einen Key findet, sonst wie `"browser"`.

   Aufwands-Grenze: empfohlen sind maximal etwa 8 Queries gesamt. API-Läufe
   sind billig, Browser-Läufe teuer; ein zu großes Set wird im Setup
   verkleinert oder auf `api` umgestellt, nie im Lauf diskutiert (Regel 8).
2. **Crawler-Matrix** (kein Browser nötig): `curl -s <domain>/robots.txt`
   ziehen und je Crawler den Status bestimmen. Geprüfte Crawler, genau diese
   Schlüssel: `GPTBot`, `OAI-SearchBot`, `ChatGPT-User`, `ClaudeBot`,
   `Claude-Web`, `PerplexityBot`, `Google-Extended`, `CCBot`. `GPTBot` ist nur
   der Trainings-Crawler von OpenAI; die Live-Zitate der ChatGPT-Suche laufen
   über `OAI-SearchBot` und `ChatGPT-User`, deshalb stehen beide mit in der
   Matrix.
   - `erlaubt`: der Crawler hat eine eigene User-agent-Gruppe mit explizitem
     Allow oder ohne greifendes Disallow, und keine Pauschal-Sperre greift.
     Ein partielles Disallow (etwa `Disallow: /admin`) zählt als `erlaubt`,
     die partielle Zeile steht dann als `rule` dabei.
   - `blockiert`: `Disallow: /` in seiner eigenen Gruppe oder in der
     `*`-Gruppe, wenn er keine eigene hat.
   - `nicht erwähnt`: keine eigene Gruppe, und die `*`-Gruppe blockiert nicht;
     dann entscheidet `*`, und genau das steht als Begründung dabei.

   Pragmatisch bleiben: robots.txt lesen, je Crawler urteilen, und die
   entscheidende Zeile als `rule` in die Matrix schreiben, zum Beispiel
   `{"GPTBot": {"status": "blockiert", "rule": "Disallow: /"}}`. Liefert
   robots.txt HTTP 404, gibt es keine Regeln: alle Crawler `nicht erwähnt` mit
   `"rule": "robots.txt nicht vorhanden (HTTP 404)"`.
3. **llms.txt**: `curl -sI <domain>/llms.txt`. HTTP 200 heißt `true`, alles
   andere `false`.
4. **API-Checks** (`geo_method: "api"`), je Query aus Schritt 1 auf jeder
   Plattform mit Key, nach den Protokoll-Regeln oben:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/check-geo/scripts/geo_api.py" \
     --platform <google-ai|chatgpt|perplexity> \
     --query "<Query wörtlich>"
   ```

   Der Output ist ein JSON-Objekt mit `platform`, `answer_text`, `citations`
   und `model`. Daraus mechanisch:

   - `domain_cited`: den Host-Teil der Config-Domain (ohne Schema) gegen die
     Hosts der `citations` matchen, subdomain-tolerant: `www.example.de` und
     `shop.example.de` zählen für `example.de`.
   - `brand_mentioned`: case-insensitiver Substring gegen
     `config.geo_brand_terms` in `answer_text`; fehlt das Feld, gilt `brand`.
     **Nicht `brand` verwenden, solange `geo_brand_terms` gesetzt ist:** `brand`
     ist der Anzeigename und trägt gelegentlich Zusätze, und ein Zusatz dort
     lässt den Abgleich still ins Leere laufen. Dazu ein Sanity-Blick der
     Session: offensichtliche Varianten (etwa Umlaut-Schreibweisen) zählen als
     Erwähnung und werden im `evidence` vermerkt.
     **Ist der Markenname zugleich der Gattungsbegriff des Produkts, ist der
     Substring-Abgleich wertlos** und `brand_mentioned` wird `null` statt
     `true`. Bei LEDERTASCHE stand "Ledertasche" am 07.09.2026 in jeder Antwort,
     ohne dass die Marke einmal gemeint war. In so einem Fall zählt nur eine
     Nennung, die erkennbar den Anbieter meint; die Begründung gehört ins
     `evidence`, damit im Report keine Sichtbarkeit behauptet wird, die es
     nicht gibt.
   - `other_citations`: aus denselben `citations` je Eintrag den Host ziehen
     (Schema und `www.` weg, Pfad und Query weg), die eigene Domain samt ihrer
     Subdomains entfernen, Dubletten entfernen, Reihenfolge der Antwort
     behalten. Einträge, die schon eine blanke Domain sind, unverändert
     übernehmen: bei Google steht die Quelldomain neben der Redirect-URL, das
     Script nimmt sie mit.
     Google-Redirect-Hosts der Grounding-API (etwa
     `vertexaisearch.cloud.google.com`) sind keine Quelle und fallen raus;
     steht daneben ein echter Domain-Eintrag, zählt der. Keine Citation heißt
     `[]`, nie `null`.
   - `evidence`: ein Satz, was die Antwort inhaltlich enthielt, plus bis zu 3
     Citation-Hosts. Beispiel: "Antwort nennt drei Anbieter, Beispielshop
     nicht darunter; Quellen: wikipedia.org, fachportal.example, ndr.de".

   Scheitert ein Call technisch (Exit 1): einmal wiederholen (Regel 4);
   scheitert er erneut, Zeile "nicht prüfbar: API-Fehler: <Meldung>".
5. **Browser-Protokoll** (`geo_method: "browser"`), alle drei Plattformen im
   Browser der Session (`method: "browser"`):

   - **google-ai**: `https://www.<google_domain>/search?q=<Query
     URL-kodiert>` öffnen, ausgeloggt und im Desktop-Viewport (Regel 7).
     Consent-Wall ablehnen (nur notwendige Cookies, wo angeboten). Der
     AI-Overview-Block rendert progressiv: erst vollständig fertig werden
     lassen, dann urteilen, sonst entstehen falsche Negative. Quellen
     aufklappen bzw. Inline-Zitate aus dem sichtbaren Block lesen. Kein AI
     Overview für die Query ist kein Fehler: beide Booleans `false`, Beleg
     "kein AI Overview für diese Query".
   - **chatgpt**: chatgpt.com mit eingeloggter Session (Login macht der
     Mensch, nie der Agent). Die Query wörtlich als Prompt, Websuche
     aktiviert, wo angeboten. Antwort vollständig fertig werden lassen, dann
     lesen.
   - **perplexity**: perplexity.ai (geht ohne Login), gleiches Vorgehen.

   Im Browser-Weg gilt für `other_citations` dasselbe wie im API-Weg, nur aus
   dem Sichtbaren: die Hosts der Quellen, die am Antwortblock stehen, ohne die
   eigene Domain, dedupliziert. Sind keine Quellen sichtbar, `[]`.

   Captcha oder fehlender Login: nicht lösen, nicht einloggen, betroffene
   Zeilen "nicht prüfbar: <Grund>" nach Regel 6.
**Der Zielordner kommt vom Aufrufer.** Solo ist `reporting/data/<heute>` der
sinnvolle Vorgabewert. **Innerhalb eines Audit- oder Report-Laufs ist es
`reporting/data/<run-id>`**, also Datum plus Kadenz (`2026-10-01-audit`,
`2026-11-01-month`). Der Orchestrator gibt den Ordner vor; wer den Pull
während eines Laufs von Hand startet, muss dieselbe Lauf-ID verwenden. Ein
Snapshot im falschen Ordner ist für die Analyse nicht vorhanden, und sie meldet
keinen Fehler, sondern rechnet ohne ihn weiter.

6. **Snapshot schreiben**: `reporting/data/<heute>/geo.json` exakt nach dem
   Schema unten, inklusive des geltenden `query_set`, der geltenden
   `competitors` und des `config_drift`-Werts aus Schritt 1. Diese Session
   baut das JSON selbst aus den Script-Outputs und dem, was sie im Browser
   gesehen hat.
7. **Kernergebnis melden**: wie viele Queries mit Brand-Erwähnung, wie viele
   mit Domain-Zitat (je Gruppe brand/category/problem), die drei häufigsten
   fremden Zitat-Domains, je Plattform die Methode
   (api/browser/nicht angeschlossen), Crawler-Blocker und llms.txt-Status.
   Auffälligkeiten benennen (etwa: Kategorie-Queries komplett ohne Erwähnung).
   Ist `config_drift` gesetzt, das an erster Stelle nennen: der Vergleich mit
   diesem Snapshot beruht auf der eingefrorenen Baseline, nicht auf dem
   aktuellen Stand der Config.

## Snapshot-Schema

`reporting/data/<heute>/geo.json`:

```json
{
  "fetched_at": "2026-08-10T12:00:00Z",
  "query_set": {
    "brand": ["Beispielshop", "Beispielshop Outdoorjacken"],
    "category": ["Outdoorjacke kaufen", "Outdoorjacken nach Maß", "Kinderset"],
    "problem": ["Wo bekomme ich Outdoorjacken her"]
  },
  "competitors": ["mitbewerber-b.example"],
  "config_drift": null,
  "queries": [
    {
      "query": "Beispielshop",
      "group": "brand",
      "platform": "google-ai",
      "method": "api",
      "brand_mentioned": true,
      "domain_cited": false,
      "other_citations": ["wikipedia.org", "ndr.de"],
      "evidence": "Antwort beschreibt Beispielshop als Outdoor-Anbieter; Quellen: wikipedia.org, ndr.de; Domain nicht dabei"
    },
    {
      "query": "Outdoorjacke kaufen",
      "group": "category",
      "platform": "chatgpt",
      "method": "api",
      "brand_mentioned": null,
      "domain_cited": null,
      "other_citations": [],
      "evidence": "nicht angeschlossen: kein API-Key"
    },
    {
      "query": "Wo bekomme ich Outdoorjacken her",
      "group": "problem",
      "platform": "perplexity",
      "method": "api",
      "brand_mentioned": false,
      "domain_cited": false,
      "other_citations": ["mitbewerber-b.example"],
      "evidence": "Antwort nennt zwei Fachversender, Beispielshop nicht darunter; Quellen: mitbewerber-b.example"
    }
  ],
  "crawlers": {
    "GPTBot": {"status": "blockiert", "rule": "Disallow: /"},
    "OAI-SearchBot": {"status": "erlaubt", "rule": "Disallow: /admin (partiell)"},
    "ChatGPT-User": {"status": "nicht erwähnt", "rule": "keine eigene Gruppe, * erlaubt"},
    "ClaudeBot": {"status": "nicht erwähnt", "rule": "keine eigene Gruppe, * erlaubt"},
    "Claude-Web": {"status": "nicht erwähnt", "rule": "keine eigene Gruppe, * erlaubt"},
    "PerplexityBot": {"status": "erlaubt", "rule": "Allow: /"},
    "Google-Extended": {"status": "nicht erwähnt", "rule": "keine eigene Gruppe, * erlaubt"},
    "CCBot": {"status": "blockiert", "rule": "Disallow: /"}
  },
  "llms_txt": false
}
```

GEO ist punktuell: kein `period`-Block, kein `comparison`. Der Report
vergleicht gegen den Vormonats-Snapshot (jüngster `reporting/data/`-Ordner mit
`geo.json`), und zwar nur Zeilen mit gleicher Plattform **und** gleicher
Methode (Regel 7). `queries` enthält immer Anzahl Queries mal drei Zeilen,
`platform` immer einer der drei festen Werte, `group` immer `brand`,
`category` oder `problem`, `method` immer `api` oder `browser`. Nicht
angeschlossene Zeilen (`geo_method: "api"`, Plattform ohne Key) tragen
`method: "api"` plus den Grund im `evidence`. Nicht prüfbare Zeilen tragen
`null`/`null` plus Grund im `evidence`, nie `false`.

`query_set` und `competitors` sind die eingefrorene Baseline (Regel 9):
wörtlich aus dem ersten Lauf übernommen und in jedem folgenden Snapshot
unverändert weitergeschrieben, unabhängig davon, was aktuell in der Config
steht. `config_drift` ist `null`, solange die aktuelle Config mit dem
geltenden `query_set` und den geltenden `competitors` übereinstimmt, sonst ein
Satz, was konkret abweicht, etwa "Config enthält eine zusätzliche
category-Query ('Outdoorjacke Herren'), die nicht Teil der eingefrorenen Baseline
ist; es zählt weiterhin die eingefrorene Liste". Ein gesetzter `config_drift`
gehört ins Kernergebnis, weil eine geänderte Zeitreihe sonst niemandem
auffällt.

`other_citations` ist immer eine Liste, nie `null`: bei nicht prüfbaren und
nicht angeschlossenen Zeilen die leere Liste. Sie hält reine Hosts ohne Schema
und ohne `www.` (`ndr.de`, nicht `https://www.ndr.de/artikel`), ohne die eigene
Domain und ohne Dubletten. Der Report rechnet daraus den Share of Voice
(Formel im Kennzahlen-Katalog); eine Domain zählt damit höchstens einmal je
Zeile.

Einordnung `google-ai` im API-Pfad: das ist Gemini mit Google-Search-Grounding,
als Proxy für Googles AI-Schicht, nicht wörtlich das AI-Overview-Modul der
SERP; im Browser-Weg ist es der echte AI-Overview-Block. Genau deshalb
vergleicht der Report nur innerhalb derselben Methode.

`crawlers` hält alle acht Schlüssel; `status` ist `erlaubt`, `blockiert` oder
`nicht erwähnt`, `rule` die entscheidende robots.txt-Zeile bzw. die kurze
Begründung. Einzige Ausnahme ist der Fehlerpfad: ließ sich robots.txt gar nicht
abrufen, steht statt der acht Schlüssel ein einzelnes
`{"error": "robots.txt nicht erreichbar nach 2 Versuchen: <Grund>"}` im
`crawlers`-Objekt (Fehlerbilder unten), nie `null`.

## Setup-Check

Für den Setup-Wizard. Die Methoden-Entscheidung (`geo_method`) fällt im
GEO-Abschnitt der Setup-Skill; hier wird nur der gewählte Weg geprüft:

1. Bei `api`: welche der drei Keys werden gefunden? (`check_env.sh` zeigt
   das samt Herkunft.) Je gesetztem Key ein Mini-Call:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/check-geo/scripts/geo_api.py" \
     --check <platform> -
   ```

   Eine OK-/Fehlerzeile, Exit 0/1.
2. Bei `browser`: Browser-Werkzeug in der Session vorhanden? Die
   `google_domain` aus der Config lädt (Consent-Wall abgelehnt, SERP
   sichtbar)? chatgpt.com zeigt eine eingeloggte Session (sonst Hinweis an
   den Nutzer, sich einzuloggen; der Agent loggt sich nie selbst ein)?
   perplexity.ai lädt?
3. Bei `off`: nichts zu prüfen.

Ausgabe: je Plattform der Stand (api, browser oder nicht angeschlossen). Schon
eine angeschlossene Plattform plus die Crawler-Matrix ergibt einen brauchbaren
Snapshot.

## Fehlerbilder

- `geo_method: "off"`: kein Lauf; der Report schreibt die eine Zeile, dass
  GEO bewusst abgeschaltet ist und sich über `/ptai-ecom:setup` aktivieren
  lässt.
- `geo_method: "api"`, Plattform ohne Key: alle ihre Zeilen `null`/`null` mit
  "nicht angeschlossen: kein API-Key". Nie im Browser improvisieren, auch
  wenn einer da wäre. Crawler-Matrix und llms.txt laufen per `curl` trotzdem;
  die Quelle gilt damit nicht als komplett ausgefallen.
- API-Call scheitert (401, 429, Timeout, Netzfehler): einmal wiederholen
  (technischer Fehlschlag, kein inhaltlicher Retry); scheitert es erneut,
  Zeile "nicht prüfbar: API-Fehler: <Meldung>". Ein 401 heißt fast immer Key
  ungültig oder abgelaufen: im Kernergebnis an den Nutzer melden.
- `geo_method: "browser"`, aber kein Browser-Werkzeug in der Session: die
  Quelle wird "nicht verfügbar (geo_method browser, aber kein
  Browser-Werkzeug in der Session)", ohne Rückfrage (Regel 8).
- ChatGPT im Browser-Weg verlangt Login: Zeilen der Plattform nach Regel 6
  auf `null` setzen, den fehlenden Login im Kernergebnis melden (kein Stopp,
  keine Frage mitten im Lauf). Nie Zugangsdaten eingeben.
- Captcha oder Bot-Erkennung im Browser-Weg: nicht lösen und nicht
  umgehen, betroffene Zeilen "nicht prüfbar: Captcha". Beim nächsten
  Monatslauf probiert es die Session regulär erneut.
- Kein AI Overview auf der Google-SERP (Browser-Weg): kein Fehler, beide
  Booleans `false` mit Beleg "kein AI Overview für diese Query".
- Browser-Antwort lädt endlos oder bricht ab: einmal neu laden (technischer
  Fehlschlag); scheitert es wieder, Zeile "nicht prüfbar: Seite lädt nicht".
- robots.txt nicht erreichbar (Netzwerkfehler, kein 404): `curl` einmal
  wiederholen; scheitert es erneut,
  `"crawlers": {"error": "robots.txt nicht erreichbar nach 2 Versuchen: <Grund>"}`
  schreiben und den Grund melden. `llms_txt` bleibt boolesch: nur HTTP 200 ist
  `true`.
- Verlockung, eine "bessere" Antwort nachzufassen: gibt es nicht. Regel 4 gilt,
  die erste Antwort zählt.
