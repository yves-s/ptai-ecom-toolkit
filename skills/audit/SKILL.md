---
name: audit
description: Einmaligen Ecommerce-Audit für einen Shop fahren, den Nullpunkt vor einem Relaunch oder für eine erste vollständige Bestandsaufnahme. Zieht alle verfügbaren Quellen maximal (volle Historie statt Berichtsmonat), lässt die Analysen als eigene Subagents laufen, verdichtet die Befunde zu einem priorisierten Maßnahmen-Backlog, friert die Baseline blockweise ein und rendert das Kunden-PDF. Nutzen bei /ptai-ecom:audit, bei einem Erstaudit, einer Bestandsaufnahme vor einem Theme- oder Relaunch, oder wenn der Nutzer den Nullpunkt für einen Shop will. Hält zweimal an (Gate A nach den Rohdaten, Gate B nach den Analysen) und lässt den Rest erst nach ausdrücklicher Freigabe laufen. Läuft je Shop nur einmal vollständig durch, ein zweiter Aufruf verweigert und verweist auf report, --backfill (leere Baseline-Blöcke nachtragen) oder --reanalyze (Phase 2 bis 4 auf denselben Rohdaten wiederholen, wenn sich eine Analyse geändert hat). Liest reporting/config.json im Kunden-Workspace, schreibt reporting/runs/<run-id>/ (Zustand, Datenlage, Screenshots-Index, Befunde, Kunden-PDF) sowie reporting/baseline/01/ und reporting/measures.json.
---

# audit: der Ecommerce-Audit-Orchestrator

Der Audit ist der Nullpunkt eines Shops, kein Report. Er läuft genau einmal
(Spec Abschnitt 3): keine Vergleichswerte, kein Vormonat, sondern je Quelle
der maximal verfügbare Zeitraum. Ergebnis ist die Baseline, gegen die jeder
spätere `/ptai-ecom:report` vergleicht, plus ein priorisierter
Maßnahmen-Backlog. Diese Skill orchestriert fünf Phasen (0 bis 4, Spec
Abschnitt 6) über zwei Skripte, fünfzehn Pull-Skills, zehn
Analyse-Subagents und zwei Module, die Baseline und Backlog schreiben. Sie ruft selbst keine API auf und rechnet keine Kennzahl,
sie steuert nur, wer wann läuft, hält den Zustand fest und legt zweimal einen
Gang ein, bevor irgendetwas in Richtung Kunde geht.

Arbeitsverzeichnis ist der Kunden-Workspace (dort liegt `reporting/`), genau
wie bei jeder anderen Skill dieses Plugins.

Anders als `report`, der nach Kadenz wiederkehrt und dreifach vergleicht
(Vorlauf, Baseline, Vorjahr), ist `audit` ein Einmal-Lauf ohne Vergleich: er
setzt den Nullpunkt, den `report` später nutzt. Beide teilen sich dieselben
Pull-Skills, dasselbe `state`-Modul und dieselbe Lauf-ID-Mechanik
(`scripts/audit/run.py`, `state.py`).

## Voraussetzungen

- `reporting/config.json` muss existieren und `scripts/audit/config.py:
  validate()` muss eine leere Fehlerliste liefern. Pflichtfelder sind
  `brand`, `domain`, `cwv_urls`, `sources`, `account_slug`, `drive_path` und
  `market`; `shopify_store`, `ga4_property_id` und `gsc_site` nur, solange ihre
  Quelle an ist (`config.SOURCE_FIELDS`). Welche Quelle Pflicht, empfohlen oder
  optional ist, steht in `scripts/audit/tiers.py`. Fehlt die Config
  komplett oder schlägt `validate()` fehl: nichts raten, nichts anlegen. In
  zwei Sätzen sagen, was fehlt, und die Skill `setup` anbieten. Sagt der
  Nutzer ja, übernimmt der Wizard; sagt er nein, hier aufhören. Das gilt für
  Phase 0 unten identisch, hier nur vorweg, weil ohne Config auch der
  Verweigerungs-Check unten sinnlos wäre.
- `config.hints()` blockiert nichts, wird aber vor dem Start einmal gezeigt.
  **Dort steht nur, was ein Mensch entscheiden muss.** Wettbewerber und
  Keyword-Seeds standen bis zum 08.09.2026 darin und sind raus: kein Pull hat
  sie je gelesen. Die Wettbewerber findet `pull-dfs-competitors` über die
  Überschneidung in den Suchergebnissen, die Keywords nimmt
  `pull-dfs-keywords` aus der Search Console. Ein Hinweis, der zu einer Arbeit
  auffordert, die niemand liest, macht ein fertiges Setup unfertig.
- Ein headless Browser für `capture-screens` und das Kunden-PDF in Phase 4
  (bevorzugt die Headless Shell von Playwright, Chrome oder Chromium gehen
  auch), bei `geo_method: browser` ein Browser-Werkzeug in der Session für
  `check-geo`, `jq` (für
  `capture-screens`), `curl` und `jq` (für
  `pull-cwv`), Shopify CLI (für `pull-shopify`), `PTAI_GOOGLE_CREDENTIALS`
  in der `.env` des Workspace; die Betreiber-Schlüssel (PageSpeed,
  DataForSEO, GEO, Ads-Token) dort oder zentral in `~/.config/ptai-ecom/.env`.
  Jedes Fehlerbild einzeln steht in der jeweiligen Pull-Skill, hier nicht
  wiederholt.

## Ein Audit läuft genau einmal je Shop

Vor jedem anderen Schritt, noch vor dem Lesen der Config im Detail: prüfen,
ob dieser Shop schon eine Baseline hat.

```bash
python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from audit import baseline

path = Path('reporting/baseline') / baseline.NUMBER / 'baseline.json'
if path.exists():
    print('vollstaendig' if baseline.is_complete('.') else 'unvollstaendig')
else:
    print('kein-baseline')
"
```

- **`kein-baseline`:** kein Audit ist je gelaufen, dieser Aufruf ist der
  erste. Weiter mit Phase 0.
- **`vollstaendig`:** alle zehn Blöcke stehen. Ein zweiter voller Audit
  bringt nichts, was `report` nicht ohnehin laufend liefert. **Verweigern**
  und auf `/ptai-ecom:report` verweisen, keine Phase startet.
- **`unvollstaendig`:** eine Baseline existiert, aber mindestens ein Block
  ist leer (regelmäßig der Fall bei `seo_visibility`, `sea` und `catalogue`,
  deren Zugänge oft erst nach dem Erstlauf kommen). Ein normaler Aufruf ohne
  Schalter **verweigert** ebenfalls, verweist aber auf `--backfill`. Der
  Nachtrag-Modus füllt ausschließlich, was `baseline.empty_blocks()` als leer
  meldet, und rührt keinen geschriebenen Block an; seine genaue Mechanik steht
  unten unter "Der Nachtrag-Modus: `--backfill`".

Diese Verweigerung gilt für den Aufruf ohne Schalter. Ruft der Nutzer
`/ptai-ecom:audit --backfill` oder `--reanalyze` ausdrücklich auf, gilt die
engere Bahn des jeweiligen Modus statt der Verweigerung.

### Wenn der erste Lauf verworfen gehört

**`--backfill` ist dafür der falsche Weg, und das ist nicht offensichtlich.**
Er füllt die leeren Blöcke und lässt die geschriebenen unangetastet, also genau
die, die mit dem alten Stand entstanden sind. Wer einen Lauf verwirft, weil
sich seither etwas an den Regeln, den Quellen oder der Config geändert hat,
bekommt damit eine Baseline aus zwei Ständen und merkt es nicht.

Am 08.09.2026 war genau das der Fall: der erste Lauf hatte den Kundentermin
getragen, danach sind an einem Tag der Crawler, die Befundregeln und die
Property-Auswahl gefixt worden, und `--backfill` hätte sieben Blöcke aus der
Zeit davor stehen lassen.

**Der Weg ist archivieren, nicht überschreiben.** Der Lauf hat einen Termin
getragen, seine Zahlen müssen nachvollziehbar bleiben:

```bash
ARCH="reporting/archiv/<run-id>-verworfen"
mkdir -p "$ARCH"
mv "reporting/data/<run-id>"  "$ARCH/data"
mv "reporting/runs/<run-id>"  "$ARCH/runs"
mv reporting/baseline         "$ARCH/baseline"
mv reporting/measures.json    "$ARCH/measures.json"
mv reporting/measures.md      "$ARCH/measures.md"
```

Dazu ein `README.md` im Archivordner, das in drei Sätzen sagt, **warum** der
Lauf verworfen wurde. Ohne den Grund ist ein Archiv nur ein Ordner, den
niemand mehr anzufassen traut.

**Drei Dateien bleiben liegen, und zwar bewusst:**

| Datei | Warum sie bleibt |
|---|---|
| `reporting/config.json` | die Zugänge und Einstellungen gelten weiter |
| `reporting/context.json` | das Kundenwissen ist der teuerste Teil und gehört keinem Lauf, sondern dem Kunden |
| `reporting/dfs-ledger.jsonl` | das Belegbuch wächst über alle Läufe und wird nie verschoben. Nach dem Verwerfen zahlt der neue Lauf die bezahlten Quellen ein zweites Mal, und genau das soll im Ledger stehen |

Danach meldet die Prüfung oben wieder `kein-baseline`, und der nächste Aufruf
läuft normal durch.

### Wenn nur die Auswertung neu gehört: `--reanalyze`

Der häufigste Fall liegt zwischen den beiden oben, und bis zum 08.09.2026 gab
es dafür keinen Weg. Die Rohdaten eines Laufs sind gut, aber die Auswertung
darüber hat sich geändert: eine Analyse ist dazugekommen, eine Prüfliste wurde
schärfer, eine Regel gefixt. Dann soll Phase 2 bis 4 erneut laufen, **auf
denselben Snapshots**.

`--backfill` ist dafür falsch, er rührt die geschriebenen Blöcke nicht an.
Verwerfen ist zu viel, es wirft die Rohdaten mit weg und kostet die bezahlten
Quellen ein zweites Mal.

**Warum die Pulls nicht mitlaufen**, obwohl sie beim ersten Lauf nur gut einen
Dollar gekostet haben: ein neuer Pull misst einen anderen Zeitpunkt. Die
Baseline ist der eingefrorene Nullpunkt, gegen den jeder spätere Report
vergleicht; wer sie mitverschiebt, liefert nicht denselben Report besser,
sondern einen anderen.

Der Ablauf, drei Schritte:

```bash
# 1. Die bisherige Fassung beiseitelegen und den Backlog zurücksetzen.
python3 -m audit.revision --workspace . --run-id <run-id>

# 2. Die Phasen 2 bis 4 wieder öffnen, Phase 0 und 1 bleiben `done`.
python3 -c "
import sys
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from audit import state
run_state = state.load('.', '<run-id>')
print(run_state.reopen_from('2-analyses'))
run_state.save()
"
```

3. Danach diese Skill erneut aufrufen. `next_phase()` liefert `2-analyses`,
   und der Lauf setzt dort an, als wäre Phase 1 gerade fertig geworden.

**Was `revision` mitnimmt und was liegen bleibt:**

| Was | Wohin | Warum |
|---|---|---|
| `findings/`, `audit.pdf`, `audit.html`, `audit-web.html` | nach `runs/<run-id>/revisions/NN/` | das ist die Fassung. Sie war ein Kundendokument oder hätte eines werden können, und ohne sie lässt sich später nicht sagen, warum eine Zahl heute anders lautet als im Termin |
| `measures.json`, `measures.md` | **Kopie** ins Archiv | der Backlog gilt über alle Läufe und bleibt im Original stehen |
| `report-text.json` | **bleibt liegen** | darin stehen die Sätze, die ein Mensch geschrieben hat. Sie gelten dem Lauf, nicht der Fassung; wer sie mitarchiviert, lässt den Betreiber sie ein zweites Mal schreiben |
| die Snapshots in `data/<run-id>/` | bleiben unangetastet | sie sind der Grund für den ganzen Modus |

**Der Backlog wird nicht geleert, er wird gesiebt.** Eine Maßnahme, die noch
auf `open` steht und nur den einen Eintrag trägt, den `create()` selbst
schreibt, hat niemand angefasst: sie entsteht gleich neu und fliegt raus.
Sobald ein Status gesetzt oder eine Historie entstanden ist, bleibt sie. Eine
neue Analyse kann denselben Befund noch einmal stellen, und die entstehende
Dublette ist billiger als eine verlorene Entscheidung. `next_id` zählt hinter
den behaltenen weiter, damit keine Kennung zweimal vergeben wird.

**Die Baseline bleibt, wie sie ist.** `baseline.write_block()` schreibt nur in
leere Blöcke, ein zweiter Durchgang von Phase 3 lässt die sieben gefüllten also
in Ruhe und füllt höchstens nach, was beim ersten Mal leer blieb. Das ist
gewollt: der Nullpunkt gehört dem Messzeitpunkt, nicht der Auswertung.

## Einstieg und Wiederaufnahme

Kein Refusal-Fall getroffen: der Lauf startet oder setzt fort.

1. **Heute einmal bestimmen** (`date.today()`), als `today` durch den
   gesamten Lauf reichen. Kein `set_source()`- und kein `write_block()`-Aufruf
   ermittelt das Datum je selbst neu: ein Lauf, der über Mitternacht reicht
   (30 bis 60 Minuten allein für Phase 1, Spec Abschnitt 6), bekäme sonst für
   Quellen desselben Laufs verschiedene Kalendertage im Zustand, und
   `run.is_due()` und die Kadenz-Logik rechnen gegen genau diese Kalendergrenze.
2. **Lauf-ID bilden:** `run.run_id(today, "audit")`, zum Beispiel
   `2026-10-01-audit`.
3. **Zustand laden oder anlegen.** `state` ist das Modul, `run_state` das
   geladene Objekt: `set_source`, `set_phase`, `source_open` und `save` sind
   Methoden **am Objekt**, nicht am Modul. Bis zum 07.09.2026 rief diese Skill
   sie an achtzehn Stellen am Modul auf, und das endet in einem
   AttributeError, mitten in Phase 1, nach einer halben Stunde Pulls. Ein Test
   hält beides jetzt auseinander.

   ```bash
   python3 -c "
   import sys
   from datetime import date
   sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
   from audit import state, run
   today = date.today()
   run_id = run.run_id(today, 'audit')
   run_state = state.load_or_new('.', run_id, 'audit', period=run.period('audit', today))
   print(run_state.next_phase())
   "
   ```

   `run.period('audit', today)` liefert `None`: ein Audit hat keinen
   Berichtszeitraum, er zieht je Quelle maximal (Spec Abschnitt 3, 5).
4. **`next_phase()` bestimmt den Einstieg.** `None` heißt: alle fünf Phasen
   stehen auf `done`, es gibt nichts zu tun (Grenzfall, siehe Verweigerung
   oben, die das eigentlich schon abfängt). Sonst ist es eine der fünf
   Phasen unten, in genau dieser Reihenfolge: `0-setup`, `1-raw-data`,
   `2-analyses`, `3-synthesis`, `4-deliverables`. Eine abgebrochene Phase
   (Status `open` oder `running`, nie `done`) wird erneut betreten, eine
   `done`-Phase nie wiederholt.
5. **Innerhalb von Phase 1 entscheidet nicht die Phase, sondern die Quelle.**
   `run_state.source_open(source)` ist `False`, sobald diese Quelle in einer
   früheren Anlauf schon `done` gemeldet wurde: sie wird nicht erneut
   gezogen, auch wenn Phase 1 insgesamt noch nicht `done` ist. Das ist der
   ganze Sinn von Zustand hier: eine bereits bezahlte DataForSEO-Abfrage
   (spätere Stufe) oder ein bereits gelaufener Shopify-Pull kostet bei einem
   zweiten Anlauf nicht noch einmal.

### Genau ein Schreiber für den Zustand

Die Pulls innerhalb von Phase 1 dürfen gleichzeitig laufen (unten,
Parallelität). **`run_state.save()` ruft ausschließlich diese Orchestrator-Ebene,
nie ein Pull selbst, und immer nacheinander, nie zwei Aufrufe gleichzeitig.**
Jeder Pull, ob als Hintergrundprozess oder als eigener Subagent gestartet,
meldet nur sein Ergebnis zurück (Dateipfad bei Erfolg, Grund bei Fehlschlag),
er lädt und speichert `state.json` nie selbst. Der Grund steht schon im Modul
(`state.py`): zwei Prozesse, die je ihren eigenen Stand laden, ihre Quelle
eintragen und speichern, überschreiben einander über `os.replace`, der letzte
Schreiber gewinnt, die Einträge der anderen sind weg, und deren Quellen
gelten beim nächsten Anlauf wieder als offen, werden also ein zweites Mal
gezogen und bei bezahlten Quellen ein zweites Mal bezahlt. Diese
Orchestrator-Ebene wartet auf jedes Ergebnis, trägt es sofort per
`run_state.set_source(source, status, file=..., reason=..., today=today)` ein und
ruft direkt danach `run_state.save()`, bevor sie das nächste Ergebnis entgegennimmt.
`today` ist immer der in Schritt 1 bestimmte Wert, nie eine neu gezogene Uhrzeit.

## Phase 0: Setup

**Was passiert:**

1. `config.validate()` gegen die gelesene `reporting/config.json`. Ist die
   Fehlerliste nicht leer: `setup` anbieten und hier aufhören. Die Phase bleibt
   `open`, nicht `failed`, damit ein späterer Aufruf wieder hier ansetzt.
   `config.hints()` einmal zeigen, blockiert nicht.
2. Den Check laufen lassen:

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/check_env.sh" .
   ```

3. **Exit-Code 0:** Stehen in den Schlusszeilen offene empfohlene oder
   optionale Quellen ("Offen, empfohlen: ..."), diese Liste einmal zeigen,
   ohne Rückfrage. Weiter.
4. **Exit-Code größer 0:** die offenen Punkte aus Rechner, Pflicht und
   Workspace zeigen, samt der "Ohne ... fehlt"-Sätze aus dem Check, dazu die
   offenen empfohlenen Quellen als Liste. Dann genau eine Frage: trotzdem
   starten? Bei Ja weiter, bei Nein `setup` anbieten, die Phase bleibt `open`.
   "Pflicht vollständig." heißt nur, dass jede Pflichtquelle laufen kann. Ein
   offener Punkt unter Pflicht, etwa ein versionierter Schlüssel des
   Dienstkontos, gehört trotzdem in die Liste vor der Frage.

**Phase 0 markiert keine Quelle.** Ein `skipped` hielte nicht:
`run_state.source_open()` gibt für jeden Status außer `done` True zurück, Phase 1
zöge die Quelle trotzdem und überschriebe den Eintrag. Eine fehlende Quelle
scheitert in Phase 1 isoliert, mit ihrem echten Grund, und Gate A weist ihn aus.

**Die Frage kommt einmal je Shop**, vor jedem Pull und jeder bezahlten Abfrage.
Das ist bewusst anders als die Kaufweg-Frage, die mitten in Phase 1 kam und
deshalb ins Setup gewandert ist.

**Artefakt:** keins von dieser Skill selbst.

**Bei Erfolg:** `run_state.set_phase('0-setup', 'done')`, `run_state.save()`.

## Phase 1: Rohdaten

**Was passiert:** jede Quelle aus `run.SOURCE_CADENCE`, deren
`run_state.source_open(source)` noch `True` ist, wird gezogen. Weil die Lauf-Kadenz
`"audit"` ist, liefert `run.is_due()` für jede Quelle sofort `True` (erste
Bedingung der Funktion: `cadence == "audit"`), Kadenz je Quelle und
`last_pulled` spielen für einen Audit keine Rolle. Einzig `source_open()`
entscheidet.

### Zwei Ordner, zwei Zwecke

`reporting/data/<run-id>/` hält die Rohdaten-Snapshots je Quelle (dieselben
Dateien, die auch die Analysen unten und später `report` lesen).
`reporting/runs/<run-id>/` hält den Lauf selbst: `state.json`, das
Gate-A-Blatt, den Screenshots-Index, die Befunde je Disziplin.

`reporting/dfs-ledger.jsonl` liegt **außerhalb** der Lauf-Ordner und wächst
über alle Läufe hinweg: eine Zeile je bezahltem DataForSEO-Aufruf, mit Tag,
Endpunkt und echtem Betrag. Sie wird nie gelöscht und nie überschrieben, sie
ist das Belegbuch, aus dem sich die Kosten je Kunde und Lauf ohne Fremdsystem
nachvollziehen lassen (Spec Abschnitt 13).

**Wichtig, weil sonst Phase 2 nichts findet:** `pull-gsc`, `pull-ga4`,
`pull-cwv`, `check-geo` und `pull-shopify` zeigen in ihrer eigenen Ablauf-
Beschreibung noch `--out "reporting/data/$(date +%F)"` (nur das Tagesdatum,
ohne Kadenz-Suffix), weil diese Skills auch für `report` und den Wochen-Puls
gelten und aus der Zeit vor der Lauf-ID-Konvention stammen. **Für einen Audit
gilt das nicht:** der Zielordner ist immer `reporting/data/<run-id>`
(`--out` entsprechend setzen), genau wie es `crawl-site` bereits richtig
vormacht und wie es die zehn Analyse-Subagents in Phase 2 auch erwarten
(`reporting/data/<run-id>/shopify.json` und so weiter, nie
`reporting/data/<heute>/...`). Ein Pull, der versehentlich in den
Tages-Ordner statt in den Lauf-Ordner schreibt, liefert Phase 2 eine leere
Analyse, ohne dass irgendwo ein Fehler auftaucht.

### Wer heute schon zieht, wer noch nicht gebaut ist

| Quelle (Schlüssel) | Skill | Betriebsart in diesem Lauf |
|---|---|---|
| `shopify` | `pull-shopify` | Session baut den Snapshot selbst (kein Script). `SINCE` auf ein Datum weit vor jeder realistischen Shop-Gründung (praktisch: `2010-01-01`), `UNTIL` gestern. **ShopifyQL liefert dabei auch für Zeiträume ohne Daten eine Zeile je Intervall**, bei `TIMESERIES month` also einen Eintrag für jeden Monat seit `SINCE`, die meisten davon auf Null. Diese Zeilen unverändert übernehmen und in `notes.by_month` festhalten, wie viele davon Umsatz tragen: wer sie ungefiltert als Monate zählt, verwässert jeden Durchschnitt und jede Saisonalität. Ob die Historie tatsächlich so weit zurückreicht, meldet Schritt 2 der Skill selbst (`read_all_orders`-Prüfung, `notes.order_history` im Snapshot bei Kappung auf 60 Tage) |
| `ga4` | `pull-ga4` | Script, `--max-history --audit-checks`, schreibt `ga4-max-history.json` mit gemessenem `history_from`. **`--compare-properties` aus `config.compare_properties()` immer mitgeben**, wenn der Shop mehr als eine Property beliefert: ohne den Vergleich kann keine Aussage über fehlende oder doppelte Käufe stimmen. **`--audit-checks` gehört an jeden Audit**: der Schalter prüft auf Bot-Profile und einen zweiten Absender je Mess-ID und zieht die Zahlen ohne Profil und nur mit dem ersten Absender dazu, bevor Phase 2 eine einzige GA4-Rate rechnet (Abschnitt "Bot-Profile und Absender" in `pull-ga4`). Am 13.09.2026 standen ohne ihn drei Befunde eines echten Audits auf Bot-Sitzungen und doppelt gezählten Ereignissen |
| `gsc` | `pull-gsc` | Script, `--max-history`, schreibt `gsc-max-history.json` mit gemessenem `history_from` |
| `cwv` | `pull-cwv` | Script, kein Zeitraum-Schalter nötig (rollierendes 28-Tage-Fenster plus CrUX-Wochenhistorie sind schon das Maximum) |
| `geo` | `check-geo` | Script bei `geo_method: "api"`; bei `"browser"` Foreground mit Login durch den Menschen; bei `"off"` kein Snapshot, Quelle `skipped` |
| `crawl` | `crawl-site` | Script, `--out` bereits korrekt run-id-basiert dokumentiert. **Umfang und Pause kommen aus `audit.config.crawl_budget(config)`**, nie aus dem Prompt: `--max-urls` und `--delay` damit belegen. Ein ungebremster Crawl kostet ein Vielfaches des übrigen Laufs (Spec Abschnitt 3, "Was ein Lauf kostet") |
| `screens` | `capture-screens` | Script für die Seitentypen, Browser-Werkzeuge für den Kaufweg. Läuft automatisiert. **`config.checkout_capture()` entscheidet, nicht der Lauf:** `True` nimmt den Kaufweg auf, `False` lässt ihn aus und weist die Lücke aus, `None` heißt, die Config beantwortet die Frage nicht |

Aus Stufe 2 sind acht weitere Quellen dazugekommen:

| Quelle (Schlüssel) | Skill | Betriebsart in diesem Lauf |
|---|---|---|
| `catalogue` | `pull-shopify-catalog` | Session sammelt die CLI-Seiten, dann `catalog_build.py`. **Nach `pull-shopify`**, gleiche Auth, gleiches Punktebudget |
| `shop_tech` | `pull-shopify-tech` | Session holt einen Block über die CLI, dann `shop_tech_build.py` mit `--crawl` auf die `crawl.json` desselben Laufs. **Nach `crawl-site`** |
| `ads` | `pull-ads` | Script. Ohne `PTAI_GOOGLE_ADS_TOKEN` oder ohne Kontozugang: `skipped` mit Grund, Block SEA bleibt leer. **Ungeprüft gegen die echte API**, siehe Verifikationsliste in der Skill |
| `dfs_rankings` | `pull-dfs-rankings` | Script, zwei bezahlte Aufrufe (Bestand, Share of Voice), die Historie nur mit `--with-history` |
| `competitors` | `pull-dfs-competitors` | Script, ein bezahlter Aufruf. Seeds sind `geo_queries.category`, **nie Markenbegriffe** |
| `shopping` | `pull-dfs-shopping` | Script, task-basiert mit Wartezeit. **Zuerst starten**, er dauert am längsten |
| `dfs_keywords` | `pull-dfs-keywords` | Script, ein bezahlter Aufruf je 1.000 Begriffe. **Nach `pull-gsc`**, er nimmt dessen Top-Queries mit. Ungeprüft gegen die echte API |
| `backlinks` | `pull-dfs-backlinks` | Script, fünf bezahlte Aufrufe, quartalsweise fällig. Ungeprüft gegen die echte API |

Die übrigen drei Schlüssel (`esp`, `meta`, `reviews`) haben weiterhin keine
Pull-Skill, sie kommen in Stufe 3. Zwei Schlüssel sind gar keine Pulls: `cwv_lab` holt
`pull-cwv` mit, `measures` führt Phase 3. Für jede noch nicht gebaute Quelle:
`run_state.set_source(source, "skipped", reason="Pull noch nicht gebaut", today=today)`.
Das ist kein Fehler, sondern der dokumentierte Ausbaustand, und Gate A weist es
genauso aus wie jede andere Lücke.

### Reihenfolge innerhalb von Phase 1

Vier Abhängigkeiten, die sonst niemand sieht:

1. **`pull-dfs-shopping` zuerst anstoßen.** Task-basiert mit Wartezeit, alles
   andere läuft daneben weiter.
2. **`pull-gsc` vor `pull-dfs-keywords`**, sobald der gebaut ist: der nimmt
   dessen Top-Queries mit.
3. **`crawl-site` vor `pull-shopify-tech`.** Der liest Skript-Hosts und
   Mess-IDs aus `crawl.json` statt selbst zu crawlen.
4. **`pull-shopify` vor `pull-shopify-catalog`.** Dieselbe Auth, und die
   Scope-Prüfung steht in `pull-shopify`.

Läuft eine Vorbedingung nicht, ist das kein Abbruch: der abhängige Pull läuft
ohne den Teil und schreibt einen Vermerk. Genau dafür sind die Vermerke gebaut.

### DataForSEO kostet Geld, und deshalb gibt es eine dritte Bahn

Die DataForSEO-Pulls laufen **sequenziell**, nicht parallel. Der Grund ist
derselbe wie beim Einzelschreiber für `state.json`, nur eine Ebene höher: der
Budgetdeckel wird gegen die Summe in `reporting/dfs-ledger.jsonl` geprüft. Zwei
parallele Pulls sehen beide denselben Stand, halten beide den Deckel für
eingehalten und geben beide aus. Der Deckel greift dann um genau die Summe zu
spät, die parallel lief.

Der Orchestrator gibt jedem mit auf den Weg: `--budget-cap` aus
`config.json > dfs_budget_usd`, `--location-code` und `--language-code` aus
`config.market()`, dazu `--run-id`, `--run-date`, `--account-slug` und
`--workspace`. **Die beiden Markt-Schalter haben keinen Vorgabewert:** ein
still angenommenes Deutschland misst für einen Shop in einem anderen Markt
Zahlen, die plausibel aussehen und zum falschen Land gehören.

Kommt ein Pull mit `BudgetExceeded` zurück:

- diese Quelle wird `skipped` mit dem Grund aus der Meldung, **nicht** `failed`.
  Der Deckel ist eine Entscheidung, kein Defekt.
- die **übrigen DataForSEO-Quellen ebenfalls `skipped`**, mit demselben Grund
  und ohne weiteren Versuch. Sie einzeln anlaufen zu lassen kostet Laufzeit für
  ein Ergebnis, das schon feststeht.
- alle anderen Quellen laufen normal weiter.
- Gate A weist die Lücke aus wie jede andere, samt der bis dahin verbrauchten
  Summe aus dem Ledger.

**Der Deckel ist die Bremse, nicht die Sandbox.** Wer einen Lauf ausprobieren
will, setzt `--budget-cap` klein und lässt ihn echt laufen. Der Schalter
`--sandbox` liefert Dummy-Werte und ist nur ein Rauchtest der Verkabelung; ein
Snapshot daraus trägt `"sandbox": true` und gehört in keinen Kundenordner.

### Parallelität, zwei Bahnen

- **Skript-Pulls, hintergrundfähig:** `pull-ga4`, `pull-gsc`, `pull-cwv`,
  `crawl-site`, `check-geo` bei `geo_method: "api"`. Diese und `pull-shopify`
  (braucht kein Script, aber auch keinen Menschen) dürfen gleichzeitig laufen,
  als parallele Hintergrundprozesse oder als parallele Subagents, je einer
  pro Quelle. Jeder bekommt Lauf-ID, Quelle und Zielordner mit auf den Weg und
  meldet nur sein Ergebnis zurück (Regel oben: nie selbst `state.json`
  anfassen).
- **Foreground, sequenziell, weil sie einen Browser steuern:**
  `capture-screens` (der Kaufweg bis zur Zahlungsauswahl, automatisiert, aber
  in einem sichtbaren Browser) und `check-geo` bei `geo_method: "browser"`.
  Sie laufen in der Hauptsitzung statt in einem Hintergrund-Subagent, weil
  sich ein Browser nicht parallel von mehreren Stellen steuern lässt. Sie
  blockieren die übrigen Pulls nicht, die laufen daneben weiter.

  **Der Kaufweg wird nie im Lauf erfragt.** Die Aufnahme legt einen echten
  Testwarenkorb im Produktivshop an, und daraus entsteht ein
  Abandoned-Checkout-Datensatz, auf den ein E-Mail-Werkzeug eine
  Warenkorbabbrecher-Strecke auslösen kann. Das ist eine Entscheidung, aber
  eine für das Setup und einmal je Kunde, nicht eine Rückfrage nach vierzig
  Minuten Pulls.

  `config.checkout_capture()` liefert `None`, wenn das Feld fehlt. Dann läuft
  der Kaufweg **nicht**, die Lücke steht in Abschnitt 13, und der Lauf sagt
  einmal am Ende von Phase 1: *"checkout_capture fehlt in der Config, der
  Kaufweg blieb aus. Mit `true` im Setup kommt er beim nächsten Lauf dazu."*
  Am 08.09.2026 fragte der Audit stattdessen mitten in Phase 1, mit einer
  Frage, die ohne Vorwissen über Klaviyo-Strecken nicht zu beantworten war.
  Yves dazu: *"So eine Frage sollte einfach gar nicht kommen."*

  **Einen Menschen braucht davon nur noch eines:** der Login bei `check-geo`
  mit `geo_method: "browser"` ("macht der Mensch, nie der Agent",
  check-geo/SKILL.md). Der Kaufweg braucht keinen mehr; er liest vor jedem
  Schritt die Seite, bricht bei einer unerwarteten Stufe ab statt zu raten,
  und hält an der Zahlungsart-Auswahl. `checkout_capture: false` in der Config
  überspringt ihn ganz.

Ein Fehler in einer einzelnen Quelle bleibt isoliert (Grundregel des
Plugins, `CLAUDE.md`): `run_state.set_source(source, "failed", reason=..., today=today)`,
die übrigen Quellen laufen weiter. Erst wenn wirklich jede Quelle fehlschlägt,
gibt es nichts für Gate A zu zeigen; das ist dann selbst der Befund.

### `screens.json` ist ein eigener Schritt dieser Phase, kein Nebeneffekt

`capture-screens` beschreibt in ihrem eigenen Ablauf, dass sie
`reporting/runs/<run-id>/screens.json` selbst schreibt. Diese
Orchestrator-Ebene verlässt sich darauf nicht stillschweigend: **sie
schreibt beziehungsweise prüft den Index selbst**, direkt nachdem
`capture-screens` fertig ist, aus genau den Bild-Einträgen und der
`not_configured`-Liste, die `capture-screens` in ihrem Ablauf Schritt 4
bis 6 sammelt (Felder `page_type`, `device`, `captured_at`, `source_url`,
`path`, optional `manual`). Erst danach gilt die Quelle als erledigt:
`run_state.set_source("screens", "done", file="reporting/runs/<run-id>/screens.json", today=today)`.
Ohne diesen expliziten Schritt bleibt der Index eine Absichtserklärung
irgendwo in einer anderen Skill, und die Analysen in Phase 2 (respektive eine
spätere Content-Analyse) finden keine Bilder, ohne dass ein Fehler
auftaucht. Bei `geo_method: "off"` gilt dieselbe Vorsicht sinngemäß nicht,
weil dort bewusst gar kein Snapshot entsteht.

**Bei Erfolg der Phase:** `run_state.set_phase('1-raw-data', 'done')`,
`run_state.save()`. Direkt danach: Gate A.

## Gate A: Datenlage-Blatt

**Artefakt:** `reporting/runs/<run-id>/source-status.md`. Diese Orchestrator-
Ebene schreibt sie, aus dem `sources`-Teil von `state.json` plus, wo nötig,
einem Blick in die jeweilige Snapshot-Datei (state.json allein kennt
"abgeschnitten" nicht, das steht nur im Snapshot selbst).

Je gezogener Quelle eine Zeile: Status, Grund, gemessener Beginn der Historie
sofern vorhanden.

| Quelle | Status | Grund | Historie ab |
|---|---|---|---|
| ga4 | vorhanden | | 2024-03-01 (`history_from`) |
| gsc | abgeschnitten | API-Grenze, mehr als 16 Monate liefert Google nie | 2025-06-01 (`history_from`) |
| shopify | abgeschnitten | `read_all_orders` fehlt im Grant, Historie hart auf 60 Tage begrenzt | siehe `notes.order_history` |
| geo | vorhanden | | keine Historie möglich, dieser Lauf ist Messpunkt 1 |
| cwv | vorhanden | | 28 Tage Feld, rund 25 Wochen CrUX-Historie |
| crawl | vorhanden | | (kein Zeitraum, Momentaufnahme) |
| screens | vorhanden | | (kein Zeitraum, Momentaufnahme) |

Statuswerte und ihre Herkunft:

- **vorhanden:** `state.json` trägt `done`, der Snapshot trägt keine
  einschränkende Notiz.
- **abgeschnitten:** `state.json` trägt ebenfalls `done`, aber der Snapshot
  selbst trägt eine Einschränkung (`shopify.json > notes.order_history`, oder
  ein `history_from`, das spürbar später liegt als GA4-Property- respektive
  Search-Console-Anmeldung). Der Grund kommt wörtlich aus dieser Notiz.
- **fehlend:** `state.json` trägt `failed`, Grund ist der gemeldete
  Fehlergrund dieser Quelle.
- **übersprungen:** `state.json` trägt `skipped`, entweder weil die Pull-
  Skill in dieser Stufe noch nicht existiert (die 13 Quellen oben) oder weil
  `geo_method: "off"` GEO bewusst abgeschaltet hat. Diese Zeilen kommen als
  kurze Liste, nicht als volle Tabellenzeile je Quelle, sonst verschwinden
  die sieben tatsächlich gezogenen Quellen zwischen dreizehn identischen
  Einträgen.

**Die Zeile ga4 trägt die beiden Prüfungen aus `--audit-checks` mit.** Ein
auffälliges Bot-Profil gehört mit Anteil und Zeiträumen
(`bot_profiles.profiles[].share_of_sessions`, `.windows`) in den Grund, doppelt
gezählte Stufen mit ihrem Beginn (`senders.double_counted_events`,
`senders.onset`). Beides entscheidet, auf welchen Zahlen Phase 2 rechnet, und
der Mensch soll es vor der Freigabe sehen, nicht erst im Report. Ist eine der
beiden Prüfungen nicht gelaufen (`bot_profiles.checked` oder
`senders.measurable` falsch), steht ga4 auf **abgeschnitten**, mit der Notiz
als Grund: jede GA4-Rate stünde sonst auf ungeprüften Sitzungen.

**Dann hält der Lauf an.** Datenlage zeigen, ausdrücklich fragen, ob Phase 2
(Analysen) starten soll. **Die Skill fährt nie von selbst mit Phase 2 fort,
auch nicht, wenn alle sieben Quellen sauber "vorhanden" melden.** Ein Lauf,
der dieses Gate überspringt, verstößt gegen den Kern dieser Skill, nicht
gegen eine Nebenregel. Bei "nein" oder ausbleibender Antwort bleibt
`state.json` unverändert bei Phase `1-raw-data` auf `done` stehen; ein
späterer Aufruf von `/ptai-ecom:audit` nimmt über `next_phase()` genau bei
Phase 2 wieder auf, ohne eine einzige Quelle erneut zu ziehen.

## Phase 2: Analysen

**Was passiert:** die Analyse-Subagents starten, je einer pro Disziplin,
parallel (ein Aufruf pro Subagent in derselben Nachricht, damit sie
tatsächlich gleichzeitig laufen). Jeder bekommt im Aufruf-Prompt die Lauf-ID
und liest ausschließlich seine feste, in seiner eigenen Definition genannte
Dateiliste unter `reporting/data/<run-id>/`, nie das Verzeichnis als Ganzes
(Spec Abschnitt 13: "Die Analysen lesen nicht alles").

**Seit dem 07.09.2026 laufen alle zehn Subagents** (`agents/audit-*.md`,
die Ziel-Ausbaustufe aus Spec Abschnitt 8). Die sechs neuen kamen mit den
Pulls, auf denen sie sitzen:

| Subagent | Disziplin | Liest |
|---|---|---|
| `audit-data-quality` | Datenqualität und Messung | `shopify.json`, `ga4.json`, `gsc.json`, `crawl.json` |
| `audit-commerce` | Handel und Wirtschaftlichkeit | `shopify.json` |
| `audit-traffic` | Traffic und Kanäle | `ga4.json`, `gsc.json`, `geo.json` |
| `audit-seo-technical` | SEO technisch | `crawl.json`, `gsc.json`, `cwv.json` |
| `audit-seo-content` | SEO Inhalte und Sortiment | `dfs-rankings.json`, `dfs-keywords.json`, `dfs-competitors.json`, `catalog.json`, `gsc.json`, `crawl.json` |
| `audit-geo` | GEO | `geo.json`, `crawl.json` |
| `audit-sea` | SEA | `ads.json`, `dfs-shopping.json`, `dfs-rankings.json`, `catalog.json` |
| `audit-conversion` | Shop und Conversion | `ga4.json`, `screens.json`, `crawl.json`, `shop-tech.json`, **plus `lens-purchase-path`** |
| `audit-content-brand` | Content und Marke | `catalog.json`, `crawl.json`, `screens.json`, **plus `lens-assortment`** |
| `audit-competition` | Wettbewerb | `dfs-competitors.json`, `dfs-backlinks.json`, `dfs-shopping.json`, `dfs-rankings.json`, `geo.json` |
| `audit-trust` | Trust und Compliance | `crawl.json`, `screens.json`, `shop-tech.json`, **plus `lens-trust`** |

### Drei Analysen laden eine Linse

`audit-conversion`, `audit-content-brand` und `audit-trust` bekommen ihre
Prüfliste nicht aus sich selbst, sondern aus einer Skill: `lens-purchase-path`,
`lens-assortment` und `lens-trust`. Alle drei sind kuratierte Methode,
`lens-purchase-path` trägt den Sieben-Punkte-Rahmen aus `marketing-skills:cro`,
`lens-assortment` den Produktseiten-Teil aus `claude-seo:seo-ecommerce`,
`lens-trust` die acht Pflichtangaben-Punkte samt der Regel, dass eine
Feststellung kein Rechtsurteil ist.

**Dafür steht `Skill` in ihrem Frontmatter, und nur bei diesen dreien.** Ein
Subagent mit `tools: Read, Write, Bash` kann keine Skill laden; ein Skillname
in seinem Prompt wäre dann eine Überschrift ohne Wirkung. Genau daran hing es
bis zum 08.09.2026: die drei Linsen lagen fertig im selben Plugin, waren in
ihrer eigenen Beschreibung ausdrücklich für den grossen Audit vorgesehen, und
kein Aufruf hat sie je geladen. Die Conversion-Analyse stellte stattdessen
vier frei formulierte Fragen und lieferte vier Befunde bei fünf offenen
Punkten, mit allen sechzehn Screenshots auf der Platte.

**Die Linse schreibt im grossen Audit keine eigene Datei.** In `audit-light`
liefert sie `L<n>-<lens>.json` im Verkaufs-Schema mit `crit`, `warn` und `ok`;
hier ist der Subagent der Schreiber, und es gilt das Befund-Schema seiner
eigenen Definition. Die Übersetzung steht dort, nicht hier.

**`audit-trust` ist der Träger, den `lens-trust` gebraucht hat.** Bis zum
08.09.2026 prüfte der kostenlose Verkaufs-Audit für einen kalten Lead die
Pflichtangaben und der bezahlte Vollaudit nicht, weil Pflichtangaben in keine
der zehn Disziplinen passten. Sie haben jetzt ihre eigene, die elfte
(`trust`), und ihre eigene Sektion im Report (Nummer 6, direkt hinter der
Conversion, weil sie dieselbe Frage beantwortet: was hält einen Menschen davon
ab, hier zu kaufen).

### Was der Kunde eingeordnet hat, geht mit in jeden Prompt

Der Audit misst von außen und kennt den fachlichen Grund nicht. Am
08.09.2026 stand "Ein großer Teil der aktiven Produkte ist in keiner Variante
kaufbar" als Befund mit Schweregrad `hoch` im Kundenreport, und der Grund war
schlicht:
die Ware ist ausverkauft. Die Rückfrage des Kunden war nicht "das stimmt
nicht", sondern **"wie gebe ich euch das zurück, damit es beim nächsten Mal
drinsteht?"**.

`reporting/context.json` ist die Antwort. Sie hält die Aussagen, die der
Kunde zu früheren Befunden gegeben hat, und Phase 2 hängt sie an den Prompt
jedes Subagents:

```bash
python3 -c "
import sys
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from audit import context
eintraege = context.load('.')
fehler = context.validate(eintraege)
if fehler:
    print('FEHLER in reporting/context.json:'); print('\n'.join(fehler))
else:
    print(context.as_prompt(eintraege))
"
```

Meldet die Prüfung Fehler, **wird die Datei repariert, bevor Phase 2
startet**, statt sie zu überspringen: eine stillschweigend wirkungslose
Kundenaussage ist schlimmer als gar keine, weil beide Seiten glauben, sie
sei angekommen. Ist die Ausgabe leer, gibt es kein Kundenwissen, und der
Abschnitt entfällt im Prompt ganz. Ein leerer Abschnitt erzeugt sonst die
Illusion, es hätte welches gegeben und nichts habe gepasst.

Die Regel, was ein Subagent damit tut, steht in seiner eigenen Definition
(Ausgabeschema-Punkt 8): ein Befund, den ein Eintrag erklärt, wird nicht
erneut gestellt, sondern fällt weg oder wird auf die Teilmenge eingeengt,
die der Eintrag nicht erklärt. Widerspricht ein Eintrag den Zahlen, gewinnen
die Zahlen, und der Widerspruch gehört sichtbar in den Befund.

**Der Weg hinein ist ein Gespräch, keine Oberfläche.** Der Kunde antwortet
auf einen Befund mit dessen Kennung ("HDL-07 stimmt so nicht, die sind
ausverkauft"), im Chat, in einer Mail oder im Termin. Wer den Audit führt,
legt daraus einen Eintrag an:

```bash
python3 -c "
import sys
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from audit import context
print(context.add('.',
    'Die nicht kaufbaren Produkte sind ausverkauft, kein technischer Fehler.',
    ['HDL-07', 'HDL-08'], 'reason', 'Termin 08.09.2026, Mara'))
"
```

`kind` ist eines von vier: `reason` (der fachliche Grund hinter einem
Zustand), `decision` (bewusst so und soll so bleiben), `planned` (läuft
schon), `correction` (unsere Messung war falsch). Einträge werden nur
angehängt, nie ersetzt: eine geänderte Einschätzung ist ein neuer Eintrag,
der den alten benennt.

**Ein Subagent startet auch dann, wenn seine Quellen in Phase 1 gefehlt
haben.** Er meldet die Lücke dann selbst als `blocked_questions`, und genau
diese Meldung braucht Gate B, um zu zeigen, was der fehlende Zugang kostet.
Wer ihn vorher aussortiert, spart einen Aufruf und verliert die einzige
Stelle, an der die Lücke beziffert wird.

**`audit-conversion` und `audit-content-brand` lesen Screenshots**, also
Bilddateien im Kundenordner, nicht nur JSON. Sie brauchen dafür keine
Sonderbehandlung durch den Orchestrator, aber sie laufen länger als die
übrigen acht. Das ist kein Hänger.

`audit-data-quality` steht im fertigen Report an erster Stelle: ist die
Messung kaputt, ist jede Zahl der übrigen neun eine Behauptung, kein Befund
(Spec Abschnitt 8, mit dem Pilot-Beleg: 70 Prozent Zuordnungslücke
zwischen Shopify und GA4).

**Welches Modell je Subagent.** Neun der zehn tragen `model: sonnet` in
ihrem Frontmatter: sie rechnen und klassifizieren gegen ein festes
Ausgabeschema (Anteile bilden, Statuscodes einordnen, Kanalanteile gegen
Schwellen halten, `null` von 0 unterscheiden), dafür reicht Sonnet.
`audit-data-quality` trägt bewusst keinen Eintrag und erbt damit das
Session-Modell, in der Regel das stärkere: er deutet Widersprüche zwischen
vier Quellen (ist die Lücke zwischen Shopify-Bestellungen und
GA4-Purchase-Events ein Zuordnungsverlust oder ein anderer Bestellweg?) und
entscheidet damit über die Gültigkeit aller übrigen Analysen. Das
fehlende `model:` dort ist die Entscheidung, kein Versehen. Der Test
`scripts/tests/test_agent_frontmatter.py` hält diese Tabelle und die
Agent-Dateien zusammen; er prüft außerdem, dass kein Agent eine Eingabedatei
unter einem Namen nennt, den kein Pull schreibt. Der Orchestrator
selbst lässt sich nicht festlegen, eine `SKILL.md` kennt kein
`model:`-Frontmatter, er läuft immer im Session-Modell.

**Artefakt:** `reporting/runs/<run-id>/findings/<disziplin>.json`, je
Subagent selbst geschrieben (`data-quality.json`, `commerce.json`,
`traffic.json`, `seo-technical.json`, `seo-content.json`, `geo.json`,
`sea.json`, `conversion.json`, `content-brand.json`, `competition.json`),
fünf Felder je Befund (`statement`, `evidence`, `effect`, `confidence`,
`effort`) plus `blocked_questions`.

**`findings/geo.json` ist nicht `data/<run-id>/geo.json`.** Gleicher
Dateiname, anderer Ordner: der eine ist der Befund des Subagenten, der andere
der Rohdaten-Snapshot, den er gelesen hat. Phase 3 liest den Befund.

**Bei Fehler:** ein Subagent, der abstürzt oder keine Datei schreibt, bleibt
isoliert. Die übrigen laufen weiter, Gate B weist die fehlende Disziplin mit
Grund aus, statt den ganzen Lauf zu stoppen. Fehlt einem Subagenten eine
seiner Eingabedateien (Quelle in Phase 1 "fehlend" oder "übersprungen"), sagt
er das als eigenen Punkt in seinem Ergebnis, nie als geratene Zahl.

**Bei Erfolg:** `run_state.set_phase('2-analyses', 'done')`, `run_state.save()`.
Direkt danach: Gate B.

## Die Abnahme: `audit.qa`

**Vor Gate B und noch einmal am Ende von Phase 4.** Das audit-light hat ein
Beleg-Gate und eine Übergabe-Checkliste, und beide haben dort Fehler gefangen,
bevor ein Kunde sie gesehen hat. Der große Audit hatte bis zum 08.09.2026
keins von beidem, nur Regeln in dieser Skill, und die gelten so weit, wie eine
Sitzung sie liest. Am 07.09.2026 ist genau deshalb ein Befund aus einem
Parser-Fehler zur Schlagzeile geworden, obwohl drei Regeln hier ihn verboten
haben.

```bash
python3 -m audit.qa --workspace . --run-id <run-id> --phase 2
```

Prüft ohne Urteil: Schema und Pflichtfelder je Befund, Schweregrad aus den
drei erlaubten Stufen, Ersatzumlaute, Werkzeugsprache in Feldern, die der
Kunde liest, die Selbstprüfung des Crawlers, gedrosselte Seiten, und ob der
Shop eine GA4-Mess-ID lädt, die nicht zur gezogenen Property gehört.

**Rückgabewert 1 heißt: nicht freigeben.** Warnungen allein brechen nichts ab,
sie sind eine Bitte hinzusehen. Am Ende gibt das Script die Liste dessen aus,
was ein Mensch entscheiden muss, weil es Urteil braucht: die Zahlen der ersten
Seite gegen die Wirklichkeit, die Kennungen, ob in jedem Kapitel auch steht,
was gut ist.

**Nichts davon gehört in den Aufruf-Prompt.** Wer eine Prüfung von Hand
mitgeben muss, hat sie beim nächsten Lauf vergessen.

### Die Belegprüfung: `audit.evidence`

Direkt nach `audit.qa`, im selben Atemzug, und aus demselben Grund als Script.

```bash
python3 -m audit.evidence --workspace . --run-id <run-id>
```

`qa` prüft, ob ein Befund ein `evidence`-Feld **hat**. Diese Prüfung nimmt
das Feld ernst und hält es gegen den Lauf: existiert die genannte
Snapshot-Datei, und führt sie den genannten Pfad? Nennt ein Befund ein Bild,
steht es im Screenshot-Index, und liegt es auf der Platte?

Das ist die Übertragung des Beleg-Gates aus `audit-light` auf einen Lauf, der
überwiegend aus Snapshots misst. Dort wird jeder Befund mit URL live gegen die
Seite gehalten; hier zeigen die Belege auf Felder wie
`crawl.json > summary.max_click_depth`, und der passende Test ist nicht der
Abruf, sondern die Auflösung. Ein Beleg, der ins Leere zeigt, ist im Ergebnis
dasselbe wie eine widerlegte Behauptung, nur schwerer zu bemerken: er sieht
aus wie ein Beleg.

Vier Verdikte, drei davon in Ordnung. `resolved` heisst, das Feld ist da.
`prose` und `external` sind Belege ohne Feldbezug, etwa eine eigene Messung
oder eine URL, und werden gezählt, nicht bemängelt. Die drei Fehlerfälle sind
`missing_field`, `missing_file` und `missing_image`, und jeder nennt die
Kennung des Befunds.

**Rückgabewert 1 heisst: dieser Befund geht nicht an den Kunden, solange der
Beleg nicht sitzt.** Zwei Auswege, kein dritter: den Beleg auf das Feld
zeigen lassen, das die Zahl wirklich trägt, oder den Befund streichen. Den
Beleg unverändert stehen lassen und weitermachen ist keiner.

Gegen den ersten echten Lauf gehalten löste die Prüfung 177 von 178 Belegen
auf. Der eine, der ins Leere zeigte, nannte ein Bild `checkout-warenkorb.png`,
während der Index `warenkorb-gefuellt.png` führte. Der Befund stand im
Kundendokument.

### Ein Aufruf, drei Dateien

```bash
python3 -m audit.report_build --workspace . --run-id <run-id> --pdf
```

Schreibt `audit.html` (Druckfassung), `audit-web.html` (Web-Fassung mit
Navigation und Filter) und rendert das PDF. **Alle drei aus einem
`content()`-Aufruf**, damit Zahlen und Befunde nicht zweimal durch dieselbe
Ableitung laufen und zwischen den Fassungen auseinandergehen.

Bis zum 09.09.2026 war die Web-Fassung ein eigenes Kommando, und beim ersten
echten Lauf ist genau das passiert, was bei einem Schritt in zwei Aufrufen
immer passiert: das PDF war gerendert, die Web-Fassung fehlte, und der Lauf
sah fertig aus. `--no-web` lässt sie weg, wenn wirklich nur die Druckfassung
gebraucht wird.

## Gate B: Befunde vorlegen

Bevor irgendetwas in Richtung Baseline oder Maßnahmen-Backlog geht (beides
sind Kundendokumente im weiteren Sinn, `baseline.md` und `measures.md`
gehen so oder in Auszügen an den Kunden), werden die Befunde aus allen
vorliegenden `findings/<disziplin>.json`-Dateien gezeigt: je Disziplin die
Anzahl Befunde, die mit `confidence: "hypothesis"` markierten separat (die
werden nie Maßnahme, sondern Test, Spec Abschnitt 9), und bei fehlenden
Disziplinen der Grund aus Phase 2.

**Getrennt davon die `blocked_questions` je Disziplin**, also die Kernfragen,
die mangels Eingabe unbeantwortet blieben, gruppiert nach der fehlenden Datei.
Sie sind keine Befunde über den Shop und gehen nicht einzeln in den Backlog:
fünf unbeantwortete Fragen wegen einer fehlenden Datei sind eine Lücke, nicht
fünf. Am Gate zeigen sie, wie viel des Audits diese eine Lücke kostet, und
genau das ist die Entscheidungsgrundlage dafür, ob Phase 3 jetzt läuft oder
erst nach dem Nachziehen der Quelle.

**Welche Analyse zu dünn steht, sagt das Script, nicht das Augenmaß.**
`audit.evidence` zählt je Disziplin die Befunde gegen die
`blocked_questions` und benennt jede, die mindestens so viel offenlassen
musste, wie sie beantwortet hat. Das ist die Abdeckungs-Regel aus
`audit-light`, übertragen auf einen Lauf ohne Score: dort bekommt eine
geblockte Linse keinen Punktwert, sondern eine im Report ausgewiesene Lücke,
weil sie sonst dieselben 92 Punkte bekäme wie ein wirklich guter Shop.

Für eine so benannte Disziplin gibt es an diesem Gate zwei Auswege und keinen
dritten:

1. **Die fehlende Quelle nachziehen** und die Analyse erneut laufen lassen.
   Das ist der Regelfall, wenn die Lücke an einer Datei hängt, die es geben
   könnte.
2. **Die Lücke steht im Report**, im Kapitel dieser Disziplin, in einem Satz,
   der sagt, was nicht geprüft werden konnte und warum.

**Weiterlaufen, ohne eins von beidem, ist keiner.** Am 08.09.2026 stand die
Conversion-Analyse mit vier Befunden gegen fünf offene Fragen, die offenen
Fragen wurden an diesem Gate gezeigt und durchgewunken, und im fertigen
Kundendokument war von der Lücke nichts mehr zu sehen. Das Kapitel las sich
wie ein Befund über den Shop, obwohl es ein Befund über den Lauf war.

**Dann hält der Lauf erneut an** und fragt ausdrücklich, ob Phase 3
(Synthese) starten soll. Dieselbe Regel wie bei Gate A: kein automatisches
Weiterlaufen, und "nein" lässt `state.json` bei Phase `2-analyses` auf
`done` stehen, ein späterer Aufruf setzt über `next_phase()` bei Phase 3 an.

## Phase 3: Synthese

**Was passiert:** aus den Befunden werden zwei Dinge, in dieser Reihenfolge:
erst die Baseline blockweise schreiben (Schritt 1 und 2), dann die Befunde in
den Maßnahmen-Backlog überführen (Schritt 3 und 4).

### Schritt 1: Baseline blockweise schreiben

Für jeden der zehn Blöcke aus `baseline.BLOCKS`, in dieser Reihenfolge:

| Block | Quelle(n) | Quell-Schlüssel im `state` | seit |
|---|---|---|---|
| `commerce` | `shopify.json` | `shopify` | ja |
| `traffic` | `ga4.json` | `ga4` | ja |
| `conversion` | `ga4.json` plus `shopify.json` | `ga4`, `shopify` | ja |
| `seo_search` | `gsc.json` plus `crawl.json` | `gsc`, `crawl` | ja |
| `seo_visibility` | `dfs-rankings.json` plus `dfs-keywords.json` plus `dfs-backlinks.json` | `dfs_rankings`, `dfs_keywords`, `backlinks` | ab Stufe 2 |
| `geo` | `geo.json` | `geo` | ja |
| `sea` | `ads.json` | `ads` | ab Stufe 2 |
| `tech` | `cwv.json` plus `crawl.json` | `cwv`, `crawl` | ja |
| `catalogue` | `catalog.json` | `catalogue` | ab Stufe 2 |
| `measurement` | errechnet aus `shopify.json` und `ga4.json`, kein eigener Pull | `shopify`, `ga4` | ja |

Ein Block wird nur geschrieben, wenn **alle** seine Quell-Schlüssel aus der
Spalte "Quell-Schlüssel im `state`" auf `done` stehen, geprüft mit
`not run_state.source_open(source)` je Schlüssel. Fehlt eine, bleibt der Block
leer, wird also nicht geschrieben, und wartet auf den Nachtrag-Modus (siehe
"Ein Audit läuft genau einmal je Shop" oben). Ein halb gefüllter Block ist
schlimmer als ein leerer: er ist eingefroren und lässt sich nie mehr
vervollständigen. `baseline.write_block()` verweigert eine leere `values`
ohnehin, das ist im Modul kein Sonderfall, sondern die Bestätigung genau
dieser Regel.

**Jeder Block trägt seine Herkunft mit.** `write_block()` verlangt neben
`values` ein `sources`-Dict, und zwar je Quell-Schlüssel des Blocks einen
Eintrag mit `pulled_at` und, sofern die Quelle einen Zeitraum abdeckt,
`period`. Beides steht bereits vor: `pulled_at` in `run_state.sources[source]`,
`period` im Snapshot der Quelle (`period` bzw. bei den Maximalzeitraum-Pulls
`period` plus `history_from`). Der Orchestrator stellt es zusammen:

```python
sources = {}
for source in block_source_keys:
    entry = run_state.sources[source]
    provenance = {"pulled_at": entry["pulled_at"]}
    snapshot = json.loads((data_dir / entry["file"]).read_text(encoding="utf-8"))
    if snapshot.get("period"):
        provenance["period"] = snapshot["period"]
    sources[source] = provenance

baseline.write_block(workspace, block, values, run_id=run_id, today=today,
                     sources=sources, trust=trust,
                     known_gaps=("repeat_rate", "return_rate"))
```

### Eine kaputte Messung wird eingefroren, nicht weggelassen

**Der Nullpunkt hält fest, was der Shop über sich wusste.** Findet der Audit
eine falsche Messung, gehört ihre Zahl trotzdem in die Baseline: sie ist der
Zustand, auf dem die Entscheidungen des Kunden beruhten. Wer sie weglässt,
behauptet, es hätte sie nie gegeben, und nimmt sich die Erklärung für den
Sprung, der kommt, sobald die Messung repariert ist.

**Gefährlich wird sie erst als Nenner.** Eine Conversion Rate aus einer um
Faktor 3,6 überhöhten Sitzungszahl sieht aus wie eine Kennzahl, ist aber
keine, und sie vererbt den Fehler an jede Rechnung, die sie weiterverwendet,
ohne dass ihr das noch anzusehen wäre. Genau diese Unterscheidung erzwingt
`write_block()` über den Pflichtparameter `trust`:

```python
trust = {
    "sessions": {
        "status": "contaminated",
        "reason": "Analytics zählt 3,64-mal so viele Besuche wie der Shop "
                  "selbst als Menschen zählt",
        "break": "2026-06",
        "finding": "MES-03",
    },
    "conversion_rate": {"derived_from": ["sessions"]},
}
```

Der erste Eintrag friert die kaputte Zahl bewusst ein. Der zweite scheitert
mit `ContaminatedInput`, weil er sie als Nenner benutzt.

| Status | Bedeutung |
|---|---|
| `measured` | gemessen und brauchbar. Vorgabe, wenn ein Wert keinen Eintrag hat |
| `contaminated` | gemessen, aber nachweislich falsch. Braucht `reason`, möglichst `break` und `finding` |
| `not_measurable` | gar nicht messbar, der Wert ist `None` und gehört zusätzlich in `known_gaps` |

**`trust={}` ist erlaubt und heißt "alles gemessen".** Die Mechanik ist
dieselbe wie beim Preistest: erzwungen wird kein Urteil, sondern dass der
Aufrufer hingesehen hat. Wer eine kaputte Messung durchwinkt, tut das dann
sichtbar statt aus Versehen.

**Das `break`-Datum ist der Teil, der später zählt.** Es macht den Vergleich
ehrlich: der nächste Report nach der Reparatur sagt "die Reihe bricht im Juni
2026, davor und danach ist nicht vergleichbar" statt "Sitzungen minus 70
Prozent". Ohne das Datum sieht eine geheilte Messung aus wie ein Einbruch,
und dann diskutiert jemand über einen Traffic-Verlust, den es nie gab.

**Eine belastbare Ersatzquelle schlägt beides.** Misst eine zweite Quelle
dieselbe Sache sauber, gehört sie in den Block, und die kaputte daneben:
bei Sitzungen etwa die Zählung des Shops, die automatisierten Verkehr selbst
trennt, gegen die Zahl aus Analytics. Dann trägt der Nullpunkt den echten
Wert **und** den, auf den der Kunde bis dahin geschaut hat.

Das ist keine Buchhaltung um ihrer selbst willen. Der Tag, an dem ein Block
festgeschrieben wird, und der Tag, an dem seine Zahlen gezogen wurden, sind im
Erstlauf derselbe und beim Nachtrag zwei verschiedene. Ohne die Trennung liest
jeder spätere Vergleich das Festschreibedatum als Messzeitpunkt und rechnet
gegen einen Tag, an dem nie gemessen wurde. Der abgedeckte Zeitraum gehört aus
demselben Grund dazu: "Umsatz je Monat über die volle Historie" ist ohne
Anfang und Ende keine Aussage. `baseline.render()` zeigt beides je Block als
eigene Tabelle.

### Korrekturen nach dem Einfrieren

**Der Wert bleibt, der Vermerk wächst.** Ein geschriebener Block ist
unveränderlich, das Wissen über seine Zahlen nicht: später zeigt sich etwa,
dass ein Betrag in einer anderen Währung steht oder dass die Begründung zu
grob war. Dann wird weder der Wert geändert noch `reason` umgeschrieben,
sondern der Vermerk des Werts bekommt von Hand in `baseline.json` einen
Eintrag unter `corrections`, das Datum als `JJJJ-MM-TT`:

```json
"revenue_analytics": {
  "status": "contaminated",
  "reason": "Zwei Mess-IDs zählen jeden Kauf doppelt.",
  "break": "2026-05",
  "finding": "MES-01",
  "corrections": [
    {"date": "2026-10-15",
     "note": "Doppelt gezählt wird nur ein Teil der Käufe, nicht jeder, belegt am 14.10.2026. Die Begründung oben ist damit überholt."}
  ]
}
```

Neue Korrekturen kommen ans Ende der Liste, ältere bleiben stehen. So ist
nachvollziehbar, was an welchem Tag bekannt war, und die ursprüngliche
Begründung bleibt lesbar, auch wenn eine Korrektur sie überholt.

**Ein Wert ohne Vermerk, der sich später als falsch herausstellt,** bekommt
einen neuen Eintrag mit `status`, `reason`, `break` und `finding` und dazu
eine Korrektur mit dem Tag, an dem das belegt wurde. Ohne dieses Datum liest
sich der Vermerk, als wäre der Fehler schon beim Einfrieren bekannt gewesen.

Danach `baseline.render(workspace)` laufen lassen. `baseline.md` zeigt den
Status in Klammern hinter der Zahl und darunter als Zitat Grund, Monat des
Bruchs, Befund und jede Korrektur mit Datum; bei `measured` heißt der Grund
dort "Hinweis". Bei einer Zeitreihe oder Liste steht das Zitat zwischen
Überschrift und Zahlen. Nennt ein Vermerk einen Wert, den es in `values`
nicht gibt, oder einen unbekannten Status, bricht `render()` ab: ein
vertippter Schlüssel ließe den Vermerk sonst still aus `baseline.md`
verschwinden.

**Die Datei mit Python `json` zurückschreiben**, also
`json.dumps(data, indent=2, ensure_ascii=False)` plus Zeilenumbruch, so wie
`baseline.py` sie anlegt. Andere Werkzeuge schreiben `0.0` als `0` und ändern
damit Werte eingefrorener Blöcke, wenn auch nur in der Schreibweise.

### Die Sperre: ein laufender Test friert keine Conversion ein

**Diese Sperre ist seit dem 06.09.2026 Code, keine Bitte.**
`baseline.write_block()` verlangt für `commerce` und `conversion` den
Parameter `price_test`; fehlt er, scheitert der Aufruf. Die Angabe kommt aus
`gates.price_test_verdict(crawl, findings)`:

```python
from audit import gates

crawl = json.loads((data_dir / "crawl.json").read_text(encoding="utf-8"))
findings = json.loads((run_dir / "findings" / "data-quality.json").read_text(encoding="utf-8"))
verdict = gates.price_test_verdict(crawl, findings.get("findings"))

baseline.write_block(workspace, "conversion", values, run_id=run_id, today=today,
                     sources=sources, price_test=verdict)
```

**Warum als Pflichtangabe und nicht als Schalter:** ein Parameter, den der
Aufrufer selbst auf "blockiert" setzen müsste, erzwingt nichts, denn wer den
Test kennt, ruft `write_block()` gar nicht erst auf. Erzwingend ist die
Umkehrung: **die Abwesenheit der Prüfung ist der Fehler.** Vergessen scheitert
damit, und genau das kann ein Satz in dieser Datei nicht leisten.

Drei Ausgänge:

| `verdict` | Was passiert |
|---|---|
| `checked: False` | Abbruch. "Nicht geprüft" ist keine Freigabe |
| `running: True` | `PriceTestRunning`, der Block wird ausgesetzt, Grund in den Gate-Bericht |
| `checked: True, running: False` | Block wird geschrieben, der Beleg wandert in sein `as_of` |

`gates.price_test_verdict()` sieht in zwei Quellen nach: den inline eingebauten
Kennungen und Fremdskripten aus `crawl.json` (dort steht ein Werkzeug wie
Intelligems im Seitenquelltext) und den Befunden aus
`findings/data-quality.json`, weil `audit-data-quality` in Kernfrage 6
ausdrücklich danach sucht. Der zweite Weg ist der wichtigere: ein
server-seitig ausgespielter Test hinterlässt im Quelltext nichts.

**Ein negativer Befund ist kein Beweis.** Er heißt "kein bekanntes Werkzeug
gefunden", und der Beleg im Block sagt das auch so. Die Markerliste in
`gates.PRICE_TEST_MARKERS` ist durch Beobachtung gewachsen; wer ein weiteres
Werkzeug antrifft, ergänzt sie dort.

Der Grund ist die Unveränderlichkeit. Conversion Rate und Warenkorbwert eines
Shops, über dem ein Preistest läuft, sind ein Mischwert aus zwei oder mehr
Varianten. Als Nullpunkt eingefroren, vergleicht jeder spätere Report gegen
etwas, das nie ein Zustand des Shops war, sondern ein Durchschnitt über ein
Experiment. Der Befund allein reicht nicht: er landet im Backlog, und daneben
steht die verunreinigte Zahl für immer in der Baseline. Am 06.09.2026 ist der
Fall im ersten echten Lauf aufgetreten, ein Preis- und Angebotstest lief
site-weit über den gesamten Messzeitraum.

Aufgehoben wird die Sperre über `--backfill`, sobald der Test beendet und ein
sauberes Fenster gemessen ist. Der nachgetragene Block trägt dann sein eigenes
`as_of` und ist damit sichtbar ein späterer Messpunkt.

**Die übrigen Blöcke sind davon nicht betroffen.** Ein Preistest verändert
Conversion und Warenkorbwert, nicht die Zahl der Seiten im Crawl, die Core Web
Vitals oder die GEO-Sichtbarkeit.

`seo_visibility`, `sea` und `catalogue` haben seit dem 07.09.2026 ihre
Quell-Schlüssel (`dfs_rankings`, `dfs_keywords`, `backlinks`, `ads`,
`catalogue`) und werden wie jeder andere Block behandelt: geschrieben, sobald
ihre Quellen `done` sind, sonst leer für einen späteren `--backfill`. Ein
fehlender Google-Ads-Zugang oder ein erreichter DataForSEO-Budgetdeckel ist
damit kein Sonderfall dieser Skill mehr, sondern derselbe Weg wie bei jeder
ausgefallenen Quelle. `measurement` hat keinen eigenen Pull,
sondern wird aus zwei bereits gezogenen Quellen errechnet (Schritt 2 unten);
geschrieben wird der Block trotzdem erst, wenn beide zugrundeliegenden
Quellen (`shopify`, `ga4`) `done` sind, aus demselben Grund wie jeder andere
Block.

### Schritt 2: Die Kennzahlen je Block

Welche Zahl aus welchem Quellfeld kommt und mit welcher Formel, steht in
`reference/metrics.md` und wird hier nicht wiederholt, nur verlinkt. Diese
Skill rechnet nicht selbst, sie schlägt nach und übernimmt das Ergebnis in
die `values` des jeweiligen Blocks:

| Block | Abschnitt in `reference/metrics.md` |
|---|---|
| `commerce` | 1. Shop (`shopify.json`): Umsatz brutto/netto, Bestellungen, AOV, Repeat-Rate |
| `traffic` | 2. Traffic (`ga4.json`): Sessions, Nutzer, Umsatz aus GA4. **Die Monatsreihe kommt aus `by_month[]`, die Kanalanteile daraus aus `by_month[].channels[]`**, nicht aus dem `channels[]` auf oberster Ebene: das ist die Summe über den ganzen Zeitraum, und Spec Abschnitt 10 verlangt "Sessions je Monat und Kanal". Beide unverändert übernehmen, ohne eigene Formel |
| `conversion` | 1. Shop: Conversion Rate gesamt, Micro-Conversion-Funnel; 2. Traffic: Conversion Rate je Kanal |
| `seo_search` | 3. SEO (`gsc.json`): Klicks, Impressionen, CTR, Position. **Je Monat aus `by_month[]`**, zusätzlich die Summe aus `totals`. Spec Abschnitt 10 verlangt "je Monat"; `daily` selbst wandert nicht in die Baseline, dafür ist es zu lang |
| `geo` | 5. GEO (`geo.json`): Brand-Erwähnungsquote, Citation Rate, Share of Voice, Crawler-Zugang, llms.txt |
| `tech` | 4. Core Web Vitals (`cwv.json`): LCP, INP, CLS, Lab-Performance-Score, je Seitentyp aus `pages[]` |
| `seo_visibility` | noch nicht im Katalog, siehe die drei Ausnahmen unten |
| `sea` | noch nicht im Katalog, siehe die drei Ausnahmen unten |
| `catalogue` | noch nicht im Katalog, siehe die drei Ausnahmen unten |
| `measurement` | noch nicht im Katalog, siehe Ausnahme unten |

**Mit Bot-Profil oder zweitem Absender stehen `traffic` und `conversion` auf
denselben Zahlen wie Befunde und Report.** `ga4_variants.compare()` rechnet die
Raten, die Felder stehen in `ga4.json`:

- **`conversion`:** Gibt es `bot_profiles.without`, kommen Funnel und
  Conversion Rate je Kanal daraus, für Stufen und Käufe in
  `senders.double_counted_events` aus dessen `primary_sender`. Eine Rate aus
  allen Sitzungen gehört nicht daneben: ihr Nenner ist nachweislich zu hoch.
- **`traffic`:** `by_month[]` gibt es nur aus allen Sitzungen, der Pull zieht
  keine Monatsreihe ohne das Profil. Die Reihe wird trotzdem eingefroren, weil
  der Kunde auf diese Zahlen geschaut hat, und die Sitzungen je Monat und Kanal
  bekommen `trust` `contaminated`: `reason` nennt das Profil und seinen Anteil
  an allen Sitzungen (`bot_profiles.profiles[].share_of_sessions`), `break` den
  Monat aus dem ersten `windows[].start`, `finding` die Kennung des Befunds zum
  Bot-Profil. Sitzungen und Kanäle ohne das Profil stehen für den
  Berichtszeitraum als eigene Werte daneben, aus `bot_profiles.without`. Zählt
  der Kauf doppelt, bekommt der Umsatz aus GA4 dasselbe, mit `break` aus
  `senders.onset`.

Nicht jeder Wert, den Spec Abschnitt 10 für einen Block nennt, ist
tatsächlich befüllbar. Die Lücken stehen bereits so in den
Analyse-Subagents und werden hier nicht anders behauptet, ein Block wird
trotzdem geschrieben, nur ohne die fehlenden Werte:

- **Retourenquote und Kohorten** (`commerce`) fehlen, weil `shopify.json` in
  diesem Ausbaustand kein passendes Feld führt
  (`agents/audit-commerce.md`, Kernfrage 4 und 6).
- **Sortimentskonzentration** (`commerce`) hat noch keine eigene Zeile in
  `reference/metrics.md`. Bis der Katalog nachzieht, kommt der Wert aus
  genau der Rechnung, die `agents/audit-commerce.md` in Kernfrage 5 schon
  beschreibt (Anteil der Top-3- und Top-10-Titel an `totals.total_sales`),
  mit Zähler und Nenner daneben, nie als Prozentzahl ohne Beleg.
- **Indexierte Seiten** (`seo_search`) hat ebenfalls noch keine Formel-Zeile.
  Der Wert ist eine Auszählung aus `gsc.json > index_sample` (Anteil
  `verdict: PASS`) beziehungsweise `crawl.json > pages[].indexable`, mit
  Anmerkung, welche der beiden Quellen gezählt wurde.
- **Conversion Rate je Gerät** (`conversion`) hat noch keine Formel-Zeile.
  `ga4.json > devices[]` führt `sessions`, `total_users`, `purchase_revenue`
  und `purchases`; die Rate ist `purchases / sessions` je Gerät, mit Zähler
  und Nenner daneben. Aus Shopify kommt sie nicht, dort ist die Conversion
  Rate nicht nach Gerät aufgeteilt. Trägt ein Snapshot statt `purchases` nur
  `transactions` (Lauf vor dem 11.09.2026), bleibt der Wert leer: in
  `transactions` zählt GA4 Refunds mit. Nicht schätzen, nicht aus dem
  Kanal-Wert ableiten.
- **Anteil Nicht-Marken-Klicks** (`seo_search`) folgt der Klassifikation aus
  `agents/audit-traffic.md`, Kernfrage 5 (`gsc.json > top_queries` gegen
  `geo.json > query_set.brand`), ebenfalls noch ohne eigene Katalog-Zeile.

Diese fünf Lücken sind kein Fehler dieses Tasks, sondern der dokumentierte
Ausbaustand: der Katalog wächst mit den Aufgaben, die eine Formel zuerst
brauchen, nicht auf Vorrat.

**Jede Lücke wird angemeldet.** `write_block()` nimmt seit dem 06.09.2026 ein
`known_gaps`, und jedes Feld mit `None`, das dort nicht steht, führt zum Abbruch.
Der Grund ist ein Tippfehler aus dem ersten echten Lauf: ein falscher
Quellfeldname liefert `None`, `render()` schreibt "nicht berechenbar", und der
Block ist unveränderlich. Aus einem Vertipper wird so eine gemessene Lücke.
`known_gaps` zwingt dazu, jede Lücke bewusst zu benennen, und trennt sie damit
vom Fehler.

**Ein fehlender Wert wird weggelassen, nie als Null geschrieben.** Ein Block
ist unveränderlich, sobald er steht: eine 0 für die Retourenquote oder für die
Conversion Rate je Gerät wäre für immer eine gemessene Null statt einer
Lücke, und der erste Folgereport rechnet eine Bewegung aus, die nie
stattgefunden hat. `baseline.render()` schreibt für einen fehlenden Wert
"nicht berechenbar", und genau so gehört er in die `values`: als `None`, nicht
als Zahl und nicht als leerer String.

**Die drei Stufe-2-Blöcke stehen ebenfalls hier statt im Katalog.** Sie sind
seit dem 07.09.2026 befüllbar, und ihre Quellfelder wandern mit den übrigen
Nachträgen in `reference/metrics.md`. Bis dahin gilt, was hier steht.

**Block `seo_visibility`** (Spec Abschnitt 10: "Anzahl Ranking-Keywords,
Sichtbarkeitsverlauf, verweisende Domains"):

| Wert | Quellfeld | Anmerkung |
|---|---|---|
| Ranking-Keywords gesamt | `dfs-rankings.json > summary.ranked_keywords_total` | der Bestand, **nicht** `ranked_keywords_delivered` und nicht die Länge von `top_keywords` |
| Keywords in den Top 3, Top 10, Top 100 | `dfs-rankings.json > summary.top_3`, `.top_10`, `.top_100` | kumulativ, aus `metrics.organic` gerechnet. `null` heißt "nicht gemessen", nie 0 |
| Geschätzter organischer Traffic | `dfs-rankings.json > summary.etv` | Schätzwert der Datenbank, keine gemessene Sitzung |
| Sichtbarkeitsverlauf je Monat | `dfs-rankings.json > visibility_history[]` | nur vorhanden, wenn der Lauf mit `--with-history` lief. Fehlt er, bleibt der Wert weg, statt aus einem Punkt eine Reihe zu machen |
| Verweisende Domains | `dfs-backlinks.json > summary.referring_domains` | dazu `referring_main_domains`, das ist die Zahl ohne Subdomains |
| Autoritätswert | `dfs-backlinks.json > summary.rank` | DataForSEO-eigene Skala, nur gegen sich selbst über die Zeit vergleichbar |
| Suchvolumen der eigenen Begriffe | `dfs-keywords.json > summary.search_volume_total` | dazu `keywords_without_data`, sonst liest sich die Summe als Vollerhebung |

**Block `sea`** (Spec Abschnitt 10: "Ausgaben je Monat, ROAS, Impression
Share, Anteil Ausgaben ohne Conversion"):

| Wert | Quellfeld | Anmerkung |
|---|---|---|
| Ausgaben je Monat | `ads.json > by_month[].cost` | Währung aus `ads.json > currency` mit in den Block, das Konto rechnet nicht zwingend in Euro |
| ROAS je Monat | `ads.json > by_month[].roas` | `null` bei Ausgaben von 0. Nie als 0 schreiben, sonst rechnet der erste Folgereport eine Erholung aus, die es nicht gab |
| Impression Share je Monat | `ads.json > by_month[].search_impression_share` | impressionsgewichtet über den Monat, plus die beiden Verlustanteile `search_budget_lost_impression_share` und `search_rank_lost_impression_share` |
| Anteil Ausgaben ohne Conversion | `ads.json > summary_search_terms.cost_without_conversion` geteilt durch die Summe aus `by_month[].cost` | Zähler und Nenner mit in den Block, die Anteilszahl allein ist nicht nachrechenbar |

**Block `catalogue`** (Spec Abschnitt 10: "Anzahl Produkte und Collections,
Anteil mit vollständigen SEO-Feldern, Anteil Bilder mit Alt-Text"):

| Wert | Quellfeld | Anmerkung |
|---|---|---|
| Produkte gesamt und aktiv | `catalog.json > summary.products_total`, `.products_active` | |
| Collections gesamt | `catalog.json > summary.collections_total` | dazu `collections_without_description` |
| Anteil mit vollständigen SEO-Feldern | aus `catalog.json > summary.products_without_seo_title` und `.products_without_seo_description` gegen `products_total` | **Ein Produkt gilt nur als vollständig, wenn beide Felder da sind.** Die zwei Zähler überschneiden sich, ihre Summe ist deshalb keine Anzahl unvollständiger Produkte. Schreib beide Zähler und den Nenner in den Block, statt eine Summe zu bilden, die zu hoch ist |
| Anteil Bilder mit Alt-Text | `catalog.json > summary.share_images_with_alt` | schon gerechnet. `null` heißt "keine Bilder im Katalog", nicht "kein Bild hat Alt-Text": vor der Deutung `images_total` prüfen |
| Varianten ohne SKU und ohne Einkaufspreis | `catalog.json > summary.variants_without_sku`, `.variants_without_cost` gegen `variants_total` | trägt `catalog.json > notes` den Hinweis, dass keine einzige Variante einen Einkaufspreis hat, gehört er als `known_gap` in den Block: Marge ist für diesen Shop nicht berechenbar |

**Alle drei Blöcke tragen ihre Erhebungsgrenze mit.** Die DataForSEO-Werte
kommen aus einer Datenbank, nicht aus einer Live-Messung (`dfs-rankings.json
> notes` sagt das), die Ads-Werte sind bis heute nicht gegen ein echtes Konto
geprüft (`ads.json > notes`), und die Shopping-Abdeckung ist eine Untergrenze
über die geprüften Begriffe, keine Vollerhebung. Diese Vermerke gehören in die
`sources` des Blocks, nicht in eine Fußnote: `baseline.render()` zeigt sie
unter der Blocküberschrift, und ohne sie liest der nächste Report die Zahlen
als gemessen.

**Ausnahme: die Zuordnungslücke für den Block `measurement`.** Weil sie neu
ist, steht sie hier direkt statt auf eine noch nicht existierende Zeile in
`reference/metrics.md` zu verlinken. Sie wandert in Task 21 in den Katalog.

- **Aussage:** welcher Anteil der tatsächlichen Shopify-Bestellungen in GA4
  nicht als `purchase` ankommt.
- **Formel:** `1 - (ga4.json > funnel.purchase.events / shopify.json >
  totals.orders)`, in Prozent.
- **Quellfeld:** `shopify.json > totals.orders`,
  `ga4.json > funnel.purchase.events`.
- **Beleg für die Formel:** dieselbe Rechnung wie Kernfrage 1 in
  `agents/audit-data-quality.md`, dort mit dem Pilot-Beleg Beispielshop
  (drei von zehn Bestellungen zugeordnet, 70 Prozent Lücke, dieselbe
  Größenordnung in GA4).
- **Nicht zu verwechseln** mit der "Zuordnungslücke Bestellungen" aus
  `reference/metrics.md` Abschnitt 1: die dortige Formel misst die Lücke
  innerhalb von Shopifys eigener `sessions.conversion_rate` und gehört zum
  Block `conversion`, nicht zu `measurement`. Der Block `measurement` hält
  ausschließlich den Abgleich gegen GA4.

### Schritt 3: Befunde werden Maßnahmen

Für jede Datei in `reporting/runs/<run-id>/findings/` und jeden Befund
darin ein Aufruf von `measures.create()`.

**`blocked_questions` läuft nicht durch `create()`.** Aus ihnen entsteht
**höchstens eine** Maßnahme je fehlender Eingabe, nie eine je Frage, und ihr
Titel benennt die Handlung, die die Lücke schließt ("GA4-Property für das
Dienstkonto freischalten lassen"), nicht die Frage, die offen blieb. Die
betroffenen Kernfragen gehören in ihre `evidence`, damit im Backlog steht, was
an dieser einen Freischaltung hängt. Ohne diese Regel entstehen aus zwei
fehlenden Zugängen ein Dutzend Backlog-Zeilen, die alle dasselbe verlangen; am
06.09.2026 waren es sechs für zwei Handlungen.

**`create()` verändert `backlog` nicht, es gibt ein neues Dokument zurück.**
Der Rückgabewert muss also zugewiesen werden, sonst läuft die Schleife ins
Leere und `save()` schreibt einen leeren Backlog, ohne dass irgendwo ein
Fehler entsteht. Genau so geschrieben:

```python
backlog = measures.load_or_empty(workspace)
for finding in findings:
    backlog = measures.create(
        backlog, title=..., discipline=..., evidence=...,
        confidence=..., leverage=..., effort=..., responsible=...,
        data_source=..., check_rule=..., finding_ref=finding["id"],
        today=today)
```

Jeder Befund geht durch diesen Aufruf, unabhängig von seiner `confidence`. `create()` entscheidet
allein aus `confidence`, ob daraus eine Maßnahme (`type: "measure"`) oder ein
Test (`type: "test"`) wird (Spec Abschnitt 9: "eine Hypothese wird nie
priorisiert, sie wird als Test formuliert"). Kein Filtern vor dem Aufruf,
das übernimmt das Modul selbst.

Feste Feldabbildung von Befund auf `create()`-Parameter:

| Befund-Feld | `create()`-Parameter | Umformung |
|---|---|---|
| `statement` | `title` | als Handlung umformuliert ("Alt-Text ergänzen" statt "37 Bilder ohne Alt-Text") |
| `discipline` des **Dokuments**, nicht des einzelnen Befunds | `discipline` | Die Agents schreiben `{"discipline": ..., "run_id": ..., "generated_at": ..., "findings": [...]}`; der einzelne Befund trägt das Feld nicht. `finding["discipline"]` liefert deshalb `None`, und `create()` wirft. Der Wert kommt aus der obersten Ebene der Datei und gilt für alle ihre Befunde. Ansonsten unverändert. Die Agents schreiben bereits die Schreibweise, die `measures.LABELS` und `measures.PRIORITY_DISCIPLINE` kennen (`data_quality`, `seo_technical`). Die gültigen Werte stehen in `${CLAUDE_PLUGIN_ROOT}/scripts/audit/measures.py` unter `LABELS["discipline"]`; wer einen Subagenten darauf verpflichtet, gibt ihm diesen Pfad mit, denn im Kunden-Workspace gibt es die Datei nicht. Hier wird nichts umgeschrieben: eine Umwandlung an dieser Stelle wäre eine Regel in Prosa, und die erste Sitzung, die sie überspringt, bekommt Datenqualitäts-Befunde, die nie nach oben priorisiert werden und im Kundendokument unübersetzt stehen. Die Dateinamen tragen weiter Bindestriche, das ist Dateinamens-Konvention und betrifft den Feldwert nicht |
| `evidence` | `evidence` | unverändert übernommen |
| `confidence` | `confidence` | unverändert übernommen, entscheidet in `create()` über `type` |
| `effect` | `leverage` | gegen die Baseline-Zahlen eingeordnet (Spec Abschnitt 9): `high`, wenn die betroffene Kennzahl mindestens ein Drittel des relevanten Blocks ausmacht (Umsatz-, Session- oder Klickanteil) oder eine Diagnose-Schwelle aus `reference/metrics.md` klar reißt; `low`, wenn sie unter der plugin-weiten Auffälligkeits-Schwelle von 20 Prozent liegt oder eine Randgröße betrifft; sonst `medium`. Wo sich der Effekt rechnen lässt, steht die Rechnung im `effect`-Satz des Befunds selbst, sonst bleibt es beim Band, nie eine erfundene Zahl |
| `effort` | `effort` | unverändert übernommen |

Drei Parameter kennt die Analyse nicht, sie entstehen erst hier:

- **`responsible`:** aus der Disziplin abgeleitet. Bei dem, was der Betreiber
  für den Kunden umsetzt (SEO, GEO, SEA, Shop und Conversion, Technik),
  `"Path to AI"`. Der gespeicherte Wert meint den Betreiber, nicht die Firma;
  im Kundendokument steht dafür der Name aus `PTAI_OPERATOR_NAME`, sonst
  "Dienstleister" (`measures.responsible_label()`). Bei rein geschäftlichen
  Entscheidungen (Sortiment, Preis, Rückgabepolitik) `"Customer"`, bei einer
  Fremdintegration (etwa ein Katalog-Feed aus einem ERP) `"Third Party"`. Eine
  Heuristik, kein Automatismus: passt sie im Einzelfall nicht, entscheidet die
  Sitzung nach Kontext.
- **`data_source`:** wo das Feld, das die Maßnahme ändert, tatsächlich
  gepflegt wird, konkret benannt (zum Beispiel "Shopify-Theme",
  "Shopify-Produktverwaltung", "GA4/GTM-Property", "DNS/Sitemap"), nie
  pauschal "Shopify". Verhindert Arbeit, die beim nächsten Sync verschwindet
  (Spec Abschnitt 9, Beispiel der Kunde mit ein Middleware-System).
- **`check_rule`:** wie ein Folgelauf feststellt, ob die Maßnahme umgesetzt
  ist. **Ohne `check_rule` wird `create()` für diesen Befund nicht
  aufgerufen:** eine Maßnahme, deren Umsetzung sich nie feststellen lässt,
  bleibt für immer offen und verstopft den Backlog. Lässt sich keine
  automatische Regel aus einem künftigen Snapshot-Feld formulieren, ist die
  Prüfregel eine Frage an den Menschen, wörtlich als solche formuliert (etwa
  "Frage an den Kunden: ist die Rückgabepolitik seit dem Audit geändert
  worden?"), nie ein leerer Wert.

  **Die Regel benennt den beobachtbaren Zustand, nie die Datei.** Sie steht im
  Kundendokument unter "Erledigt, wenn", und dort gilt die Vokabular-Regel wie
  überall: der Leser hat Fragen zu seinem Shop, keine zu unseren Snapshots.
  "Mehr als 100 verschiedene Seitentitel über die geprüften Seiten" ist
  richtig, `"crawl.json: mehr als 100 verschiedene Title-Werte"` nicht. Der
  Folgelauf weiß selbst, in welcher Datei er nachsieht.
- **`finding_ref`:** die Kennung des Befunds, aus dem die Maßnahme folgt, also
  `finding["id"]`. Ohne sie zeigt der Report eine Handlung ohne Herkunft, und
  der Leser kann sie nicht beauftragen. Das war die Beanstandung vom
  07.09.2026: *"Ich kann das doch jetzt nicht einfach in Auftrag geben, weil
  ich ja gar nicht verstehe: Was heißt das? Wo wurde das gefunden?"* Nur eine
  Maßnahme, die aus einer Lücke in der Datenlage folgt und keinen Befund am
  Shop hat, bleibt ohne.

### Schritt 4: Priorisieren und schreiben

Nachdem alle Befunde aus allen vorliegenden `findings/`-Dateien durch
`create()` gelaufen sind: `measures.save(workspace, backlog)`.

**`prioritize()` wird hier nicht aufgerufen, und sein Rückgabewert wird nie
zugewiesen.** Anders als `create()`, das ein neues Dokument liefert und dessen
Rückgabe zwingend zugewiesen werden muss, nimmt `prioritize(backlog)` das
Dokument und gibt eine **Liste** zurück, die Sortierung für die Ausgabe. Wer
`backlog = measures.prioritize(backlog)` schreibt und das speichert, legt eine
Liste in `measures.json` ab; `load()` liefert danach eine Liste, und der nächste
Lauf fällt an ganz anderer Stelle um. Am 06.09.2026 im ersten echten Lauf genau
so passiert. `save()` weist den falschen Typ inzwischen ab, die Reihenfolge oben
bleibt trotzdem die richtige. Sortiert wird erst beim Rendern in Phase 4, und
`render()` ruft `prioritize()` selbst auf.

**Vorher zählen, danach nachzählen.** Wie viele Befunde in den
`findings/`-Dateien standen und wie viele Einträge `backlog["measures"]` danach
trägt. Beide Zahlen gehören in die Zusammenfassung am Ende des Laufs. Stehen
Befunde da und der Backlog ist leer oder deutlich kürzer, brich ab und sag
warum, statt zu schreiben: ein leerer `measures.md` sieht aus wie "nichts
gefunden" und ist nicht von einem echten Ergebnis zu unterscheiden. Der
häufigste Grund dafür ist ein `create()`-Aufruf, dessen Rückgabewert nicht
zugewiesen wurde (siehe Schritt 3), und der wirft keine Ausnahme. `prioritize()` stellt Befunde der
Disziplin `data_quality` unabhängig von ihrer eigenen Einordnung nach
Sicherheit, Hebel und Aufwand an die Spitze (Spec Abschnitt 9); das
übernimmt das Modul selbst, diese Skill ruft nur auf. Das Rendern zu
`measures.md` (`measures.render()`) geschieht erst in Phase 4, dieselbe
Trennung wie bei der Baseline: diese Phase schreibt Zustand, Phase 4 leitet
das lesbare Dokument daraus ab.

**Artefakte:** `reporting/baseline/01/baseline.json` (neu oder um Blöcke
ergänzt) und `reporting/measures.json`.

**Bei Fehler:** ein einzelner `create()`-Aufruf, der mangels Beleg, ohne
`check_rule` oder mit unbekanntem Wert scheitert (`ValueError` oder die
`check_rule`-Pflicht oben), lässt den betroffenen Befund weg und
protokolliert das, bricht aber nicht die übrigen Befunde oder Blöcke ab. Ein
bereits geschriebener Block wird nie erneut geschrieben
(`BlockAlreadyWritten` wird nie abgefangen, das ist ein Denkfehler beim
Aufrufer, keine Fehlerbehandlung).

**Bei Erfolg:** `run_state.set_phase('3-synthesis', 'done')`, `run_state.save()`.

## Phase 4: Deliverables

**Ist `workos:report` installiert, lädt der Lauf sie vor dem ersten Satz an
einem Kundendokument, für Tonfall und Prüfungen.** Sie hält die vier Textarten
im Report, die vier Label-Fragen für Überschriften, Spaltenköpfe und
Statuswerte, die vier Sätze des Einstiegs und die Abgrenzung, was aus der
Stimme im Fachdokument gilt. Das betrifft `baseline.md` und `measures.md`
genauso wie das Kunden-PDF. Wo sie dieser Skill widerspricht, gilt diese Skill;
beim Einstieg kommt das vor. Ein Befund-Titel ist in jedem Fall ein Label, keine
freie Formulierung.

**Schritt 1, die Markdown-Ableitungen.** `baseline.render(workspace)`
schreibt `baseline.md` aus `baseline.json`, `measures.render(workspace)`
schreibt `measures.md` aus `measures.json`. Beide sind reine Ableitungen, nie
von Hand gepflegt.

**Schritt 2, das Kunden-PDF.** Es folgt einem Skelett aus acht Elementen in
fester Reihenfolge, das `skills/audit/templates/audit.html` und
`scripts/audit/report_build.py` festhalten. Bis zum 07.09.2026 hatte das
Template davon zwei, und der Report sprang von der Überschrift direkt in die
erste Tabelle.

**Das Dokument baut `scripts/audit/report_build.py`, nicht die Sitzung.** Bis
zum 07.09.2026 stand hier in Prosa, welcher Platzhalter aus welchem Quellfeld
kommt, und jede Sitzung setzte das Dokument von Hand zusammen. Das Ergebnis war
jedes Mal ein anderes, und jeder Fix an der Darstellung lebte nur in der
Sitzung, die ihn gemacht hat. Die Trennung ist jetzt fest:

| Was | Wer | Warum |
|---|---|---|
| Zahlen je Sektion, Befunde, Maßnahmen, Quellen, Kennzahlenleiste | das Script | Zahlen gehören in Code, damit sie nicht driften |
| neun Textelemente in `report-text.json` | die Sitzung | Text gehört an einen Menschen, damit er nicht generisch wird |
| Überschriften, Labels, Erklärzeilen | das Template | eine Zeile, die jeder Lauf neu schreibt, driftet |

| # | Element | Steckt im Template als | Gefüllt aus |
|---|---|---|---|
| 1 | Kopf | `__COVER_HEADLINE__` plus feste Dokumentzeile | Sitzung, Pitch-Gate |
| 2 | Einstieg | `__INTRO__` | Sitzung, vier Sätze, siehe unten |
| 3 | Die größten Probleme | `__PROBLEMS__` | Sitzung, zwei bis vier Kacheln |
| 3b | Kennzahlenleiste | sechs `__KPI_*__` plus Notizen | Script |
| 3c | Path to AI E-Com Score | `__SCORES__` | Script |
| 4 | Zusammenfassung | fünf `__SUMMARY_*__` | Sitzung |
| 4b | Die wichtigsten Erkenntnisse | `__TAKEAWAYS__` | Sitzung, fünf Sätze mit Befund-Kennung |
| 4c | Die Befunde im Überblick | `__FINDINGS_OVERVIEW__` | Script |
| 5 | Inhalt | fest im Template | nichts, die vierzehn Zeilen stehen |
| 6 | Fachsektionen | dreizehn `SECTION:`-Marker | Script, siehe Tabelle darunter |
| 7 | Nächster Schritt | `__NEXT_STEP__` | Sitzung |
| 8 | Quellen | `SECTION:sources` | Script, aus `state.json > sources` |

**Alle Überschriften, alle Labels und alle Erklärzeilen stehen fest im
Template.** Sie gelten für jeden Shop und werden nie je Lauf neu formuliert.
Eine Zeile, die jeder Lauf selbst schreibt, driftet, und sie durchläuft dabei
jedes Mal die vier Label-Fragen aufs Neue. Der Lauf füllt Zahlen, Namen und
Sektionsinhalte, sonst nichts.

### Die elf Fachsektionen

Seit dem 07.09.2026 trägt jede Sektion ihre eigenen Zahlen und direkt darunter
die Befunde, die aus ihnen folgen. Davor standen alle Zahlen in einer einzigen
Baseline-Tabelle und alle Befunde als ein Block dahinter; der Leser musste
zwischen beiden blättern, und die Baseline war eine Zeile je Bereich
("SEO Suche · Klicks · 120.000"). Yves dazu: *"Was soll das heißen?"*

| Marker | Inhalt | Quelle |
|---|---|---|
| `SECTION:shop` | Tabelle Angabe / Wert / Quelle: Shop-System, Theme, Sprachen, Märkte, Zahlarten, Sortiment, Seiten im Shop, Zahlen ab, Skripte fremder Anbieter. **Die Spalte Quelle trägt Werkzeugnamen** (Shopify Admin, Search Console, eigener Durchgang), nie Dateinamen | `config.json`, `shop-tech.json`, `catalog.json`, `crawl.json`, `state.json` |
| `SECTION:measurement` | Die Zahlen zur Messqualität, dann die Befunde der Disziplin. Steht vorn, weil eine kaputte Messung jede Zahl danach zur Behauptung macht | `findings/data-quality.json`, `shopify.json`, `ga4.json`, `shop-tech.json` |
| `SECTION:commerce` | Umsatz, Bestellungen, Bestellwert, Saison und Verfügbarkeit, dann die Befunde | `findings/commerce.json`, `shopify.json`, `catalog.json` |
| `SECTION:traffic` | Kanaltabelle mit Sessions, Anteil, Bestellungen, Conversion und Umsatz je Kanal, dann die Befunde | `findings/traffic.json`, `ga4.json` |
| `SECTION:conversion` | Kaufweg je Stufe als Anteil aller Sitzungen, dazu die Geräte, dann die Befunde | `findings/conversion.json`, `ga4.json`, `screens.json` |
| `SECTION:trust` | Welche Pflichtseiten der Crawl gefunden hat und mit welchem Status, dazu der Vorbehalt, dass dies keine juristische Prüfung ist, dann die Befunde | `findings/trust.json`, `crawl.json` |
| `SECTION:seo` | Klicks und Impressionen, Ranking-Bestand, Sichtbarkeitsverlauf, stärkste Rankings, Chancen knapp vor Seite eins, Lücken zum Wettbewerb, dann die Befunde | `findings/seo-content.json`, `gsc.json`, `dfs-rankings.json`, `dfs-competitors.json`, `dfs-backlinks.json` |
| `SECTION:geo` | Sichtbarkeit je Plattform und Abfragegruppe, wer stattdessen zitiert wird, Crawler-Zugang, dann die Befunde | `findings/geo.json`, `geo.json` |
| `SECTION:tech` | Ladezeit je Seitentyp aus Feld und Labor, der eigene Durchgang durch den Shop, dann die Befunde | `findings/seo-technical.json`, `cwv.json`, `crawl.json` |
| `SECTION:catalogue` | Produkte, Varianten, Kategorien, gepflegte Felder, Bilder, dann die Befunde | `findings/content-brand.json`, `catalog.json` |
| `SECTION:competition` | Sichtbarkeit im Vergleich, Autorität, Linkprofil, Shopping-Präsenz, dann die Befunde | `findings/competition.json`, `dfs-rankings.json`, `dfs-backlinks.json`, `dfs-competitors.json`, `dfs-shopping.json` |
| `SECTION:sea` | Shopping-Präsenz und was das Werbekonto zeigt, dann die Befunde | `findings/sea.json`, `ads.json`, `dfs-shopping.json` |
| `SECTION:measures` | Die Reihenfolge der Umsetzung als Tabelle, eine Zeile je Maßnahme, mit dem Abschnitt, in dem sie ausführlich steht. Darunter nur die Maßnahmen ohne Befund am Shop | `measures.json` |
| `SECTION:gaps` | Tabelle Quelle / Status / Grund / Was dadurch offen bleibt | `source-status.md` plus die `blocked_questions` aller Disziplinen |
| `SECTION:method` | Wie der PTAI E-Com Score gerechnet wird: Strafpunkte, Gewichte, Grenzen, und was der Score nicht leistet. **Aus den Konstanten von `score.py` erzeugt, nicht getippt** | `scripts/audit/score.py` |
| `SECTION:sources` | Je Quelle eine `.source-row`: Werkzeug, Umfang, Stand | `state.json > sources`, Erhebungsdatum aus `pulled_at` |

**Jede Fachsektion beginnt mit ihren Zahlen, dann kommen die Befunde.** Die
Zahlen-Tabelle hat immer drei Spalten: Kennzahl, Wert, Bezug. Der Bezug ist
nicht optional. "Klicks 120.000" ist keine Aussage; "Klicks aus der
Google-Suche · 120.000 · in 16 Monaten, bei 4,8 Mio. Impressionen" ist eine.

**Jede Maßnahme steht bei ihrem Befund, nicht in einem eigenen Kapitel.**
Bis zum 07.09.2026 stand beides: der Befund sagte "Was zu tun ist", und
25 Seiten später stand dieselbe Handlung noch einmal als Block. Yves dazu:
*"Sind da dann nochmal weitere Maßnahmen?"* Nein, es waren dieselben.

Daraus folgen drei Regeln:

- **Der Maßnahmen-Block steht direkt unter dem Befund**, aus dem er folgt, in
  der Sektion dieses Befunds. Er braucht dort keine Zeile "Woraus": der Befund
  steht zwei Zentimeter darüber.
- **Trägt ein Befund eine Maßnahme, entfällt sein `fix`-Satz.** Die Maßnahme
  sagt dasselbe vollständiger, mit Zuständigkeit und Prüfregel. Ohne Maßnahme
  behält der Befund seinen Satz.
- **Abschnitt 12 ist der Plan, nicht die Wiederholung.** Eine Tabelle in der
  Reihenfolge aus `measures.prioritize()`, je Zeile Nummer, Maßnahme, Hebel,
  Aufwand und der Abschnitt, in dem sie ausführlich steht. Als Block stehen
  dort nur die Maßnahmen ohne Befund am Shop: die folgen aus einer Lücke in der
  Datenlage und haben sonst keinen Ort.

**Eine Maßnahme ist ein Block, keine Tabellenzeile.** `measures.json` trägt je
Eintrag `evidence`, `data_source`, `check_rule` und `responsible`; bis zum
07.09.2026 zeigte der Report keines dieser Felder, und der Leser konnte die
Maßnahme nicht beauftragen. Yves: *"Ich kann das doch jetzt nicht einfach in
Auftrag geben, weil ich ja gar nicht verstehe: Was heißt das? Wo wurde das
gefunden?"* Jeder Block nennt deshalb den Befund, aus dem er folgt, was er
bringt, wo gearbeitet wird, wer zuständig ist und woran ein Folgelauf die
Erledigung erkennt.

**Die Kernzahl je Baseline-Block ist festgelegt, nicht gewählt.** Sonst sucht
jeder Lauf sie neu aus, und die Übersichtstabelle vergleicht über zwei Läufe
hinweg verschiedene Zahlen:

| Block | Kernzahl | Quellfeld im Block |
|---|---|---|
| Handel | Umsatz über den erhobenen Zeitraum | `commerce` > Umsatz brutto |
| Traffic | Sessions über den erhobenen Zeitraum | `traffic` > Sessions |
| Conversion | Conversion Rate gesamt | `conversion` > Conversion Rate |
| SEO Suche | Klicks über den erhobenen Zeitraum | `seo_search` > Klicks |
| SEO Sichtbarkeit | Ranking-Keywords gesamt | `seo_visibility` > Ranking-Keywords |
| GEO | Marke genannt bei Kategorie-Abfragen, als "x von y" | `geo` > Trefferquote Kategorie |
| SEA | Ausgaben über den erhobenen Zeitraum | `sea` > Ausgaben |
| Technik | LCP der Produktseite, Feldwert | `tech` > LCP Produktseite |
| Katalog | Anteil Bilder mit Alt-Text | `catalogue` > Anteil Bilder mit Alt-Text |
| Messung | Zuordnungslücke gegen GA4 | `measurement` > Zuordnungslücke |

Ein leerer Block bekommt in der Wert-Spalte "nicht erhoben" und in der
Stand-Spalte den Grund aus `state.json`, nie eine leere Zelle und nie eine
Null. Die Zelle der Zuordnungslücke bekommt `class="neg"`, wenn sie über der
Schwelle aus `reference/metrics.md` liegt: sie ist dann der eine Wert, der
eine Maßnahme auslöst.

### Die Kennzahlenleiste

Sechs Kacheln, drei mal zwei, gebaut von `report_build.key_figures()`. Bis zum
07.09.2026 waren es acht in einer Viererreihe, darunter Suchklicks und zwei
Katalogzahlen.

**Die Auswahl folgt der Umsatzgleichung, nicht dem, was gerade greifbar ist.**
Shopify formuliert sie als Sitzungen mal Conversion Rate mal Bestellwert mal
Kauffrequenz. Umsatz ist das Ergebnis, die vier Faktoren sind die Hebel, und
die Frage eines Geschäftsführers lautet: welcher Faktor hat sich bewegt.

| Platzhalter | Wert | Warum diese Kachel |
|---|---|---|
| `__KPI_REVENUE__` | Umsatz im Auswertungsfenster | die Zielgröße |
| `__KPI_ORDERS__` | Bestellungen | das Zwischenglied der Gleichung |
| `__KPI_AOV__` | Ø Bestellwert | Hebel 3 |
| `__KPI_CR__` | Conversion Rate | Hebel 2 |
| `__KPI_SESSIONS__` | Sitzungen | Hebel 1 |
| `__KPI_SIXTH__` | Wiederkaufrate, sonst Retourenquote oder Rohertrag | Hebel 4, plus die Marge |

Dazu trägt jede Kachel ihre Veränderung: `__KPI_REVENUE_NOTE__`,
`__KPI_ORDERS_NOTE__`, `__KPI_AOV_NOTE__`, `__KPI_CR_NOTE__`,
`__KPI_SESSIONS_NOTE__` und `__KPI_SIXTH_NOTE__`. `__KPI_SIXTH_LABEL__` trägt
den Namen der sechsten Kennzahl, weil er von der Datenlage abhängt, und
`__KPI_SIXTH_CLASS__` setzt sie kleiner, wenn sie "nicht erhoben" sagt: eine
fehlende Kennzahl wird gezeigt, aber nicht geschrien.

**Was hier nicht mehr steht, und warum.** Suchklicks sind ein Kanal-Input eine
Ebene unter den Sitzungen und stehen im SEO-Kapitel. Zahl der Produkte und
Anteil der kaufbaren sind Bestandsfakten, kein Ergebnis, und die zweite ist
zusätzlich eine Aussage über die Datenqualität. Beide standen dort, weil
`pull-shopify` sie ohne Zusatzzugang liefert, und das ist der falsche Grund
für eine Kachel auf dem Deckblatt.

**Der Zeitraum steht einmal über der Leiste** (`__KPI_PERIOD__`), nicht in
jeder Bildunterschrift. Sechs Mal derselbe Satz unter sechs Zahlen ist Lärm.

**Jede Zahl trägt ihren Vergleich, und das ist keine Kür.** Stephen Few,
"Common Pitfalls in Dashboard Design": *"To state that quarter-to-date sales
total $736,502 without any context means little. Compared to what? Is this
good or bad?"* Der Vergleichswert ist das Vorjahresfenster, nie ein
Branchen-Benchmark: für die meisten Sortimente gibt es keine belastbare
öffentliche Zahl, und eine gescrapte macht den Report angreifbar.

**Die sechste Kachel wird nie durch eine greifbare Zahl ersetzt.** Liefert
keine Quelle Wiederkaufrate, Retourenquote oder Rohertrag, sagt die Kachel
"nicht erhoben" plus den Grund in Kundensprache. Eine fehlende Kennzahl mit
Begründung ist ein Befund, eine ersatzweise eingesetzte ist ein Fehler.

**Störmonate werden ausgewiesen, nicht geglättet.** Ein Monat mit auffällig
erhöhten Sitzungen oder ohne gemessene Käufe verzerrt jeden Vergleich, der ihn
mitnimmt. `window.build()` erkennt sie, rechnet Sitzungen, Bestellungen und
Conversion zusätzlich über die identischen verbleibenden Monate beider Jahre,
und die Kachel sagt in ihrer Notiz, dass sie das getan hat.

**Das Auswertungsfenster ist nicht die Baseline.** Die Baseline friert die
volle Historie ein, sie ist der Nullpunkt. Das Fenster sind die letzten zwölf
vollen Monate gegen die zwölf davor, und es beantwortet eine andere Frage:
wohin bewegt der Shop sich gerade. `scripts/audit/window.py` rechnet es aus
den Snapshots, nie die Sitzung.

### Wie eine Kennzahl heißt

Deutsch für Handelsgrößen, englisch für die eingeführten Akronyme. Das ist
nicht Geschmack, sondern die Schreibweise, die Shopify, GA4 und die Search
Console auf Deutsch selbst benutzen: der Kunde sieht dieses Wort in seinem
Werkzeug.

| Im Report | Nicht |
|---|---|
| Sitzungen | Sessions, Visits |
| Conversion Rate | Konversionsrate, Umwandlungsrate |
| Ø Bestellwert, einmal ausgeschrieben mit "(AOV)" | Warenkorbwert |
| Bestellungen | Transaktionen, Orders |
| Umsatz, bei Bedarf Nettoumsatz | Revenue |
| Wiederkaufrate | Repeat Rate |
| Retourenquote | Return Rate |
| Warenkorbabbruchrate | Cart Abandonment Rate |
| Impressionen, Klickrate | Impressions, CTR (im Fließtext einmal erklärt) |
| Organische Suche, Bezahlte Suche, Verweis | Organic, Paid, Referral |
| Absprungrate, Interaktionsrate | Bounce Rate, Engagement Rate |
| CAC, CLV, ROAS, ROI | eingedeutschte Formen |

**Für Klicks aus der Search Console gibt es keinen deutschen Fachbegriff.**
Google nennt sie im deutschen Leistungsbericht schlicht "Klicks". Im
SEO-Kapitel heißt es bei der ersten Nennung "Klicks in der organischen Suche",
danach nur "Klicks". Auf das Deckblatt gehören sie nicht.

**Die Stufen des Kaufwegs tragen die offiziellen GA4-Namen**, mit einer
Ausnahme: `add_to_cart` heißt dort "In den Einkaufswagen legen", und das ist
eine Übersetzung, kein Handelsbegriff. Im Report steht "In den Warenkorb
gelegt", passend zu Warenkorbabbruchrate und durchschnittlichem Warenkorb.

### Der Kaufweg ist kein Trichter

**GA4 zählt je Stufe die Sitzungen, in denen das Ereignis mindestens einmal
vorkam, unabhängig von der Reihenfolge.** Eine Sitzung kann den Warenkorb
ansehen, ohne in derselben Sitzung etwas hineingelegt zu haben: mit einem
gespeicherten Warenkorb vom letzten Besuch, über einen Newsletter-Link direkt
auf `/cart`, oder durch einen Klick auf das Warenkorb-Symbol.

**Deshalb gibt es keine Spalte "Weiter von der Stufe davor".** Sie stand bis
zum 07.09.2026 im Report und behauptete einen Weg, den die Zahlen nicht
beschreiben. Für den Warenkorb meldete sie 237,6 Prozent, also mehr Sitzungen
in einer Stufe als in der davor. Yves dazu: *"Ok, dann verstehe ich die
Darstellung nicht."*

Jede Stufe trägt stattdessen ihren **Anteil an allen Sitzungen**, und unter der
Tabelle steht ein Satz, warum eine spätere Zeile größer sein kann als eine
frühere. Genau die Zahl, die den Leser stutzen lässt, muss erklärt werden, wo
sie steht.

**Eine Übergangsquote ist erlaubt, wo die Stufen zwingend aufeinander folgen.**
Produkt ansehen und in den Warenkorb legen ist so ein Paar: ohne Produktansicht
kein Warenkorb. Sie wird als eigener Satz ausgewiesen, nicht als Spalte, damit
klar bleibt, dass sie eine Ausnahme ist.

### Die größten Probleme, als Zahl

`__PROBLEMS__` sind zwei bis vier Kacheln, in denen **die Zahl selbst das
Problem ist**. Die Bauform kommt aus einem eigenen Report, der funktioniert
hat: "3 Versandkostenschwellen, gleichzeitig", "0
Länder, bei denen die Preise übereinstimmen". Wer nur diese Zeile liest, weiß,
worum es geht.

Je Kachel vier Felder in `report-text.json` unter `problems`:

| Feld | Inhalt |
|---|---|
| `value` | die Zahl, groß und allein lesbar |
| `label` | was sie zählt, zwei bis vier Wörter |
| `detail` | eine Zeile, die sagt, was daran das Problem ist |
| `finding_ref` | die Kennung des Befunds dahinter |

**Welche Probleme das sind, entscheidet die Sitzung, nicht das Script.** Welche
drei von 91 Befunden tragen, folgt nicht aus den Daten. Das Script prüft nur,
dass jede Kachel auf einen Befund zeigt, den es wirklich gibt, und bricht sonst
ab: eine Zahl auf Seite eins ohne Herkunft kann der Leser nicht nachschlagen.

**Der Unterschied zur Kennzahlenleiste ist der Blickwinkel.** Die Kennzahlen
sagen, wie der Shop dasteht. Die Problem-Kacheln sagen, was ihn das kostet.
Beide stehen auf Seite eins, und keine ersetzt die andere.

**Die Problem-Kacheln stehen zuerst, direkt unter dem Einstieg.** Der Leser
fragt "was ist los", bevor er fragt "wie steht der Shop da". Bis zum
07.09.2026 standen sie hinter der Zusammenfassung, also hinter fünf Absätzen
Erklärung, und damit an der Stelle, an der ein Leser sie nicht mehr sucht.

**Jede Zahl trägt ihre Bezugsgröße im `value`, nicht erst in der Erklärzeile.**
"1.000" allein ist nicht bewertbar, "1.000 von 3.000" ist es sofort. Das
Nutzertesting der Cochrane-Ergebnistabellen fand die fehlende Bezugsklasse als
häufigste Fehlerquelle überhaupt (Rosenbaum et al., Journal of Clinical
Epidemiology 2010). Ausnahme ist die Zahl, deren richtiger Wert selbstverständlich
ist: "0 Länder, bei denen die Preise übereinstimmen" braucht keinen Nenner,
weil jeder Leser weiß, dass dort "alle" stehen müsste.

### Der Path to AI E-Com Score

`__SCORES__` baut `scripts/audit/score.py`: eine Gesamtbewertung, vier
Bereichswerte mit Zielmarke, und je Fachsektion ein eigener Wert in ihrem Kopf.

**Der Score hat einen Namen, und zwar unseren.** Er heißt im Dokument
"Path to AI E-Com Score", nicht "Health Score" und nicht "Gesamtbewertung". Ein
Score ohne Absender ist eine Behauptung; einer mit Absender ist eine Methode,
die jemand verantwortet und die beim nächsten Lauf wiederkommt.

**Die Rechenweise ist bewusst dieselbe wie in `scripts/report/sales/score.mjs`**,
der Engine des audit-light. Zwei Engines für dieselbe Frage wären zwei
Antworten, und beim ersten Widerspruch glaubt niemand mehr einer von beiden.
100 minus Strafpunkte je Befund, gewichtet nach Schweregrad (hoch 14, mittel 5,
gering 1) und Sicherheit (belegt 1,0, plausibel 0,7, Verdacht 0,4), mit
abnehmendem Ertrag.

| Bereich | Gewicht | Sektionen |
|---|---|---|
| Kaufen | 0,40 | Conversion, Katalog, Handel |
| Gefunden werden | 0,30 | SEO, GEO, Wettbewerb, Bezahlte Suche, Traffic |
| Technik | 0,15 | Technik und Ladezeit |
| Messung | 0,15 | Messung |

Abschnitt 1 speist keinen Score: Shop und Technik ist eine Bestandsaufnahme,
keine Bewertung.

**Deckel bei 92, Boden bei 35.** 100 würde behaupten, es gäbe nichts mehr zu
finden, und ein Audit prüft nur, was er prüfen kann. Der Boden verhindert, dass
eine gründlich geprüfte Sektion allein durch die Menge ihrer Befunde gegen null
läuft.

**Eine Sektion ohne Datengrundlage bekommt keinen Score, sondern "nicht
bewertbar".** Sonst sieht ein Bereich, den niemand prüfen konnte, aus wie einer
ohne Probleme. Ihr Gewicht verteilt sich auf die übrigen.

**Das Ziel ist der Stand nach Umsetzung, wortwörtlich, und es liegt deshalb
oft nahe am Deckel.** Bis zum 07.09.2026 war der Sprung auf 24 Punkte begrenzt,
mit der Begründung, ein überall gleiches Ziel sage nichts. Das war der falsche
Schluss aus einer richtigen Beobachtung: **die Aussage steckt nicht in der Höhe
des Ziels, sondern im Abstand.** Messung 38 auf 89 ist ein Sprung von 51
Punkten, Bezahlte Suche 86 auf 92 einer von sechs, und genau das soll der Leser
sehen. Yves dazu: *"Wieso nur 53? Warum kann man nicht 100 schaffen?"*

Was das Ziel unter dem Deckel hält, sind die Befunde **ohne** Maßnahme:
Beobachtungen, Lücken in der Datenlage, Dinge außerhalb des eigenen Zugriffs.
Die verschwinden nicht dadurch, dass jemand arbeitet.

**Die Rechnung steht im Report, nicht nur im Code.** Abschnitt 14 legt sie
vollständig offen: Strafpunkte je Schweregrad, Faktor je Sicherheit,
Bereichsgewichte, Deckel, Boden, abnehmender Ertrag und wie das Ziel entsteht.
**Der Abschnitt wird aus den Konstanten in `score.py` erzeugt, nicht daneben
geschrieben:** eine von Hand getippte Methodenbeschreibung veraltet mit der
ersten Änderung an einem Gewicht, und niemand merkt es, weil das Dokument
weiter rendert.

**Dort steht auch die Grenze der Methode, ausdrücklich.** Die Gewichte sind
eine Kalibrierung, keine Messung: so gewählt, dass ein schwerer Befund spürbar
mehr wiegt als ein leichter und gründliches Prüfen den Wert nicht ruiniert.
Sie stammen aus keiner Studie. Was die Methode garantiert, ist etwas anderes
und für den Zweck entscheidend: dieselben Befunde ergeben immer denselben Wert,
und zwei Läufe desselben Shops sind vergleichbar. Wer das verschweigt, verkauft
eine Zahl als mehr, als sie ist, und beim ersten Nachfragen bricht sie
zusammen.

**Wogegen der Score vergleicht, und wogegen nicht.** Es gibt keinen belastbaren
öffentlichen Benchmark für einen Shop dieser Größe und dieses Sortiments. Die
kursierenden Branchenzahlen stammen aus Aggregator-Blogs; Shopify selbst zitiert
für Schmuck eine einzige Quelle über gut 400 Marken. Das ist zu dünn für ein
Kundendokument, und eine gescrapte Zahl macht den Report angreifbar. Verglichen
wird deshalb gegen drei Dinge, die alle im Dokument selbst stehen: gegen 100,
also einen Shop ohne Befunde, gegen das Ziel nach Umsetzung, und **ab dem
nächsten Lauf gegen den heutigen Wert.** Genau dafür existiert die Baseline.

**Nie einen Branchen-Benchmark danebenstellen**, auch nicht als Orientierung.
Sobald eine Zahl im Dokument steht, wird sie zum Maßstab, und dieser Maßstab
wäre nicht belegt.

### Die wichtigsten Erkenntnisse und der Zustand je Bereich

`__TAKEAWAYS__` sind fünf Sätze, die den ganzen Report tragen. **Jeder nennt
eine gemessene Zahl und die Kennung des Befunds dahinter**, damit der Leser von
der Erkenntnis zur Herleitung springen kann. Als `<ol>` mit fünf `<li>`. Die
Sitzung schreibt sie, nicht das Script: welche fünf von 92 Befunden tragen,
folgt nicht aus den Daten.

`__FINDINGS_OVERVIEW__` baut das Script: je Bereich die Zahl der Befunde, wie
viele davon schwer wiegen und in welchem Abschnitt sie stehen, darunter die
schwerwiegenden einzeln mit Kennung. **Das ist Navigation, keine Bewertung.**
Ein Audit misst, es benotet nicht, und eine Punktzahl je Bereich wäre die
einzige Zahl im Dokument ohne Beleg.

Bis zum 07.09.2026 stand hier "Der Zustand je Bereich": eine Kernzahl je
Bereich, ohne Zeitraum, mit Einordnungen wie "bereinigt gegen das Vorjahr".
Yves dazu: *"Die Zahlen bringen mir eigentlich nichts, weil ich nicht
verstehe, was die aussagen."* Die Zahlen stehen jetzt in der Kennzahlenleiste
und in den Fachsektionen, wo ihr Zeitraum danebensteht.

**Der Schweregrad hat drei Stufen, und sie sind definiert.** Die Zahl der
Stufen schreibt kein Standard vor, die Definition und die durchgängige
Anwendung schon (IIA Global Internal Audit Standards 14.3: *"When ratings are
used, rating criteria should be clearly defined and consistently applied"*).
Drei ist die Form, in der die Nielsen Norman Group berichtet, sobald berichtet
statt geforscht wird.

| Stufe | Wann |
|---|---|
| hoch | kostet heute Geld oder macht andere Zahlen im Report unbrauchbar |
| mittel | messbarer Verlust an Sichtbarkeit, Conversion oder Datenqualität, aber nicht akut |
| gering | Hygiene, heute ohne messbaren Verlust |

**Schweregrad ist nicht Priorität.** Der Schweregrad sagt, wie schwer der
Befund wiegt; die Reihenfolge der Umsetzung entsteht zusätzlich aus dem
Aufwand, und deshalb stehen Hebel und Aufwand getrennt am Maßnahmenblock
(CVSS v4.0 User Guide: Base Scores messen Schwere und taugen allein nicht zur
Risikobewertung).

Fehlt `severity` im Befund, leitet `report_build.severity_rank()` ihn aus dem
Hebel der Maßnahmen ab, die auf ihn verweisen, und sonst aus der Sicherheit
der Analyse. Ein bloßer Verdacht wird dabei nie "hoch".

### Die fünf Zeilen der Zusammenfassung

Die Labels stehen fest im Template, gefüllt werden nur die Werte. Je ein bis
zwei Sätze:

| Platzhalter | Was hineingehört |
|---|---|
| `__SUMMARY_WHAT__` | Gegenstand und Grundgesamtheit: welcher Shop, welcher Stichtag, welche Bereiche, je über den längsten Zeitraum der Quelle |
| `__SUMMARY_WHY__` | der Mechanismus, der den Nullpunkt nötig macht, nicht der Ablauf des Audits |
| `__SUMMARY_STATUS__` | die drei bis vier tragenden Zahlen aus der Kennzahlenleiste, als Satz |
| `__SUMMARY_PROBLEM__` | was aus dem stärksten Befund folgt, in der Sprache des Lesers |
| `__SUMMARY_POSSIBLE__` | der Weg raus, ohne Preis und ohne Ablauf |

### Ein Wort je Sache, im ganzen Dokument

Am 07.09.2026 standen für denselben Gegenstand drei Wörter im selben PDF:
Baseline in der Überschrift, Nullpunkt in der Erklärzeile, Ausgangswert in der
Zusammenfassung. Wer ein Vokabular einführt, benutzt es weiter; sonst sucht
der Leser den Unterschied, den es nicht gibt.

| Gegenstand | Das Wort | Nicht |
|---|---|---|
| die eingefrorenen Zahlen | Baseline | Nullpunkt, Ausgangswerte, Startwerte |
| der nächste Lauf | der spätere Report, der nächste Report | Folgereport |
| die Beziehung dazu | daran messen, damit vergleichen | dagegen vergleichen |
| Abschnitt 1 | Shop und Technik | Marke und Shop |
| Abschnitt 5 | Lücken in der Datenlage | Was nicht gemessen werden konnte |
| die Kennzahl je Bestellung | Ø Bestellwert, im Fließtext einmal "durchschnittlicher Bestellwert (AOV)" | Warenkorbwert |
| die erfassten Seiten | Seiten im Shop, geöffnet und geprüft | gecrawlte Seiten |
| fremde Skripte | Skripte fremder Anbieter | Fremdtechnik |

`baseline.json` und `baseline.md` heißen weiter so. Das ist der technische
Name der Datei, kein Wort im Kundendokument.

### Der Report beantwortet Fragen zum Shop, nicht zum Werkzeug

**Der Leser hat Fragen zu seinem Shop. Fragen zur Messung hat er nicht, bis
wir sie ihm stellen.** Wie weit eine Schnittstelle zurückreicht, wie ein Wert
berechnet wird, warum er nicht abgeleitet wurde, wie die Dateien eines Laufs
heißen: nichts davon ist der Gegenstand. Jeder Satz darüber nimmt einem Satz
über den Shop den Platz weg und lässt den Leser mit einer Frage zurück, die er
vorher nicht hatte.

Beanstandet am 07.09.2026 an zwei Stellen desselben Entwurfs. Ein heller
Kasten erklärte die Datenreichweite der Search Console, obwohl die Tabelle
darüber das Startdatum schon trug. Yves: *"Der erklärt es ja nicht mal
richtig, und die Frage hat auch noch nie jemand gestellt."* Und auf der
Kennzahl-Kachel stand *"von Shopify berechnet, nicht abgeleitet"*, eine
Bauregel des Generators auf der auffälligsten Stelle des Deckblatts.

**Die Prüffrage:** würdest du diesen Satz laut sagen, wenn du dem Kunden den
Report über den Tisch schiebst?

### Gleichartiges wird gleich behandelt

**Stehen mehrere Werte derselben Sorte nebeneinander und du kommentierst
einen davon, hast du über die anderen gesagt, an ihnen sei nichts.** Entweder
bekommt jeder gleichartige Wert seinen Vermerk, oder keiner.

Belegt am 07.09.2026. Die Zeile "Historie ab" führte drei Startdaten aus drei
Quellen, erklärt wurde eine. Yves: *"Mein Shopify ist ja auch da 10/2023, und
Google Analytics ist 03/2024. Wieso hast du denn dazu dann am Ende nichts
geschrieben? Wieso hast du denn nur das jetzt als erwähnenswert genommen?"*

Diese Prüfung sieht nie ein Element allein an, sondern immer den Satz
gleichartiger Elemente. Deshalb findet sie keine der Satz- oder Label-Fragen:
die prüfen je einen Satz und je ein Label. Die Frage lautet: **gibt es im
Dokument einen zweiten Eintrag derselben Sorte, der diesen Vermerk genauso
verdient hätte?**

### Der helle Kasten und die Fußnote

**Der helle Kasten ist die auffälligste Stelle seiner Sektion und wird zuerst
gelesen.** Er trägt deshalb nur eine Einordnung, die für die ganze Sektion
gilt und ändert, was der Leser tut. Höchstens einer je Sektion. Eine
Randbedingung an einer einzelnen Zahl gehört nie hierher.

**Was zu genau einer Zahl gehört, hängt an dieser Zahl.** Drei Wege, in dieser
Reihenfolge zu prüfen:

1. **Ein Zusatz in der Zelle.** Erste Wahl, weil er nichts kostet:
   `Search Console 06/2025 (Google gibt höchstens 16 Monate heraus)`.
2. **Eine Spalte**, wenn mehrere Zeilen einen Grund tragen. Die Lücken-Tabelle
   hat dafür die Spalte "Grund".
3. **Eine Fußnote**, nur wenn beides nicht trägt.

**Eine Fußnote bekommt ein Wert nur dann, wenn der Leser ihn ohne die
Anmerkung in der falschen Größenordnung liest.** Ein Zusatz in der Zelle
erledigt sie. Eine Bedingung, die schon in einer Spalte, in einer
Kachel-Notiz oder in Abschnitt 5 steht, erledigt sie ebenfalls: die Fußnote
wiederholt nie, was das Dokument schon trägt.

Form: hochgestellte Ziffer direkt hinter dem einzelnen Wert
(`<span class="fn">1</span>`), die Auflösung in einem `.table-note` direkt
unter der Tabelle, die Tabelle bekommt `class="has-note"`. Nummerierung je
Tabelle neu ab 1, höchstens drei je Tabelle, und **nur in einer Tabelle, die
auf eine Seite passt**: im Druck gibt es kein Zurückblättern, und über einen
Seitenumbruch hinweg zeigt die Marke auf nichts. Läuft die Tabelle länger,
bekommt sie eine Spalte oder die Zeile wird geteilt.

**Der Fall, der die Mechanik ausgelöst hat, braucht sie nicht.** Die
Datenreichweite der Search Console steht als Zusatz in der Zelle und
ausführlich in Abschnitt 5. Eine Fußnote dort wäre die dritte Erzählung
derselben Sache. Das ist der Maßstab: die Fußnote ist eine Erlaubnis, kein
Auftrag, und der Anlass war *"wir müllen eigentlich zu"*.

### Kopf, Einstieg und Schlussblock

**Die Cover-Headline läuft durch ein Pitch-Gate, falls eins installiert ist.**
Ist `workos:voice` installiert, die Skill aufrufen, Gate durchlaufen, Ergebnis
abwarten, dann erst einsetzen. Sie ist zusammen mit dem Schlussblock eines von
genau zwei Elementen im Dokument, für die das gilt. Mit oder ohne Gate handelt
sie vom Leser und vom Wert, nie vom Mangel:
`IHR HABT ALLES. ES KOMMT NUR NICHT AN.` ist am 04.09.2026 genau daran
gescheitert.

**Der Einstieg beginnt mit dem Ergebnis, nicht mit dem Umfang.** Bis zum
07.09.2026 stand hier eine Reihenfolge, die mit "Was ich angesehen habe"
anfing und mit "Was der Leser danach entscheiden kann" aufhörte. Was dabei
entsteht, sah so aus:

> *"Ich habe Beispielshop einmal vollständig durchgemessen: 2.000 Seiten im
> Shop, 3.000 Produkte und 300 Kategorien ... Nach dem Lesen kannst du
> festlegen, was als Nächstes in den Sprint geht."*

Yves dazu: *"Kompletter Schrott. Da ist einfach nur irgendwas
runtergebetet."* Und zum Schlusssatz: *"Die geben keinen Sinn und müssen doch
mehr Wert bieten. Gerade wenn man sich die Zeit nimmt, etwas zu lesen, sollte
da doch wirklich mehr Wert gestiftet werden."*

**Die Regel dahinter ist belegt.** Die US-Army-Schreibvorschrift AR 25-50,
Ziffer 1-38b: *"Two essential requirements include putting the main point at
the beginning of the correspondence (bottom line up front) and using the
active voice."* Dieselbe Regel bei Minto (die Aussage steht oben, die Belege
darunter), bei der Nielsen Norman Group (Inverted Pyramid) und im GAO Yellow
Book. Ein Einstieg, der mit dem Umfang der Arbeit beginnt, verschiebt die
Aussage hinter den Punkt, an dem die meisten aufhören zu lesen.

**Vier Sätze, in dieser Reihenfolge:**

1. **Was gilt.** Der stärkste Befund des Laufs, als Aussage über den Shop, mit
   seiner Zahl. Nicht der Umfang, nicht das Vorgehen, nicht das Dokument.
2. **Warum das so ist, oder was daran hängt.** Der Mechanismus in einem Satz.
3. **Woraus das folgt.** Jetzt der Umfang, konkret und zählbar, als Beleg für
   Satz 1 und nicht als Selbstzweck.
4. **Was der Leser damit tun kann.** Eine Handlung, die er ohne den Rest des
   Dokuments treffen kann. **Kein Terminversprechen, keine Floskel über den
   Sprint.** Prüffrage: könnte dieser Satz unter jedem beliebigen Report
   stehen? Dann ist er keiner.

Der Betreiber ist das Subjekt (ich-Form), wo er handelt, der Leser wird
geduzt. "Dieser Report zeigt" ist immer falsch. Jede Zahl kommt aus dem Lauf
und wird nie geschätzt: steht die Zahl der Befunde noch nicht fest, wird der
Einstieg zuletzt geschrieben.

**Der Einstieg läuft nicht durch das Pitch-Gate**, aber diese Prüffrage gilt,
ob `workos:report` installiert ist oder nicht: würdest du diesen Satz laut
sagen, wenn du dem Kunden den Report über den Tisch schiebst?

**`__NEXT_STEP__`** ist die eine konkrete Handlung plus der Zeitpunkt, an dem
darüber gesprochen wird. Ein Absatz, keine Liste.

### Drei Regeln, die im Audit anders gelten als im Monats-Report

Sie stehen auch im Template und sind der Grund für ein eigenes Template statt
einer Wiederverwendung von `report.html`:

- **Kein Vergleich, keine Bewegung.** Ein Audit ist Messpunkt eins.
  "Gestiegen", "verbessert", "im Trend" haben in diesem Dokument keinen Beleg.
  Wo eine Reihe vorliegt, beschreibt sie den Verlauf im erhobenen Zeitraum,
  nie eine Wirkung.
- **Ein fehlender Wert wird als fehlend gezeigt**, nie als 0 und nie
  weggelassen. Eine leere Zelle liest sich als Null, und eine Null ist eine
  Messung.
- **Kopf, Einstieg und Schlussblock erklären nie, was fehlt.** Was nicht
  gemessen werden konnte, steht in Abschnitt 5 und nur dort. Am 07.09.2026
  beanstandet: "Dann fängst du auch an, schon in der ersten oberen Headline
  oder in der Beschreibung darunter, zu erklären, was nicht geht." Der Kunde
  hatte die Einschränkung nie im Kopf, bis sie dort stand.

### Ablauf

1. **Ist `workos:report` installiert, die Skill laden**, vor dem ersten Satz.
   Sie hält die vier Textarten und die vier Label-Fragen; wo sie dieser Skill
   widerspricht, gilt diese Skill.
2. **Das Script ohne `--text` aufrufen.** Es schreibt die Textvorlage in den
   Lauf-Ordner und bricht mit Rückgabewert 2 ab:

   ```bash
   python3 -m audit.report_build --workspace . --run-id <run-id> --pdf
   ```

   (aus `${CLAUDE_PLUGIN_ROOT}/scripts` heraus, oder mit
   `PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/scripts`.)

3. **`reporting/runs/<run-id>/report-text.json` füllen.** Das ist die
   vollständige Liste der Schlüssel, die das Script erwartet:

   | Schlüssel | Form | Inhalt |
   |---|---|---|
   | `cover_headline` | Text | die Cover-Zeile, ohne Schlusspunkt |
   | `intro` | HTML | vier Sätze, Ergebnis zuerst, siehe unten |
   | `summary_what` | Text | Gegenstand und Grundgesamtheit |
   | `summary_why` | Text | der Mechanismus, der den Lauf nötig macht |
   | `summary_status` | Text | die tragenden Zahlen als Satz |
   | `summary_problem` | Text | was aus dem stärksten Befund folgt |
   | `summary_possible` | Text | der Weg raus, ohne Preis und ohne Ablauf |
   | `takeaways` | HTML `<ol>` | fünf Sätze, jeder mit Zahl und Befund-Kennung |
   | `next_step` | HTML | der konkrete Ask |
   | `problems` | Liste | zwei bis vier Kacheln, siehe unten |
   | `section_messages` | Objekt | je Fachsektion ein Satz, siehe unten |

   Fehlt eines davon, bricht das Script ab und nennt es. Das ist Absicht: ein
   Dokument mit leerem Einstieg geht nie an einen Kunden.
 Neun Felder, alle
   Pflicht: `cover_headline`, `intro`, die fünf `summary_*`, `takeaways`,
   `next_step`. Die Vorlage trägt zu jedem Feld einen Hinweis, was
   hineingehört, und darunter unter `_zahlen_dieses_laufs` die acht Kennzahlen,
   die Liste aller Befund-Kennungen und die Zahl der Maßnahmen. **Ohne diese
   Zahlen vor Augen entsteht ein Statussatz ohne Beleg**, und genau deshalb
   stehen sie in der Vorlage statt in dieser Skill.

   `cover_headline` und `next_step` laufen vorher durch das Pitch-Gate in
   `workos:voice`, falls installiert, siehe unten. Beide dürfen HTML enthalten,
   `intro`, `takeaways` und `next_step` erwarten es (`<p>`, `<ol><li>`).

4. **Erneut aufrufen, jetzt baut das Script.** Es setzt die Pfade
   (`__CSS_PATH__`, `__LOGO_PATH__`, `__LOGO_REVERSED_PATH__`, immer absolut,
   weil headless Chrome keine Plugin-relativen Pfade auflöst), die drei
   Identitäts-Platzhalter (`__BRAND__` aus `config.json > brand`,
   `__RUN_LABEL__` als lesbarer Stand wie "Stand Oktober 2026", nie die rohe
   Lauf-ID, `__GENERATED_DATE__` als `TT.MM.JJJJ`), die acht Kennzahlen mit
   ihren Notizen, die Zustandstabelle, die dreizehn Sektionen samt Befunden,
   den Maßnahmenteil, entfernt den BAUKASTEN, setzt zuletzt den Schluss
   `__CLOSING__` über `closing.apply` aus `scripts/audit/closing.py` ein und
   schreibt
   `reporting/runs/<run-id>/audit.html`. Bleibt ein Platzhalter oder ein
   `SECTION:`-Marker übrig, bricht es ab und nennt ihn; ein Dokument mit einer
   sichtbaren Marker-Zeile geht nie an einen Kunden.

   **Der Schluss kommt aus den Einstellungen des Betreibers.** Ist
   `PTAI_CLOSING_FILE` gesetzt und lesbar, ersetzt die Schlussseite des
   Betreibers das Schluss-Panel zwischen den Markierungen `CLOSING:start` und
   `CLOSING:end`, dieselbe Seite wie im Monats-Report und in `audit-light`; die
   Markierungen bleiben stehen. Sonst bekommt das Panel den neutralen Schluss:
   eine Kontaktzeile je
   gesetztem und gültigem Wert aus `PTAI_OPERATOR_NAME`,
   `PTAI_OPERATOR_CONTACT`, `PTAI_OPERATOR_EMAIL` und
   `PTAI_OPERATOR_BOOKING_URL`, darunter immer die Herkunftszeile, kein Satz
   dazu; ohne eine einzige gültige Einstellung nur die Herkunftszeile. Fehlt
   die Datei, ist sie nicht lesbar oder leer, steht ein Hinweis auf stderr, und
   der Audit endet neutral. Die Web-Fassung `audit-web.html` endet mit demselben
   Schluss, die Schlussseite dort als Blatt mittig unter dem Inhalt.

   **Die Sitzung baut das HTML nicht selbst.** Was am Aufbau nicht stimmt, wird
   im Script geändert, nicht in der erzeugten Datei: ein Fix an der Kopie ist
   beim nächsten Lauf wieder weg.

5. Rendern, mit dem Renderer aus `report` (ein Script für beide Dokumente,
   damit Chrome-Suche, A4-Einstellung und Größenprüfung nicht in zwei
   Fassungen auseinanderlaufen):

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/skills/report/scripts/render_pdf.sh" \
     "reporting/runs/<run-id>/audit.html" \
     "reporting/runs/<run-id>/audit.pdf"
   ```

6. **Die Web-Fassung bauen**, aus demselben Inhalt:

   ```bash
   python3 -m audit.report_web --workspace . --run-id <run-id>
   ```

   Sie schreibt `reporting/runs/<run-id>/audit-web.html`: eine einzelne Datei
   mit Sprungnavigation, Volltextsuche und einem Filter nach Schweregrad.
   **Zwei Fassungen sind belegte Praxis, keine Bequemlichkeit** (IIA Standard
   15.1: *"Multiple versions of a final communication may be issued, with
   formats, content, and level of detail customized to address specific
   audiences."*). Das PDF ist das Dokument, das man weitergibt; die Web-Fassung
   ist die, in der man arbeitet.

   **Zum Ansehen einen Server starten, nicht doppelklicken:**

   ```bash
   python3 -m http.server 8080 --directory reporting/runs/<run-id>
   ```

   Dann `http://localhost:8080/audit-web.html` öffnen. Die Seite funktioniert
   auch über `file://`, aber nicht in jedem Browser gleich: Safari und einige
   Konfigurationen behandeln lokale Dateien strenger, und dann bleibt die
   Navigation still stehen, ohne dass eine Fehlermeldung erscheint.

   **Die Seite ist deshalb so gebaut, dass sie ohne Skript benutzbar bleibt.**
   Die Abschnittslinks sind gewöhnliche Anker, der Sprung passiert im Browser,
   der Abstand zur Kopfleiste kommt aus `scroll-margin-top`. Das Skript fügt
   nur hinzu, was ohne es fehlt: Markierung des aktuellen Abschnitts, Filter,
   Menü. Jeder dieser Bausteine läuft in seinem eigenen `try`, damit ein Fehler
   nicht die übrigen mitnimmt.

   **Der Inhalt kommt aus `report_build.content()`, nie aus einem zweiten
   Builder.** Zwei Builder wären zwei Wahrheiten, und die erste Zahl, die nur
   in einer von beiden korrigiert wird, fällt niemandem auf. Die Datei lädt
   nichts von außen: kein CDN, kein Skript, keine Schrift. Sie muss auch dann
   funktionieren, wenn sie in einem Jahr aus einem Ordner heraus geöffnet wird.

7. Das PDF sichtprüfen: Archivo Black in den Überschriften, Logo oben rechts,
   die acht Kacheln auf Seite eins, Zusammenfassung und Erkenntnisse auf Seite
   zwei, Tabellen sauber, Schlussseite am Ende. **Seitenzahl gegen den Umfang
   halten:** ein Audit dieser Größe liegt bei 40 bis 60 Seiten. Deutlich mehr
   heißt fast immer, dass ein Block ohne Rasterpartner in einem Grid steht.
8. **Jede Zahl, die auf Seite eins landet, gegen die Wirklichkeit prüfen, nicht
   nur gegen das Quellfeld.** Am 07.09.2026 stand "alle gut tausend Seiten tragen
   denselben Titel, das Wort Visa" als eine von drei Problem-Kacheln im
   Dokument. Die Zahl stimmte mit dem Snapshot überein und war trotzdem falsch:
   der Crawler hatte die Zahlungs-Icons im Seitenfuß ausgelesen. Ein einziger
   Abruf hätte es gezeigt:

   ```bash
   curl -s https://<domain>/ | grep -o '<title>[^<]*'
   ```

   Die Regel gilt für jeden Befund, der es in Einstieg, Erkenntnisse,
   Problem-Kacheln oder Schlussblock schafft: **erst nachsehen, dann
   hinschreiben.** Vier bis sechs Zahlen, fünf Minuten. Ein Befund, der sich
   nicht in einer Minute gegenprüfen lässt, gehört nicht auf die erste Seite.

   Meldet der Crawler unter `crawl.json > summary.self_check` etwas, ist das
   der erste Ort, an dem du nachsiehst.

9. **Das Script meldet beim Bauen die Lesbarkeit** des Fließtexts: Wiener
   Sachtextformel, LIX und die mittlere Satzlänge. Das ist ein Regressionstest,
   kein Qualitätsnachweis. Die Formeln messen Wort- und Satzlänge, nicht
   Verständnis, und ein Text lässt sich formelkonform zerhacken, ohne dass ein
   Leser mehr versteht. Läuft ein Wert deutlich aus dem Band, sieh dir die
   Stelle an, statt Sätze mechanisch zu teilen.

10. **Die Abnahme laufen lassen**, jetzt über den ganzen Lauf:

    ```bash
    python3 -m audit.qa --workspace . --run-id <run-id> --phase 4
    ```

    Zusätzlich zu Phase 2 prüft sie die Maßnahmen (zeigt jede auf einen
    Befund, den es gibt, hat jede eine Prüfregel) und das fertige Dokument
    (kein Platzhalter übrig, keine Ersatzumlaute, Lesbarkeit im Band). Danach
    die Liste abarbeiten, die sie für den Menschen ausgibt.

11. Zahlen gegenlesen: jede Kachel, jede abgeleitete Größe, jeden Prozentwert
   gegen sein Quellfeld. Das ist der Schritt, an dem
   am 06.09.2026 zwei falsche Zahlen in einem Entwurf gefunden wurden. Was
   dabei auffällt, wird im Script korrigiert, nicht im HTML.

**Kein Browser auf dem Rechner:** `render_pdf.sh` bricht mit klarer Meldung ab.
Das ist kein Fehlschlag der Phase: `baseline.md` und `measures.md` stehen, das
HTML liegt fertig da, und der Nutzer bekommt den Render-Befehl zum Nachholen.
Die Phase gilt trotzdem als erledigt, mit dem PDF als offenem Punkt.

**Artefakte:** `reporting/baseline/01/baseline.md`, `reporting/measures.md`,
`reporting/runs/<run-id>/audit.html`, `reporting/runs/<run-id>/audit.pdf`,
`reporting/runs/<run-id>/audit-web.html`.

**Bei Erfolg:** `run_state.set_phase('4-deliverables', 'done')`, `run_state.save()`.
Danach dem Nutzer eine Zusammenfassung: welche Baseline-Blöcke stehen, welche
noch leer sind (und mit `--backfill` folgen), wie viele Maßnahmen priorisiert
wurden, wie viele Tests, die im Lauf verbrauchte DataForSEO-Summe aus
`reporting/dfs-ledger.jsonl`, Pfade zu `baseline.md`, `measures.md`, dem PDF
und dem Screenshot-Zielordner im Kundenordner.

## Der Nachtrag-Modus: `--backfill`

Ruft der Nutzer `/ptai-ecom:audit --backfill` auf einem Shop mit
unvollständiger Baseline auf (siehe "Ein Audit läuft genau einmal je Shop"
oben), läuft nicht der volle Fünf-Phasen-Zyklus. Der Nachtrag rührt an
keinem geschriebenen Block, er füllt ausschließlich, was noch fehlt.

**Was passiert:**

1. `baseline.empty_blocks(workspace)` liefert die leeren Blöcke, in der
   Reihenfolge von `baseline.BLOCKS`. Nur sie sind im Spiel.
2. Für jeden leeren Block die Quell-Schlüssel aus der Tabelle in Phase 3,
   Schritt 1 nachschlagen ("Quell-Schlüssel im `state`"). Gezogen wird nur,
   was einer dieser Blöcke tatsächlich braucht, nie die volle Quellenliste
   aus Phase 1: eine Quelle, deren Block längst geschrieben ist, hat hier
   nichts verloren.
3. Eigene Lauf-ID, eigener Zustand: wie jeder Audit-Lauf bekommt der Nachtrag
   `run.run_id(today, "audit")` und ein eigenes `state.json` unter
   `reporting/runs/<run-id>/`. Die ermittelten Quellen laufen nach
   derselben Mechanik wie Phase 1, isoliert je Quelle, ein Schreiber für den
   Zustand (`run_state.set_source()` plus `run_state.save()` nach jedem Ergebnis),
   hier nicht wiederholt.
4. Für jeden Block, dessen Quell-Schlüssel jetzt alle auf `done` stehen
   (`not run_state.source_open(source)` je Schlüssel, dieselbe Prüfung wie in
   Phase 3, Schritt 1), die Werte nach `reference/metrics.md` bilden und
   `baseline.write_block(workspace, block, values, run_id=run_id,
   today=today, sources=sources)` aufrufen, mit `sources` wie in Phase 3,
   Schritt 1 beschrieben. **Beim Nachtrag ist das der Punkt, an dem die
   Trennung zählt:** `today` ist der Nachtragstag, `pulled_at` der Tag, an
   dem die Quelle tatsächlich gezogen wurde, und beide stehen danach
   getrennt in `baseline.md`. Direkt danach `baseline.render(workspace)` erneut
   laufen lassen, damit `baseline.md` den nachgetragenen Block zeigt.

**Artefakt:** `reporting/baseline/01/baseline.json` und `baseline.md`, um die
zuvor leeren Blöcke ergänzt. `reporting/measures.json` bleibt unberührt:
eine neue Analyse der jetzt verfügbaren Quelle ist kein Teil dieses Modus.

**Was das kostet:** Ein nachgetragener Block trägt sein eigenes `as_of`
(Festschreibedatum, Lauf-ID und je Quelle Erhebungsdatum plus Zeitraum, siehe
`baseline.write_block()`), und `baseline.render()` zeigt beides unter der
Blocküberschrift. Er ist damit sichtbar nicht
derselbe Nullpunkt wie ein Block aus dem Erstlauf: zwischen beiden Terminen
hat sich der Shop weiterbewegt, und der nachgetragene Block hat diese
Bewegung nie beobachtet, seine eigene Zeitreihe beginnt erst an seinem
eigenen Stichtag. Steht das nicht ausdrücklich neben dem Wert, liest der
nächste `/ptai-ecom:report`-Vergleich zwei verschiedene Nullpunkte als einen
und rechnet eine Bewegung aus, die nie stattgefunden hat. Die Zusammenfassung
am Ende des Nachtrags nennt deshalb je gefülltem Block sein `as_of` und sagt
ausdrücklich, dass es ein späterer, eigener Messpunkt ist, kein Teil des
Erstlauf-Nullpunkts.

**Die drei Stufe-2-Blöcke sind der Regelfall dieses Modus.**
`seo_visibility`, `sea` und `catalogue` bleiben in jedem Lauf leer, dessen
Workspace die zugehörigen Zugänge nicht hatte, und genau dafür ist
`--backfill` gebaut. Seit dem 07.09.2026 gibt es für alle drei einen
Quell-Schlüssel und eine Formel-Tabelle (Phase 3, Schritt 2), der Nachtrag
läuft also durch bis zum geschriebenen Block.

| Block | Wartet auf | Vorbehalt |
|---|---|---|
| `seo_visibility` | `dfs_rankings`, `dfs_keywords`, `backlinks` | DataForSEO-Guthaben und Budgetdeckel. Der Sichtbarkeitsverlauf entsteht nur mit `--with-history` |
| `sea` | `ads` | Google-Ads-Zugang. **Ungeprüft gegen die echte API**, siehe Verifikationsliste in `pull-ads` |
| `catalogue` | `catalogue` | Shopify-Admin-Zugang mit Katalog-Scope |

**Ein Nachtrag ohne Zugang tut korrekt nichts.** Fehlt der Zugang weiterhin,
bleibt der Block leer, und der Modus berichtet das mit dem Grund aus
`state.json`, statt still zu enden. Ein Nachtrag, der nichts tut und nichts
sagt, sähe aus wie ein Fehlschlag, der keiner ist.

## Fehlerbilder

- **Config fehlt oder ist ungültig:** siehe Voraussetzungen und Phase 0,
  `setup` anbieten, kein Raten.
- **Zweiter voller Aufruf auf einen Shop mit bestehender Baseline:** siehe
  "Ein Audit läuft genau einmal je Shop", verweigern, auf `report` oder
  `--backfill` verweisen.
- **Beschädigte `state.json` oder `baseline.json`:** beide Module werfen
  hier absichtlich (`ValueError`), nie ein stiller Neuanfang, weil der jede
  bereits bezahlte Abfrage beziehungsweise jeden bereits geschriebenen,
  unveränderlichen Block wegwerfen würde. Datei prüfen, reparieren oder
  gezielt löschen, nicht den ganzen Lauf-Ordner.
- **Einzelne Quelle in Phase 1 scheitert:** isoliert behandeln, `failed` samt
  Grund, die übrigen Quellen laufen weiter, Gate A weist es aus.
- **Alle Quellen scheitern:** Gate A zeigt eine Tabelle voller "fehlend" und
  "übersprungen". Kein technischer Abbruch, aber an dieser Stelle ist die
  Rückfrage bei Gate A ("weiterlaufen?") die eigentliche Fehlerbehandlung:
  ohne Rohdaten liefert Phase 2 nichts Belastbares.
- **Einzelner Analyse-Subagent scheitert in Phase 2:** isoliert behandeln,
  Gate B weist die fehlende Disziplin mit Grund aus, die übrigen Befunde
  gehen normal in Phase 3.
- **Unterbrochener Lauf** (Absturz, abgebrochene Sitzung, bewusstes Anhalten
  an einem Gate): `state.json` bleibt auf der zuletzt abgeschlossenen Phase
  stehen, ein erneuter Aufruf von `/ptai-ecom:audit` lädt über
  `state.load_or_new()` denselben Zustand und setzt über `next_phase()`
  exakt dort fort, keine Quelle mit Status `done` wird erneut gezogen.
- **`--backfill` auf einen bereits vollständigen Shop:** kein Block ist leer,
  es gibt nichts nachzutragen; das ist derselbe Fall wie "vollstaendig" oben
  und verweist ebenfalls auf `report`.
