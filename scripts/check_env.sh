#!/usr/bin/env bash
# Umgebungs-Check für den Setup-Wizard (/ptai-ecom:setup) und Phase 0 des Audits.
#
# Aufruf:
#   check_env.sh [<workspace-dir>]     (Default: aktuelles Verzeichnis)
#
# Prüft ohne Seiteneffekte, ob Kunden-Workspace und Rechner für die Pull-Skills
# bereit sind, und druckt eine Haken-Liste (OK/FEHLT/KAPUTT je Zeile), gruppiert
# nach Rechner, Pflicht, Empfohlen, Optional und Workspace. Welche Quelle in
# welcher Stufe steht, kommt aus scripts/audit/tiers.py.
# Exit-Code = Anzahl offener Punkte in Rechner, Pflicht und Workspace. Offenes
# in Empfohlen und Optional wird angezeigt, zählt aber nicht.
#
# Guard-Disziplin wie in psi_pull.sh: kein einzelner Check darf das Script
# abbrechen. Jeder Fehlschlag wird zur FEHLT-/KAPUTT-Zeile plus Zähler, nie zum
# Crash. Checks, deren Voraussetzung fehlt (etwa eine Config-Zeile), drucken
# FEHLT mit Verweis, statt zu scheitern.
set -euo pipefail

usage() {
  cat >&2 <<EOF
Usage: $(basename "$0") [<workspace-dir>]

  <workspace-dir>  Kunden-Workspace mit reporting/config.json und .env
                   (Default: aktuelles Verzeichnis)
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

WORKSPACE="${1:-.}"
# Absoluter Pfad des Workspace, einmal hier bestimmt. Die Pulls laufen im
# Workspace, also gilt ein relativer Pfad aus der .env dort und nicht in dem
# Verzeichnis, aus dem der Check gestartet wurde. Existiert das Verzeichnis
# nicht, bleibt der Wert wie übergeben; die Zeile dazu kommt weiter unten, und
# set -e darf hier nicht zuschlagen.
WORKSPACE_ABS="$(cd "$WORKSPACE" 2>/dev/null && pwd || printf '%s' "$WORKSPACE")"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG="${WORKSPACE}/reporting/config.json"
ENV_FILE="${WORKSPACE}/.env"

# Die zentrale Datei der Betreiber-Schlüssel, dieselbe wie in scripts/audit/env.py.
# Die Expansion steht bewusst ohne Doppelpunkt: ein gesetztes, aber leeres
# PTAI_ENV_FILE heißt "keine zentrale Datei". env.py macht daraus Path(""), also
# das aktuelle Verzeichnis, und liest dort nichts. Mit ":-" fiel der Check auf
# die Standarddatei zurück und meldete Schlüssel, die die Pulls nicht sehen.
CENTRAL_ENV="${PTAI_ENV_FILE-${HOME}/.config/ptai-ecom/.env}"
# Ein relativer Wert gilt dort, wo er gelesen wird: env.py nimmt ihn relativ zum
# Arbeitsverzeichnis des Pulls, und die Pulls wie der DataForSEO-Test-Call unten
# laufen im Workspace. Bis 11.09.2026 löste der Check ihn gegen sein eigenes
# Arbeitsverzeichnis auf. Eine Tilde bleibt, wie sie ist: env.py ruft kein
# expanduser auf, dort ist "~/x" ein gewöhnlicher relativer Pfad. Leer bleibt leer.
if [[ -n "$CENTRAL_ENV" && "$CENTRAL_ENV" != /* ]]; then
  CENTRAL_ENV="${WORKSPACE_ABS%/}/${CENTRAL_ENV}"
fi
# Nur für die Meldungen: ein leerer Pfad liest sich dort wie ein Tippfehler.
CENTRAL_ENV_SHOWN="${CENTRAL_ENV:-(keine, PTAI_ENV_FILE ist leer)}"

# Jeden Aufruf nach außen auslassen (Shopify, Live-Site, CrUX, GA4, GSC,
# DataForSEO, GEO). Für Tests gebaut, im Betrieb nie setzen.
OFFLINE="${CHECK_ENV_OFFLINE:-0}"

# Zeitlimit für den Shopify-CLI-Aufruf in Sekunden; per Env übersteuerbar
# (vor allem für Tests, im Normalbetrieb nie setzen).
SHOPIFY_TIMEOUT="${CHECK_ENV_SHOPIFY_TIMEOUT:-30}"

PROBLEMS=0

# Die Zeilen werden gesammelt und am Ende gruppiert gerendert, statt sofort zu
# drucken. Eine flache Liste aus 25 Zeilen mischt Rechner-Voraussetzungen und
# Anschluss-Zustand; bei einem funktionierenden Rechner interessieren davon
# acht. Format je Eintrag: "<Gruppe>\t<Status>\t<Text>".
LINES=()
SECTION="Sonstiges"
# Stufe der aktuellen Gruppe (required, recommended, optional) und die Quelle
# aus tiers.py, zu der die folgenden Zeilen gehören. Beide leer in Rechner und
# Workspace und für Zeilen, die zu keiner einzelnen Quelle gehören.
SECTION_TIER=""
CURRENT_KEY=""
# Offene Quellen in der Reihenfolge ihres ersten Auftretens, durch Leerzeichen
# getrennt. OPEN_LINE_KEYS hält die Quellen mit mindestens einer eigenen FEHLT-
# oder KAPUTT-Zeile; wer nur über einen Hinweis offen ist, zählt in der Ausgabe
# eigens im Kopf seiner Gruppe.
OPEN_KEYS=""
OPEN_LINE_KEYS=""

# Einstufung aus scripts/audit/tiers.py, weiter unten einmal geladen. Spalten:
# 1 key, 2 tier, 3 Stufen-Label, 4 Label, 5 provider, 6 run_sources, 7 without.
TIER_TABLE=""

# Here-String statt printf-Pipe: awk hört nach dem ersten Treffer auf, und unter
# pipefail ließe ein printf, das dann noch schreibt, den Aufruf scheitern.
tier_field() {
  if [[ -z "$TIER_TABLE" ]]; then
    return 0
  fi
  awk -F'\t' -v k="$1" -v c="$2" '$1 == k { print $c; exit }' <<<"$TIER_TABLE"
}

tier_label() {
  if [[ -z "$TIER_TABLE" ]]; then
    return 0
  fi
  awk -F'\t' -v t="$1" '$2 == t { print $3; exit }' <<<"$TIER_TABLE"
}

section() { SECTION="$1"; SECTION_TIER=""; CURRENT_KEY=""; }

# Gruppe einer eingestuften Quelle. Label und Stufe kommen aus tiers.py, nie
# aus diesem Skript. Ohne Einstufung stehen alle Quellen in "Quellen".
source_section() {
  local label
  CURRENT_KEY="$1"
  label="$(tier_field "$1" 3)"
  if [[ -n "$label" ]]; then
    SECTION="$label"
    SECTION_TIER="$(tier_field "$1" 2)"
  else
    SECTION="Quellen"
    SECTION_TIER=""
  fi
}

# Offenes in Empfohlen und Optional steht in der Liste, zählt aber nicht.
counts() { [[ "$SECTION_TIER" != "recommended" && "$SECTION_TIER" != "optional" ]]; }

mark_open() {
  if [[ -z "$CURRENT_KEY" ]]; then
    return 0
  fi
  case " ${OPEN_KEYS} " in
    *" ${CURRENT_KEY} "*) ;;
    *) OPEN_KEYS="${OPEN_KEYS:+${OPEN_KEYS} }${CURRENT_KEY}" ;;
  esac
}

open_line() {
  LINES+=("${SECTION}"$'\t'"$1"$'\t'"$2")
  mark_open
  if [[ -n "$CURRENT_KEY" ]]; then
    OPEN_LINE_KEYS="${OPEN_LINE_KEYS} ${CURRENT_KEY}"
  fi
  if counts; then
    PROBLEMS=$((PROBLEMS + 1))
  fi
}

ok()      { LINES+=("${SECTION}"$'\t'"OK"$'\t'"$1"); }
missing() { open_line "FEHLT" "$1"; }
broken()  { open_line "KAPUTT" "$1"; }
hint()    { LINES+=("${SECTION}"$'\t'"HINWEIS"$'\t'"$1"); }

# Wer eine Lücke schließen kann. "kunde" heißt: der Operator sieht die
# Quelle vielleicht, darf sie aber nicht freischalten, und es braucht eine
# Anforderung an den Kunden. Genau dieser Fall ist am 06.09.2026 zweimal
# hintereinander aufgetreten und hatte im Wizard keinen Zweig.
CUSTOMER_ASKS=()
customer_ask() { CUSTOMER_ASKS+=("$1"); }

# Letzte nicht-leere Zeile eines mehrzeiligen Outputs, gekürzt. Damit landet
# aus einem Python-Traceback die eigentliche Fehlerklasse in der Haken-Zeile.
# Leerer Input liefert "keine Ausgabe" statt leerer Klammern in der Meldung.
last_line() {
  local line
  line="$(printf '%s\n' "$1" | sed -e '/^[[:space:]]*$/d' | tail -n 1 | cut -c 1-180)"
  if [[ -z "$line" ]]; then
    printf 'keine Ausgabe'
  else
    printf '%s' "$line"
  fi
}

# Kommando mit Zeitlimit ausführen: timeout/gtimeout, wenn vorhanden, sonst
# Hintergrundprozess plus Wächter (bash-3.2-kompatibel, macOS hat kein
# timeout an Bord). Exit 124 bzw. 143 heißt: Zeitlimit gerissen. Immer in
# einem geführten Kontext aufrufen (if/||), nie nackt unter set -e.
run_with_timeout() {
  local secs="$1"
  shift
  if command -v timeout >/dev/null 2>&1; then
    timeout "$secs" "$@"
    return $?
  fi
  if command -v gtimeout >/dev/null 2>&1; then
    gtimeout "$secs" "$@"
    return $?
  fi
  # Fallback: Job-Control an, damit der Hintergrundjob eine eigene
  # Prozessgruppe bekommt und der Wächter die ganze Gruppe killt (sonst
  # überlebt ein Kindprozess des Jobs den kill). stdout läuft über eine
  # Temp-Datei statt durch die Pipe, damit ein doch überlebender Nachfahre
  # die Command-Substitution des Aufrufers nie offenhalten kann.
  local tmp_out
  local status=0
  tmp_out="$(mktemp "${TMPDIR:-/tmp}/check_env_out.XXXXXX")" || return 1
  set -m 2>/dev/null || true
  "$@" > "$tmp_out" &
  local cmd_pid=$!
  ( sleep "$secs"; kill -TERM -- -"$cmd_pid" 2>/dev/null ) &
  local watch_pid=$!
  set +m 2>/dev/null || true
  wait "$cmd_pid" 2>/dev/null || status=$?
  kill -TERM -- -"$watch_pid" 2>/dev/null || true
  wait "$watch_pid" 2>/dev/null || true
  cat "$tmp_out"
  rm -f "$tmp_out"
  return "$status"
}

# Wert eines Keys aus einer .env-Datei, mit denselben Leseregeln wie
# env.parse_env(): Kommentare und fremde Zeilen fallen weg, optionales
# "export ", Leerzeichen um "=", ein Carriage Return am Zeilenende, umschließende
# Quotes; ein leerer Wert zählt als nicht gesetzt, und der letzte nicht leere
# Wert gewinnt. Sonst sind Check und Pulls sich über einen Schlüssel uneinig.
# Zusätzlich wird eine führende Tilde aufgelöst, PTAI_GOOGLE_CREDENTIALS
# braucht das. Bewusst kein source: der Check bleibt seiteneffektfrei.
env_file_get() {
  local file="$1" key="$2" line val found=""
  if [[ ! -f "$file" || ! -r "$file" ]]; then
    return 0
  fi
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    if [[ ! "$line" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Z][A-Z0-9_]*)[[:space:]]*=[[:space:]]*(.*)$ ]]; then
      continue
    fi
    if [[ "${BASH_REMATCH[2]}" != "$key" ]]; then
      continue
    fi
    val="${BASH_REMATCH[3]}"
    val="${val%"${val##*[![:space:]]}"}"
    if [[ ${#val} -ge 2 && "${val:0:1}" == "${val: -1}" && ( "${val:0:1}" == '"' || "${val:0:1}" == "'" ) ]]; then
      val="${val:1:${#val}-2}"
    fi
    if [[ -n "$val" ]]; then
      found="$val"
    fi
  done < "$file"
  printf '%s' "${found/#\~/$HOME}"
}

# Dieselbe Suche wie scripts/audit/env.py: Umgebung, Workspace-.env, zentrale
# Datei. PTAI_GOOGLE_CREDENTIALS nie zentral: pull-ga4 und pull-gsc lesen es nur
# aus der Workspace-.env, ein zentraler Fund wäre ein falsches OK.
env_get() {
  local key="$1" val
  if [[ -n "${!key:-}" ]]; then
    printf '%s' "${!key}"
    return 0
  fi
  val="$(env_file_get "$ENV_FILE" "$key")"
  if [[ -n "$val" ]]; then
    printf '%s' "$val"
    return 0
  fi
  if [[ "$key" == "PTAI_GOOGLE_CREDENTIALS" ]]; then
    return 0
  fi
  env_file_get "$CENTRAL_ENV" "$key"
}

# Woher ein Schlüssel kommt. Nie der Wert.
env_origin() {
  local key="$1"
  if [[ -n "${!key:-}" ]]; then
    printf 'Umgebung'
  elif [[ -n "$(env_file_get "$ENV_FILE" "$key")" ]]; then
    printf 'Workspace'
  elif [[ "$key" != "PTAI_GOOGLE_CREDENTIALS" && -n "$(env_file_get "$CENTRAL_ENV" "$key")" ]]; then
    printf 'zentral'
  else
    printf 'nicht gesetzt'
  fi
}

offline_skip() { hint "$1: ausgelassen (CHECK_ENV_OFFLINE)"; }

# Der PSI-Key geht als Header über eine curl-Konfiguration auf stdin, nie in die
# URL, sonst steht er in der Prozessliste. Dieselbe Form wie key_config in
# skills/pull-cwv/scripts/psi_pull.sh.
key_header_config() {
  local key="${1//\\/\\\\}"
  key="${key//\"/\\\"}"
  printf 'header = "X-Goog-Api-Key: %s"\n' "$key"
}

# Browser für PDF und Screenshots: dieselbe Suche wie render_pdf.sh und
# shoot.sh, damit der Check nie einen anderen Fund meldet als die Verbraucher.
. "${SCRIPT_DIR}/lib/find_chrome.sh"

section "Workspace"
if [[ ! -d "$WORKSPACE" ]]; then
  broken "Workspace: Verzeichnis ${WORKSPACE} existiert nicht"
fi

# --- Rechner: jq, curl, git, Python ---------------------------------------
section "Rechner"

JQ_OK=0
CURL_OK=0
if command -v jq >/dev/null 2>&1; then
  ok "Voraussetzung: jq installiert"
  JQ_OK=1
else
  missing "Voraussetzung: jq fehlt (brew install jq)"
fi
if command -v curl >/dev/null 2>&1; then
  ok "Voraussetzung: curl installiert"
  CURL_OK=1
else
  missing "Voraussetzung: curl fehlt (auf macOS vorinstalliert, sonst nachinstallieren)"
fi

# git entscheidet unten, ob .env und der Schlüssel des Dienstkontos ignoriert
# oder versioniert sind. Jeder dieser Aufrufe steht in einem if, und dort liest
# sich ein fehlendes git (Exit 127) wie "kein Repo": ohne diese Zeile gäbe es
# dann still gar keine Aussage.
GIT_OK=0
if command -v git >/dev/null 2>&1; then
  GIT_OK=1
else
  hint "Voraussetzung: git fehlt, ob .env und der Schlüssel des Dienstkontos ignoriert sind, ist nicht prüfbar"
fi

PY_MODERN=0
PIP_OK=0
GAUTH_OK=0
if command -v python3 >/dev/null 2>&1; then
  py_version="$(python3 --version 2>&1 || true)"
  ok "Voraussetzung: python3 installiert (${py_version})"
  if python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    ok "Python-Version: 3.10 oder neuer"
    PY_MODERN=1
  else
    broken "Python-Version: älter als 3.10, die Pull-Scripts brauchen 3.10+ (brew install python)"
  fi
  if pip_out="$(python3 -m pip --version 2>&1)"; then
    ok "pip: funktioniert ($(last_line "$pip_out"))"
    PIP_OK=1
  else
    broken "pip: selbst kaputt ($(last_line "$pip_out")). Ausweg: Homebrew-Python (brew install python) oder pipx, nicht mit dem kaputten pip weiterprobieren"
  fi
  # google.auth allein reicht nicht: google_token.py holt sich den Token über
  # google.auth.transport.requests, und das zieht das Paket requests nach.
  if python3 -c 'import google.auth, google.auth.transport.requests' >/dev/null 2>&1; then
    ok "google-auth: importierbar (inkl. requests-Transport)"
    GAUTH_OK=1
  elif python3 -c 'import google.auth' >/dev/null 2>&1; then
    missing "google-auth: da, aber der requests-Transport fehlt. Nachziehen mit: pip3 install --user requests, danach erneut prüfen"
  elif [[ "$PIP_OK" -eq 1 ]]; then
    missing "google-auth: nicht importierbar. pip funktioniert, also: pip3 install --user google-auth requests, danach erneut prüfen"
  else
    missing "google-auth: nicht importierbar, und pip ist kaputt (siehe oben). Über ein Homebrew-Python oder pipx installieren"
  fi
else
  missing "Voraussetzung: python3 fehlt (brew install python)"
  missing "Python-Version: nicht prüfbar (python3 fehlt)"
  missing "pip: nicht prüfbar (python3 fehlt)"
  missing "google-auth: nicht prüfbar (python3 fehlt)"
fi

# --- Einstufung aus scripts/audit/tiers.py --------------------------------
# Eine Stelle für Pflicht, Empfohlen und Optional. Ohne lauffähiges python3
# landet jede Quelle in der Gruppe "Quellen", und jede offene Zeile dort zählt.
if [[ "$PY_MODERN" -eq 1 ]]; then
  if tier_out="$(cd "${PLUGIN_ROOT}/scripts" && python3 -m audit.tiers 2>&1)"; then
    TIER_TABLE="$tier_out"
  else
    broken "Einstufung: python3 -m audit.tiers schlug fehl ($(last_line "$tier_out")). Alle Quellen stehen deshalb in der Gruppe Quellen, und jede offene Zeile dort zählt"
  fi
fi

# --- Rechner: Browser für PDF-Rendering und Screenshots --------------------
# Ein Fund deckt beide Verbraucher ab: render_pdf.sh (Monats-Report) und
# shoot.sh (capture-screens) suchen über scripts/lib/find_chrome.sh, und die
# Zeile nennt, welcher Browser es geworden ist.
if chrome_bin="$(find_chrome)"; then
  ok "Browser: $(browser_name "$chrome_bin") gefunden (${chrome_bin}), für PDF-Rendering und Screenshots"
else
  missing "Browser: weder die Headless Shell von Playwright noch Google Chrome oder Chromium gefunden. Das Monats-PDF und die Audit-Screenshots (capture-screens) brauchen eins davon. Installieren: ${BROWSER_INSTALL_HINT}"
fi

# --- Rechner: Einstellungen des Betreibers (zählen nie) --------------------
# Beide haben eine Vorgabe, deshalb OK oder Hinweis, nie offen. audit-light
# braucht PTAI_ACCOUNTS_ROOT, um Kunden zu finden und neue anzulegen; der große
# Audit liest stattdessen drive_path aus der Config. Dieselben Regeln wie
# account.accounts_root(): Tilde aufgelöst; relativ oder ohne Ordner ist dort
# ein Fehler und hier ein Hinweis. Den Namen zeigt der Check nie, nur die Quelle.
accounts_root="$(env_get PTAI_ACCOUNTS_ROOT)"
accounts_root="${accounts_root/#\~/$HOME}"
if [[ -z "$accounts_root" ]]; then
  hint "Kundenordner: PTAI_ACCOUNTS_ROOT nicht gesetzt, audit-light nutzt die Vorgabe ~/ptai-ecom/accounts"
elif [[ "$accounts_root" != /* ]]; then
  hint "Kundenordner: PTAI_ACCOUNTS_ROOT ($(env_origin PTAI_ACCOUNTS_ROOT)) ist kein absoluter Pfad. audit-light bricht damit ab"
elif [[ -d "$accounts_root" ]]; then
  ok "Kundenordner: PTAI_ACCOUNTS_ROOT gesetzt ($(env_origin PTAI_ACCOUNTS_ROOT)), ${accounts_root} vorhanden"
else
  hint "Kundenordner: PTAI_ACCOUNTS_ROOT zeigt auf ${accounts_root}, den Ordner gibt es nicht. audit-light bricht damit ab; liegt er in einem Cloud-Ordner, prüfen, ob der eingebunden ist"
fi

if [[ -n "$(env_get PTAI_OPERATOR_NAME)" ]]; then
  ok "Betreiber-Name: PTAI_OPERATOR_NAME gesetzt ($(env_origin PTAI_OPERATOR_NAME))"
else
  hint "Betreiber-Name: PTAI_OPERATOR_NAME nicht gesetzt, Maßnahmen und Report nennen den Betreiber mit der Vorgabe"
fi

# --- Workspace: Config ------------------------------------------------------
section "Workspace"

CONFIG_OK=0
if [[ -f "$CONFIG" ]]; then
  if [[ "$JQ_OK" -eq 1 ]]; then
    if jq -e . "$CONFIG" >/dev/null 2>&1; then
      ok "Config: reporting/config.json vorhanden und parsebar"
      CONFIG_OK=1
    else
      broken "Config: reporting/config.json ist kein gültiges JSON (jq kann sie nicht parsen)"
    fi
  else
    missing "Config: reporting/config.json vorhanden, aber ohne jq nicht prüfbar (siehe oben)"
  fi
else
  missing "Config: ${CONFIG} nicht gefunden (legt der Setup-Wizard an)"
fi

CFG_STORE=""
CFG_GA4=""
CFG_GSC=""
CFG_DOMAIN=""
CFG_GEO_METHOD=""
CFG_GOOGLE_DOMAIN="google.de"
CFG_ACCOUNT_SLUG=""
CFG_DRIVE_PATH=""
# Ohne Config ist unbekannt, ob der Shop SEA fährt. Unbekannt wird wie "ja"
# behandelt, siehe unten beim customer_ask. Die Vorbelegung muss hier stehen:
# ohne sie bricht das Script unter set -u ab, sobald keine Config existiert.
CFG_ADS="unbekannt"
if [[ "$CONFIG_OK" -eq 1 ]]; then
  CFG_STORE="$(jq -r '.shopify_store // empty' "$CONFIG" 2>/dev/null || true)"
  CFG_GA4="$(jq -r '.ga4_property_id // empty' "$CONFIG" 2>/dev/null || true)"
  CFG_GSC="$(jq -r '.gsc_site // empty' "$CONFIG" 2>/dev/null || true)"
  CFG_DOMAIN="$(jq -r '.domain // empty' "$CONFIG" 2>/dev/null || true)"
  CFG_GEO_METHOD="$(jq -r '.geo_method // empty' "$CONFIG" 2>/dev/null || true)"
  CFG_GOOGLE_DOMAIN="$(jq -r '.google_domain // "google.de"' "$CONFIG" 2>/dev/null || echo "google.de")"
  # sources.ads sagt, ob der Shop überhaupt SEA fährt. Fehlt der Schlüssel,
  # ist es unbekannt, und unbekannt wird wie "ja" behandelt: eine Zeile zu
  # viel in der Kundenanforderung kostet eine Rückfrage, eine fehlende Zeile
  # kostet den ganzen SEA-Block.
  CFG_ADS="$(jq -r 'if has("sources") and (.sources | has("ads")) then (.sources.ads | tostring) else "unbekannt" end' "$CONFIG" 2>/dev/null || echo "unbekannt")"
  CFG_ACCOUNT_SLUG="$(jq -r '.account_slug // empty' "$CONFIG" 2>/dev/null || true)"
  CFG_DRIVE_PATH="$(jq -r '.drive_path // empty' "$CONFIG" 2>/dev/null || true)"
fi

# Ob eine Quelle des Kunden in der Config abgeschaltet ist: alle ihre
# run_sources stehen auf false. Ein fehlender Schlüssel heißt an. Quellen des
# Betreibers kennen das nicht (Spec 2026-09-11, Abschnitt 6.1).
switched_off() {
  local key="$1" provider run_sources rs
  if [[ "$CONFIG_OK" -ne 1 ]]; then
    return 1
  fi
  provider="$(tier_field "$key" 5)"
  if [[ "$provider" != "customer" && "$provider" != "both" ]]; then
    return 1
  fi
  run_sources="$(tier_field "$key" 6)"
  if [[ -z "$run_sources" ]]; then
    return 1
  fi
  for rs in ${run_sources//,/ }; do
    # Nicht `// "x"`: jq behandelt false dort wie leer.
    if [[ "$(jq -r --arg rs "$rs" '(.sources // {})[$rs] | tostring' "$CONFIG" 2>/dev/null)" != "false" ]]; then
      return 1
    fi
  done
  return 0
}

# Eine Zeile statt aller übrigen Zeilen der Quelle.
report_switched_off() { missing "$(tier_field "$1" 4): in der Config abgeschaltet"; }

# --- Rechner: Shopify CLI -------------------------------------------------
# Steht hinter der Config, weil es auf sie ankommt: ist Shopify dort
# abgeschaltet, braucht der Rechner die CLI für diesen Kunden nicht, und ihr
# Fehlen ist ein Hinweis. Die Zeile "in der Config abgeschaltet" steht einmal,
# unter Pflicht, deshalb fehlt das Wort hier.
section "Rechner"

SHOPIFY_OK=0
if command -v shopify >/dev/null 2>&1; then
  ok "Shopify: CLI installiert"
  SHOPIFY_OK=1
elif switched_off shopify; then
  hint "Shopify: CLI fehlt (npm install -g @shopify/cli@latest). Zählt nicht, solange die Config Shopify nicht nutzt"
else
  missing "Shopify: CLI fehlt (npm install -g @shopify/cli@latest)"
fi

# --- Workspace: .env und Kundenordner -------------------------------------
section "Workspace"

# Zuerst, ob .env schon versioniert ist: git check-ignore antwortet für eine
# versionierte Datei mit Exit 1, auch wenn die .gitignore sie trifft, und der
# Rat, sie dort aufzunehmen, ginge ins Leere.
if [[ -f "$ENV_FILE" ]] && git -C "$WORKSPACE" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if git -C "$WORKSPACE" ls-files --error-unmatch -- .env >/dev/null 2>&1; then
    broken "Secrets: .env ist im Git-Repo bereits versioniert, ein Eintrag in .gitignore wirkt darauf nicht. Mit git rm --cached -- .env aus dem Index nehmen, '.env' in .gitignore aufnehmen und committen. Die Schlüssel darin bleiben in der Git-Historie: war der Commit je gepusht, jeden Schlüssel beim Anbieter neu erzeugen"
  elif git -C "$WORKSPACE" check-ignore -q .env 2>/dev/null; then
    ok "Secrets: .env ist gitignored"
  else
    broken "Secrets: .env liegt in einem Git-Repo, ist aber nicht gitignored. '.env' in die .gitignore des Workspace aufnehmen"
  fi
fi

# Ohne beide Felder weiß ein Audit-Lauf nicht, in welchen Kundenordner
# Screenshots und Deliverables gehören, und legt sie sonst im Repo ab
# (verletzt die PII-Regel, siehe setup-Skill).
if [[ -n "$CFG_ACCOUNT_SLUG" ]]; then
  ok "Kundenordner: account_slug gesetzt (${CFG_ACCOUNT_SLUG})"
elif [[ "$CONFIG_OK" -eq 1 ]]; then
  missing "Kundenordner: account_slug fehlt in der Config (Name des Kundenordners unter PTAI_ACCOUNTS_ROOT)"
else
  missing "Kundenordner: account_slug nicht prüfbar (Config fehlt oder kaputt, siehe oben)"
fi

if [[ -z "$CFG_DRIVE_PATH" ]]; then
  if [[ "$CONFIG_OK" -eq 1 ]]; then
    missing "Kundenordner: drive_path fehlt in der Config"
  else
    missing "Kundenordner: drive_path nicht prüfbar (Config fehlt oder kaputt, siehe oben)"
  fi
elif [[ "$CFG_DRIVE_PATH" != /* ]]; then
  # Absolut ist Pflicht, wie in config.validate(): ein relativer Wert landete
  # relativ zum Workspace und damit im Kunden-Repo.
  broken "Kundenordner: drive_path '${CFG_DRIVE_PATH}' ist relativ, muss der volle Pfad zum Kundenordner sein (python3 -m audit.account <domain> gibt ihn aus)"
elif [[ -d "$CFG_DRIVE_PATH" ]]; then
  if [[ -w "$CFG_DRIVE_PATH" ]]; then
    ok "Kundenordner: ${CFG_DRIVE_PATH} vorhanden und beschreibbar"
  else
    broken "Kundenordner: ${CFG_DRIVE_PATH} vorhanden, aber nicht beschreibbar (Zugriffsrechte prüfen)"
  fi
else
  # Der Kundenordner kann vor dem ersten Lauf noch fehlen; dann muss
  # wenigstens das Eltern-Verzeichnis da und beschreibbar sein, damit ein
  # späteres mkdir -p greift.
  drive_parent="$(dirname "$CFG_DRIVE_PATH")"
  if [[ -d "$drive_parent" && -w "$drive_parent" ]]; then
    ok "Kundenordner: ${CFG_DRIVE_PATH} existiert noch nicht, Eltern-Verzeichnis ${drive_parent} ist beschreibbar"
  else
    broken "Kundenordner: ${CFG_DRIVE_PATH} existiert nicht und das Eltern-Verzeichnis ${drive_parent} ist nicht erreichbar oder nicht beschreibbar. Pfad prüfen; liegt er in einem Cloud-Ordner, ob der eingebunden ist"
  fi
fi

# --- Pflicht: Shopify -----------------------------------------------------
source_section shopify

if switched_off shopify; then
  report_switched_off shopify
elif [[ "$SHOPIFY_OK" -eq 1 && -n "$CFG_STORE" ]]; then
  # Das Auth-List-JSON hält nur die nackte Subdomain ({"sessions":[{"subdomain":
  # "beispielshop-de",...}]}), nie die volle myshopify.com-Domain aus der Config.
  # Deshalb Suffix abschneiden und gezielt das subdomain-Feld matchen.
  store_subdomain="${CFG_STORE%%.myshopify.com*}"
  if [[ "$OFFLINE" == "1" ]]; then
    offline_skip "Shopify-Auth für ${CFG_STORE}"
  else
    auth_status=0
    auth_list="$(run_with_timeout "$SHOPIFY_TIMEOUT" shopify store auth list --json 2>/dev/null)" || auth_status=$?
    if [[ "$auth_status" -eq 0 ]]; then
      auth_match=0
      if [[ "$JQ_OK" -eq 1 ]] && jq -e . >/dev/null 2>&1 <<<"$auth_list"; then
        if jq -e --arg sub "$store_subdomain" \
          '[.. | objects | select(.subdomain? == $sub)] | length > 0' \
          >/dev/null 2>&1 <<<"$auth_list"; then
          auth_match=1
        fi
      elif grep -Eq "\"subdomain\"[[:space:]]*:[[:space:]]*\"${store_subdomain}\"" <<<"$auth_list" 2>/dev/null; then
        auth_match=1
      fi
      if [[ "$auth_match" -eq 1 ]]; then
        ok "Shopify: Auth für ${CFG_STORE} vorhanden"
      else
        missing "Shopify: keine Auth für ${CFG_STORE}. Auth nach der Scope-Union-Regel der pull-shopify-Skill, nie narrow"
      fi
    elif [[ "$auth_status" -eq 124 || "$auth_status" -eq 143 ]]; then
      broken "Shopify: 'shopify store auth list --json' hat nach ${SHOPIFY_TIMEOUT}s nicht geantwortet (Timeout)"
    else
      broken "Shopify: 'shopify store auth list --json' schlug fehl (CLI aktualisieren: npm install -g @shopify/cli@latest)"
    fi
  fi
elif [[ "$SHOPIFY_OK" -eq 1 ]]; then
  missing "Shopify: Auth nicht prüfbar (shopify_store fehlt in der Config)"
else
  # Das Fehlen der CLI zählt schon unter Rechner. Offen ist Shopify trotzdem,
  # sonst stünde am Ende "Pflicht vollständig." über einem Shop ohne Anschluss.
  hint "Shopify: Auth nicht prüfbar (CLI fehlt)"
  mark_open
fi

# --- Pflicht: Google-Dienstkonto für GA4 und Search Console ----------------
# Die Zeilen gehören zu keiner einzelnen Quelle. Sie stehen in der Gruppe von
# GA4 (beide Pflicht, gelesen aus tiers.py) und zählen dort, lösen aber keinen
# "Ohne ... fehlt"-Satz aus: offen werden GA4 und Search Console über ihre
# Test-Call-Zeilen weiter unten.
CREDS_OK=0
CREDS_PATH=""
if ! switched_off ga4 || ! switched_off gsc; then
  source_section ga4
  CURRENT_KEY=""
  # Die Workspace-.env hält nur noch den Pfad zum Dienstkonto, alle anderen
  # Schlüssel dürfen zentral stehen. Eine fehlende Datei ist deshalb kein eigener
  # Punkt mehr, die Zeile zum Dienstkonto sagt, was fehlt.
  CREDS_PATH="$(env_get PTAI_GOOGLE_CREDENTIALS)"
  # pull-ga4 und pull-gsc übergeben den Pfad unverändert und laufen im Workspace,
  # ein relativer Pfad gilt also dort. Bis 11.09.2026 prüfte der Check ihn gegen
  # das Verzeichnis, aus dem er gestartet wurde, und meldete eine vorhandene
  # Datei als fehlend, sobald das nicht der Workspace war. Die Test-Calls unten
  # bekommen denselben absoluten Pfad.
  if [[ -n "$CREDS_PATH" && "$CREDS_PATH" != /* ]]; then
    CREDS_PATH="${WORKSPACE_ABS%/}/${CREDS_PATH}"
  fi
  if [[ -z "$CREDS_PATH" ]]; then
    missing "Google-Dienstkonto für GA4 und Search Console: PTAI_GOOGLE_CREDENTIALS nicht in der .env des Workspace gesetzt (die Datei hält nur noch diesen Pfad, alle anderen Schlüssel dürfen zentral stehen)"
  elif [[ -f "$CREDS_PATH" ]]; then
    if [[ "$JQ_OK" -ne 1 ]] || jq -e '.type == "service_account" and (.client_email | type == "string") and (.private_key | type == "string")' "$CREDS_PATH" >/dev/null 2>&1; then
      ok "Google-Dienstkonto für GA4 und Search Console: Service-Account-JSON vorhanden (${CREDS_PATH})"
      CREDS_OK=1
    else
      broken "Google-Dienstkonto für GA4 und Search Console: ${CREDS_PATH} ist kein gültiges Service-Account-JSON (type, client_email oder private_key fehlt). Den Schlüssel in der Google Cloud Console neu erzeugen"
    fi
    # Liegt der Key im Git-Repo des Workspace (Soll-Konvention secrets/), muss er
    # gitignored sein. Das entscheidet git selbst, nicht ein Vergleich von
    # Pfadpräfixen: git löst ".." auf und erkennt den Workspace auch unter einer
    # anderen Symlink-Schreibweise (/tmp gegen /private/tmp). Der Präfixvergleich
    # bis 11.09.2026 ließ beides still aus, ein nicht ignorierter Key unter
    # keys/../keys/sa.json ergab gar keine Zeile.
    if git -C "$WORKSPACE" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      # Zuerst, ob der Key schon versioniert ist. git check-ignore antwortet
      # dafür mit Exit 1, auch wenn die .gitignore ihn trifft, und riet dann zu
      # einer Zeile, die schon dort stand. ls-files: 0 versioniert, 1 nicht
      # versioniert, 128 außerhalb des Repo.
      creds_tracked_status=0
      git -C "$WORKSPACE" ls-files --error-unmatch -- "$CREDS_PATH" >/dev/null 2>&1 || creds_tracked_status=$?
      if [[ "$creds_tracked_status" -eq 0 ]]; then
        broken "Google-Dienstkonto für GA4 und Search Console: ${CREDS_PATH} ist im Git-Repo bereits versioniert, ein Eintrag in .gitignore wirkt darauf nicht. Mit git rm --cached -- '${CREDS_PATH}' aus dem Index nehmen, 'secrets/' in .gitignore aufnehmen und committen. Der Schlüssel bleibt in der Git-Historie: war der Commit je gepusht, den Schlüssel in der Google Cloud Console löschen und neu erzeugen"
      else
        # Exit 0 heißt ignoriert, 1 heißt im Repo und nicht ignoriert, 128 heißt,
        # git kann den Pfad nicht beurteilen, meist weil er außerhalb des Repo
        # liegt. Das "|| creds_ignore_status=$?" hält set -e davon ab, bei 1 oder
        # 128 abzubrechen.
        creds_ignore_status=0
        git -C "$WORKSPACE" check-ignore -q -- "$CREDS_PATH" >/dev/null 2>&1 || creds_ignore_status=$?
        case "$creds_ignore_status" in
          0)
            ok "Google-Dienstkonto für GA4 und Search Console: ${CREDS_PATH} ist gitignored"
            ;;
          1)
            broken "Google-Dienstkonto für GA4 und Search Console: ${CREDS_PATH} liegt im Git-Repo, ist aber NICHT gitignored. 'secrets/' in .gitignore und .git/info/exclude aufnehmen, siehe setup-Skill Abschnitt Secrets"
            ;;
          *)
            hint "Google-Dienstkonto für GA4 und Search Console: git kann für ${CREDS_PATH} nicht sagen, ob die Datei ignoriert ist, meist liegt sie außerhalb des Git-Repo des Workspace (git check-ignore, Exit ${creds_ignore_status})"
            ;;
        esac
      fi
    fi
  else
    broken "Google-Dienstkonto für GA4 und Search Console: PTAI_GOOGLE_CREDENTIALS zeigt auf ${CREDS_PATH}, die Datei existiert nicht"
  fi
fi

GA4_SCRIPT="${PLUGIN_ROOT}/skills/pull-ga4/scripts/ga4_pull.py"
GSC_SCRIPT="${PLUGIN_ROOT}/skills/pull-gsc/scripts/gsc_pull.py"

check_reason=""
if [[ "$CREDS_OK" -ne 1 ]]; then
  check_reason="Creds-Datei fehlt oder ist ungültig"
fi
if [[ "$GAUTH_OK" -ne 1 ]]; then
  check_reason="${check_reason:+${check_reason}, }google-auth fehlt"
fi
if [[ "$PY_MODERN" -ne 1 ]]; then
  check_reason="${check_reason:+${check_reason}, }Python zu alt oder nicht da"
fi

# --- Pflicht: Google Analytics 4 ------------------------------------------
source_section ga4

if switched_off ga4; then
  report_switched_off ga4
else
  # Der Tag ist ein Zustand beim Kunden, kein Zugang: der Betreiber kann ihn im
  # Setup nicht beheben. Deshalb ist jeder Zweig ohne Fund ein Hinweis und zählt
  # nie als offener Punkt.
  if [[ "$OFFLINE" == "1" ]]; then
    offline_skip "GA4-Tag"
  elif [[ "$CURL_OK" -eq 1 && -n "$CFG_DOMAIN" ]]; then
    if site_html="$(curl -sL --max-time 30 "$CFG_DOMAIN" 2>/dev/null)"; then
      tag_hits="$(grep -Ec 'googletagmanager|gtag' <<<"$site_html" || true)"
      if [[ "$tag_hits" -gt 0 ]]; then
        ok "GA4-Tag: auf ${CFG_DOMAIN} gefunden (${tag_hits} Treffer)"
      else
        hint "GA4-Tag: auf ${CFG_DOMAIN} nicht gefunden (weder googletagmanager noch gtag im HTML). Zustand beim Kunden, im Audit weist ihn die Datenqualitäts-Analyse aus"
      fi
    else
      hint "GA4-Tag: ${CFG_DOMAIN} nicht abrufbar (curl-Fehler oder Timeout)"
    fi
  elif [[ "$CURL_OK" -eq 1 ]]; then
    hint "GA4-Tag: nicht prüfbar (domain fehlt in der Config)"
  else
    hint "GA4-Tag: nicht prüfbar (curl fehlt)"
  fi

  if [[ -z "$check_reason" && -n "$CFG_GA4" ]]; then
    if [[ "$OFFLINE" == "1" ]]; then
      offline_skip "GA4-Test-Call"
    elif check_out="$(python3 "$GA4_SCRIPT" --property "$CFG_GA4" --creds "$CREDS_PATH" --check 2>&1)"; then
      ok "GA4-Test-Call: $(last_line "$check_out")"
    else
      broken "GA4-Test-Call: fehlgeschlagen ($(last_line "$check_out")). Property-Freigabe für die Service-Account-Mail prüfen"
      customer_ask "Google Analytics 4: das Dienstkonto als Betrachter auf der Property freischalten (Verwaltung, Property-Zugriffsverwaltung). Wer selbst keine Nutzer hinzufügen darf, braucht dafür jemanden mit Administratorrechten auf der Property."
    fi
  elif [[ -z "$check_reason" ]]; then
    missing "GA4-Test-Call: nicht möglich (ga4_property_id fehlt in der Config)"
  else
    # Der Grund zählt schon oben (Dienstkonto, google-auth, Python).
    hint "GA4-Test-Call: nicht möglich (${check_reason}, siehe oben)"
    mark_open
  fi
fi

# --- Pflicht: Google Search Console ---------------------------------------
source_section gsc

if switched_off gsc; then
  report_switched_off gsc
elif [[ -z "$check_reason" && -n "$CFG_GSC" ]]; then
  if [[ "$OFFLINE" == "1" ]]; then
    offline_skip "GSC-Test-Call"
  elif check_out="$(python3 "$GSC_SCRIPT" --site "$CFG_GSC" --creds "$CREDS_PATH" --check 2>&1)"; then
    ok "GSC-Test-Call: $(last_line "$check_out")"
  else
    broken "GSC-Test-Call: fehlgeschlagen ($(last_line "$check_out")). Property-Zugriff für die Service-Account-Mail prüfen"
    customer_ask "Google Search Console: das Dienstkonto mit der Berechtigung Uneingeschränkt hinzufügen (Einstellungen, Nutzer und Berechtigungen). Das kann dort ausschließlich ein Eigentümer der Property."
  fi
elif [[ -z "$check_reason" ]]; then
  missing "GSC-Test-Call: nicht möglich (gsc_site fehlt in der Config)"
else
  # Der Grund zählt schon oben (Dienstkonto, google-auth, Python).
  hint "GSC-Test-Call: nicht möglich (${check_reason}, siehe oben)"
  mark_open
fi

# --- Empfohlen: DataForSEO ------------------------------------------------
source_section dataforseo

# DataForSEO gehört dem Betreiber, nicht dem Kunden: kein customer_ask.
# Eine Zeile in der Kundenanforderung, die der Operator selbst erledigen
# muss, macht die Anforderung unglaubwürdig.
#
# Login und Passwort liest der Check wie audit.env.get_together(): maßgeblich
# ist die Ebene, in der der Login steht, und das Passwort zählt nur aus
# derselben Ebene. Einzeln aufgelöst meldete der Check einen zentralen Login
# plus ein Passwort aus dem Workspace als gefunden, während dfs_client.py in
# der zentralen Datei kein Passwort findet und alle fünf Pulls ausfallen.
DFS_ENV_OK=0
dfs_login="$(env_get PTAI_DFS_LOGIN)"
dfs_origin="$(env_origin PTAI_DFS_LOGIN)"
dfs_password_any="$(env_get PTAI_DFS_PASSWORD)"
dfs_password=""
dfs_where=""
case "$dfs_origin" in
  Umgebung)
    dfs_password="${PTAI_DFS_PASSWORD:-}"
    dfs_where="in der Umgebung"
    ;;
  Workspace)
    dfs_password="$(env_file_get "$ENV_FILE" PTAI_DFS_PASSWORD)"
    dfs_where="in der .env des Workspace"
    ;;
  zentral)
    dfs_password="$(env_file_get "$CENTRAL_ENV" PTAI_DFS_PASSWORD)"
    dfs_where="in der zentralen Datei ${CENTRAL_ENV}"
    ;;
esac
if [[ -n "$dfs_login" && -n "$dfs_password" ]]; then
  ok "DataForSEO: PTAI_DFS_LOGIN und PTAI_DFS_PASSWORD gefunden (${dfs_origin})"
  DFS_ENV_OK=1
elif [[ -n "$dfs_login" && -n "$dfs_password_any" ]]; then
  broken "DataForSEO: PTAI_DFS_LOGIN steht ${dfs_where}, PTAI_DFS_PASSWORD steht nicht an derselben Stelle. Die Pulls nehmen beide aus der Ebene des Logins: das Passwort dort ergänzen oder beide an eine Stelle legen"
elif [[ -n "$dfs_login" || -n "$dfs_password_any" ]]; then
  broken "DataForSEO: nur eine der beiden Zeilen (PTAI_DFS_LOGIN, PTAI_DFS_PASSWORD) ist gesetzt"
else
  missing "DataForSEO: PTAI_DFS_LOGIN und PTAI_DFS_PASSWORD nicht gefunden, weder im Workspace noch zentral in ${CENTRAL_ENV_SHOWN} (die fünf DataForSEO-Pulls fallen sonst aus)"
fi

# DataForSEO-Test-Call: läuft über appendix/user_data und ist laut Doku
# kostenlos. Ein kostenpflichtiger Endpunkt hat in einem Setup-Check nichts
# verloren, der läuft bei jedem Wizard-Start. dfs_client.py findet die
# Zugangsdaten selbst; das cd sorgt dafür, dass Herkunfts-Anzeige und Test-Call
# dieselbe .env meinen, auch wenn der Check nicht aus dem Workspace startet.
DFS_SCRIPT="${PLUGIN_ROOT}/scripts/dfs_client.py"
if [[ "$DFS_ENV_OK" -eq 1 && "$PY_MODERN" -eq 1 ]]; then
  if [[ "$OFFLINE" == "1" ]]; then
    offline_skip "DataForSEO-Test-Call"
  elif check_out="$(cd "$WORKSPACE" && python3 "$DFS_SCRIPT" --check 2>&1)"; then
    ok "DataForSEO-Test-Call: $(last_line "$check_out")"
  else
    broken "DataForSEO-Test-Call: fehlgeschlagen ($(last_line "$check_out")). Zugangsdaten im API-Access-Bereich prüfen"
  fi
else
  missing "DataForSEO-Test-Call: nicht möglich (Zugangsdaten fehlen oder Python zu alt, siehe oben)"
fi

# --- Empfohlen: PageSpeed und CrUX ----------------------------------------
source_section pagespeed

psi_key="$(env_get PTAI_PSI_KEY)"
if [[ -n "$psi_key" ]]; then
  ok "PSI: PTAI_PSI_KEY gefunden ($(env_origin PTAI_PSI_KEY))"
  # Der Schlüssel bedient zwei APIs. Die Klick-Anleitung sagt, ihn auf die
  # PageSpeed Insights API einzuschränken, und danach antwortet die
  # CrUX-History-API mit 403 "blocked". Die Wochenhistorie fällt dann still
  # aus, und der bisherige Check hat das nie bemerkt, weil er nur PSI trifft.
  if [[ "$OFFLINE" == "1" ]]; then
    offline_skip "CrUX-History"
  elif [[ "$CURL_OK" -eq 1 ]]; then
    crux_body="$(key_header_config "$psi_key" | curl -s --config - --max-time 20 -X POST \
      "https://chromeuxreport.googleapis.com/v1/records:queryHistoryRecord" \
      -H 'Content-Type: application/json' \
      -d '{"origin":"https://web.dev","formFactor":"PHONE"}' 2>/dev/null || true)"
    if [[ "$JQ_OK" -eq 1 ]] && jq -e '.record' >/dev/null 2>&1 <<<"$crux_body"; then
      ok "CrUX-History: mit demselben Key abrufbar (Wochenhistorie der Core Web Vitals)"
    else
      crux_err="$(jq -r '.error.message // "keine verwertbare Antwort"' <<<"$crux_body" 2>/dev/null || echo "keine verwertbare Antwort")"
      broken "CrUX-History: nicht abrufbar ($(last_line "$crux_err")). Meist ist der Key auf die PageSpeed Insights API eingeschränkt: unter APIs und Dienste, Anmeldedaten zusätzlich die Chrome UX Report API erlauben. Ohne sie fehlt die Wochenhistorie im Block Technik"
    fi
  else
    missing "CrUX-History: nicht prüfbar (curl fehlt)"
  fi
else
  missing "PSI: PTAI_PSI_KEY nicht gefunden, weder im Workspace noch zentral in ${CENTRAL_ENV_SHOWN}"
fi

# --- Empfohlen: GEO -------------------------------------------------------
source_section geo

# Die Keys sind eine Fähigkeit des Betreibers, geo_method ist die Wahl je
# Kunde (Spec 2026-09-11, Abschnitt 6.1). Offen ist GEO deshalb, wenn keiner
# der drei Schlüssel auf irgendeiner Ebene steht, egal welcher Weg gewählt ist.
# Ein unbekannter geo_method ist ein Fehler der Config und zählt unter Workspace.
GEO_KEYS_SET=0
for geo_entry in "PTAI_OPENAI_KEY|chatgpt" "PTAI_PERPLEXITY_KEY|perplexity" "PTAI_GEMINI_KEY|google-ai"; do
  if [[ -n "$(env_get "${geo_entry%%|*}")" ]]; then
    GEO_KEYS_SET=$((GEO_KEYS_SET + 1))
  fi
done
GEO_METHOD="$CFG_GEO_METHOD"
if [[ -z "$GEO_METHOD" ]]; then
  if [[ "$GEO_KEYS_SET" -gt 0 ]]; then
    GEO_METHOD="api"
  else
    GEO_METHOD="browser"
  fi
  hint "GEO: geo_method fehlt in der Config (ältere Config), behandelt wie '${GEO_METHOD}'. Einmal /ptai-ecom:setup laufen lassen trägt das Feld nach"
fi

if [[ "$GEO_KEYS_SET" -eq 0 ]]; then
  geo_none="GEO-Keys: keiner der drei Schlüssel (PTAI_OPENAI_KEY, PTAI_PERPLEXITY_KEY, PTAI_GEMINI_KEY) gefunden, weder im Workspace noch zentral in ${CENTRAL_ENV_SHOWN}"
  case "$GEO_METHOD" in
    browser) missing "${geo_none}. GEO läuft über den Browser" ;;
    off)     missing "${geo_none}. GEO ist abgeschaltet" ;;
    *)       missing "${geo_none} (geo_method '${GEO_METHOD}')" ;;
  esac
else
  # Geprüft wird die Fähigkeit des Rechners, deshalb unabhängig von geo_method.
  # "Angeschlossen" ist eine Behauptung, solange niemand angerufen hat. Für PSI,
  # GA4, GSC und DataForSEO macht dieser Check einen Test-Call, für GEO stand
  # hier bis 07.09.2026 nur "ist der Schlüssel gesetzt". Deshalb meldete er
  # "angeschlossen: chatgpt, perplexity, google-ai" als OK, während der
  # Gemini-Schlüssel mit "Your project has been denied access" antwortete und im
  # Lauf alle sieben google-ai-Abfragen ausfielen. geo_api.py --check liefert
  # sauber Exit 1, es wurde nur nie aufgerufen.
  GEO_SCRIPT="${PLUGIN_ROOT}/skills/check-geo/scripts/geo_api.py"
  for geo_entry in "PTAI_OPENAI_KEY|chatgpt" "PTAI_PERPLEXITY_KEY|perplexity" "PTAI_GEMINI_KEY|google-ai"; do
    geo_var="${geo_entry%%|*}"
    geo_platform="${geo_entry##*|}"
    geo_out=""
    if [[ -z "$(env_get "$geo_var")" ]]; then
      hint "GEO: ${geo_var} nicht gesetzt (${geo_platform} erscheint im Report als nicht angeschlossen)"
    elif [[ ! -f "$GEO_SCRIPT" ]]; then
      hint "GEO: ${geo_platform} nicht geprüft, ${GEO_SCRIPT} fehlt"
    elif [[ "$OFFLINE" == "1" ]]; then
      offline_skip "GEO ${geo_platform}"
    elif geo_out="$(cd "$WORKSPACE" && python3 "$GEO_SCRIPT" --check "$geo_platform" - 2>&1)"; then
      ok "GEO: ${geo_platform} antwortet ($(env_origin "$geo_var"))"
    else
      broken "GEO: ${geo_platform} antwortet nicht ($(last_line "$geo_out"))"
    fi
  done
fi

case "$GEO_METHOD" in
  api|browser|off) ;;
  *) section "Workspace"; broken "Config: geo_method '${GEO_METHOD}' ist unbekannt (erlaubt: api, browser, off)" ;;
esac

# --- Optional: Google Ads -------------------------------------------------
source_section ads

# Google Ads ist der Fall, für den customer_ask gebaut wurde: der Operator
# sieht das Konto vielleicht, freischalten kann es nur der Kunde. Das
# Entwicklertoken ist davon getrennt und gehört dem Betreiber.
if switched_off ads; then
  report_switched_off ads
elif [[ -n "$(env_get PTAI_GOOGLE_ADS_TOKEN)" ]]; then
  ok "Google Ads: PTAI_GOOGLE_ADS_TOKEN gefunden ($(env_origin PTAI_GOOGLE_ADS_TOKEN))"
else
  missing "Google Ads: PTAI_GOOGLE_ADS_TOKEN nicht gesetzt. Das Entwicklertoken gehört dem Betreiber und wird im eigenen Google-Ads-Verwaltungskonto beantragt (API-Center). Ohne es bleibt der Baseline-Block SEA leer und wird später nachgetragen"
fi
if [[ "$CFG_ADS" != "false" ]]; then
  customer_ask "Google Ads: das Dienstkonto mit der Zugriffsebene Nur Lesen als Nutzer hinzufügen (Tools und Einstellungen, Zugriff und Sicherheit, Nutzer). Ohne diesen Zugang bleibt der Baseline-Block SEA leer und wird später nachgetragen."
fi

# --- Workspace: Versionierung von reporting/ -------------------------------
section "Workspace"
# Die Trennung hängt an der Wiederholbarkeit, nicht am Ordner: was ein
# späterer Lauf jederzeit neu ziehen kann, darf ignoriert bleiben. Baseline,
# Maßnahmen und der Zustand eines Laufs können das nicht, und die Snapshots
# eines Audit-Laufs erst recht nicht: crawl.json und die Core Web Vitals
# halten einen Vorher-Zustand fest, den nach einem Relaunch keine Abfrage
# wiederherstellt.

if git -C "$WORKSPACE" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  # git check-ignore beantwortet die Frage für Pfade, die es noch nicht gibt.
  must_track=(
    "reporting/config.json"
    "reporting/baseline/01/baseline.json"
    "reporting/measures.json"
    "reporting/runs/2026-01-01-audit/state.json"
  )
  ignored_anyway=()
  for path in "${must_track[@]}"; do
    if git -C "$WORKSPACE" check-ignore -q "$path" 2>/dev/null; then
      ignored_anyway+=("$path")
    fi
  done
  if [[ ${#ignored_anyway[@]} -eq 0 ]]; then
    ok "Versionierung: Baseline, Maßnahmen, Config und Lauf-Zustand landen im Repo"
  else
    broken "Versionierung: von .gitignore ausgeschlossen, obwohl nicht wiederherstellbar: ${ignored_anyway[*]}"
  fi

  # Eine versionierte Datei beantwortet check-ignore mit Exit 1, auch wenn die
  # .gitignore sie trifft. Deshalb zuerst ls-files, sonst hieße es "würde
  # committet" über einer Datei, die längst im Repo liegt.
  for path in ".env" "secrets/google-sa.json"; do
    if git -C "$WORKSPACE" ls-files --error-unmatch -- "$path" >/dev/null 2>&1; then
      broken "Versionierung: ${path} ist bereits versioniert, .gitignore greift nicht mehr (git rm --cached -- ${path}). War der Commit je gepusht, die Schlüssel darin beim Anbieter neu erzeugen"
    elif git -C "$WORKSPACE" check-ignore -q "$path" 2>/dev/null; then
      ok "Versionierung: ${path} ist ignoriert"
    else
      broken "Versionierung: ${path} ist NICHT ignoriert und würde committet"
    fi
  done

  if git -C "$WORKSPACE" check-ignore -q "reporting/runs/2026-01-01-audit/report.pdf" 2>/dev/null; then
    ok "Versionierung: PDFs sind ignoriert (sie liegen im Kundenordner)"
  else
    hint "Versionierung: PDFs unter reporting/ sind nicht ignoriert. Sie liegen ohnehin im Kundenordner; eine Zeile 'reporting/**/*.pdf' in der .gitignore hält das Repo schlank"
  fi

  if git -C "$WORKSPACE" check-ignore -q "reporting/data/2026-01-01-audit/crawl.json" 2>/dev/null; then
    hint "Versionierung: reporting/data/ ist ignoriert. Für Report-Läufe ist das richtig (jeder Lauf zieht neu), für den Audit nicht: crawl.json und die Core Web Vitals sind der Vorher-Zustand und nach einem Relaunch nicht mehr herstellbar. Vor dem Audit eine Ausnahme ergänzen, etwa '!reporting/data/*-audit/'"
  else
    ok "Versionierung: reporting/data/ landet im Repo"
  fi
elif [[ "$GIT_OK" -eq 1 ]]; then
  # Ohne git sagt die Zeile unter Rechner schon, dass hier nichts prüfbar ist.
  hint "Versionierung: ${WORKSPACE} ist kein git-Repo, die Ergebnisse des Audits werden dort nirgends festgehalten"
fi

# --- Ausgabe ---------------------------------------------------------------
# Gruppiert statt flach, und eine vollständig grüne Gruppe schrumpft auf eine
# Zeile. Wer den Wizard führt, soll auf einen Blick sehen, was steht und was
# aussteht, statt 25 gleichrangige Zeilen zu lesen.

REQUIRED_LABEL="$(tier_label required)"
RECOMMENDED_LABEL="$(tier_label recommended)"
OPTIONAL_LABEL="$(tier_label optional)"
SECTION_ORDER=("Rechner")
for label in "$REQUIRED_LABEL" "$RECOMMENDED_LABEL" "$OPTIONAL_LABEL"; do
  if [[ -n "$label" ]]; then
    SECTION_ORDER+=("$label")
  fi
done
SECTION_ORDER+=("Quellen" "Workspace" "Sonstiges")

# Keine Zeile darf verschwinden. Die Schleife unten druckt nur Gruppen aus
# SECTION_ORDER; eine Zeile mit einem anderen Gruppennamen (ein vergessenes
# section, ein Label aus tiers.py, das hier niemand erwartet) landet deshalb in
# Sonstiges, statt still wegzufallen.
for i in "${!LINES[@]}"; do
  line_section="${LINES[$i]%%$'\t'*}"
  known=0
  for known_section in "${SECTION_ORDER[@]}"; do
    if [[ "$known_section" == "$line_section" ]]; then
      known=1
      break
    fi
  done
  if [[ "$known" -eq 0 ]]; then
    LINES[$i]="Sonstiges"$'\t'"${LINES[$i]#*$'\t'}"
  fi
done

section_has_entries() {
  local section_name="$1" entry
  for entry in "${LINES[@]}"; do
    [[ "${entry%%$'\t'*}" == "$section_name" ]] && return 0
  done
  return 1
}

for section_name in "${SECTION_ORDER[@]}"; do
  section_has_entries "$section_name" || continue

  checked=0
  open_count=0
  for entry in "${LINES[@]}"; do
    [[ "${entry%%$'\t'*}" == "$section_name" ]] || continue
    rest="${entry#*$'\t'}"
    status="${rest%%$'\t'*}"
    checked=$((checked + 1))
    [[ "$status" == "FEHLT" || "$status" == "KAPUTT" ]] && open_count=$((open_count + 1))
  done

  # Die offenen Quellen dieser Gruppe. Wer nur über einen Hinweis offen ist
  # (Shopify ohne CLI), hat keine eigene FEHLT- oder KAPUTT-Zeile und zählt im
  # Kopf eigens mit. Sonst stünde "[ok] Pflicht" über einem Shop ohne Anschluss,
  # und der "Ohne ... fehlt"-Satz der Quelle fiele weg.
  section_keys=""
  for key in $OPEN_KEYS; do
    [[ "$(tier_field "$key" 3)" == "$section_name" ]] || continue
    section_keys="${section_keys:+${section_keys} }${key}"
    case " ${OPEN_LINE_KEYS} " in
      *" ${key} "*) ;;
      *) open_count=$((open_count + 1)) ;;
    esac
  done

  if [[ "$open_count" -eq 0 ]]; then
    # Vollständig grüne Gruppe: eine Zeile genügt, die Einzelpunkte stehen
    # nur bei --verbose. Ausnahme sind Hinweise, die trotzdem sichtbar bleiben.
    printf '\n[ok] %s (%d geprüft)\n' "$section_name" "$checked"
    for entry in "${LINES[@]}"; do
      [[ "${entry%%$'\t'*}" == "$section_name" ]] || continue
      rest="${entry#*$'\t'}"
      status="${rest%%$'\t'*}"
      text="${rest#*$'\t'}"
      [[ "$status" == "HINWEIS" ]] && printf '     Hinweis: %s\n' "$text"
      if [[ "${CHECK_ENV_VERBOSE:-0}" == "1" && "$status" == "OK" ]]; then
        printf '     %s\n' "$text"
      fi
    done
    continue
  fi

  printf '\n[%d offen] %s\n' "$open_count" "$section_name"
  for entry in "${LINES[@]}"; do
    [[ "${entry%%$'\t'*}" == "$section_name" ]] || continue
    rest="${entry#*$'\t'}"
    status="${rest%%$'\t'*}"
    text="${rest#*$'\t'}"
    case "$status" in
      OK)      printf '  [x] %s\n' "$text" ;;
      FEHLT)   printf '  [ ] %s\n' "$text" ;;
      KAPUTT)  printf '  [!] %s\n' "$text" ;;
      HINWEIS) printf '      Hinweis: %s\n' "$text" ;;
    esac
  done
  for key in $section_keys; do
    printf '      Ohne %s fehlt: %s.\n' "$(tier_field "$key" 4)" "$(tier_field "$key" 7)"
  done
done

if [[ "${#CUSTOMER_ASKS[@]}" -gt 0 ]]; then
  echo
  echo "Das kann der Kunde freischalten, nicht du:"
  for ask in "${CUSTOMER_ASKS[@]}"; do
    printf '  - %s\n' "$ask"
  done
  echo "  Der Setup-Wizard erzeugt daraus die Anforderung an den Kunden (${PLUGIN_ROOT}/reference/access.md, Teil B)."
fi

# --- Summe ----------------------------------------------------------------

open_labels() {
  local key out=""
  for key in $OPEN_KEYS; do
    if [[ "$(tier_field "$key" 2)" == "$1" ]]; then
      out="${out:+${out}, }$(tier_field "$key" 4)"
    fi
  done
  printf '%s' "$out"
}

lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

echo
if [[ -n "$TIER_TABLE" ]]; then
  required_open="$(open_labels required)"
  if [[ -z "$required_open" ]]; then
    echo "${REQUIRED_LABEL} vollständig."
  else
    echo "${REQUIRED_LABEL} offen: ${required_open}."
  fi
  recommended_open="$(open_labels recommended)"
  if [[ -n "$recommended_open" ]]; then
    echo "Offen, $(lower "$RECOMMENDED_LABEL"): ${recommended_open}."
  fi
  optional_open="$(open_labels optional)"
  if [[ -n "$optional_open" ]]; then
    echo "Offen, $(lower "$OPTIONAL_LABEL"): ${optional_open}."
  fi
fi
if [[ "$PROBLEMS" -eq 0 ]]; then
  echo "Keine offenen Punkte in Rechner, ${REQUIRED_LABEL:-Pflicht} und Workspace."
else
  echo "${PROBLEMS} offene(r) Punkt(e) in Rechner, ${REQUIRED_LABEL:-Pflicht} oder Workspace. Der Setup-Wizard (/ptai-ecom:setup) führt durch die Behebung."
  if [[ "${CHECK_ENV_VERBOSE:-0}" != "1" ]]; then
    echo "Alle Einzelpunkte auch der grünen Gruppen: CHECK_ENV_VERBOSE=1 vor den Aufruf setzen."
  fi
fi
exit "$PROBLEMS"
