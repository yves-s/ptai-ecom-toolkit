#!/usr/bin/env bash
# shoot.sh: nimmt von einer URL zwei Screenshots auf, Desktop und Mobil, über
# einen headless Browser aus scripts/lib/find_chrome.sh (bevorzugt die Headless
# Shell von Playwright, sonst Google Chrome oder Chromium).
#
# Aufruf:
#   shoot.sh --url <url> --name <page-type> --target <directory>
#
# Schreibt <directory>/<page-type>-desktop.png (1440x900) und
# <directory>/<page-type>-mobil.png (390x844, mobiler User-Agent). Am Ende
# eine einzelne JSON-Zeile mit den Feldern, die screens.json je Bild braucht
# (Seitentyp, Gerät, Aufnahmezeit, Quell-URL, absoluter Pfad), damit die
# aufrufende Skill den Index zusammenbaut, ohne Pfad oder Zeitstempel selbst
# neu zu erfinden.
#
# Teil des Plugins ptai-ecom (Skill capture-screens). Muster für den
# Chrome-Aufruf: skills/report/scripts/render_pdf.sh. Guard-Disziplin aus
# scripts/check_env.sh: kein Fehlschlag bricht das ganze Script ab, jeder wird
# zu einer Fehlerzeile auf stderr plus einem Zähler, der Exit-Code ist die
# Anzahl der fehlgeschlagenen Aufnahmen (0, 1 oder 2).
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"

# Ein realistischer, aktueller Mobil-User-Agent (iOS Safari). Nur der
# User-Agent-String macht eine Seite noch nicht mobil, das Fenstermaß
# 390x844 zusammen mit dem UA schon eher: viele Shop-Themes schalten ihr
# responsives Layout über beides.
#
# ACHTUNG, gemessen am 07.09.2026: headless Google Chrome klemmt die
# Fensterbreite bei 500 Pixeln. `--window-size=390,844` ergibt
# `window.innerWidth === 500`, und das Bild wird danach auf 390 beschnitten.
# Heraus kommt der linke Ausschnitt eines 500er-Layouts, also eine Ansicht, die
# kein Mensch je sieht. Im ersten echten audit-light-Lauf hat eine Linse das
# nachgemessen: das Logo lag mittig bei 249,5 statt bei 195. Ein Layout-Befund
# vom Handy aus solchen Bildern ist eine Aussage über den Screenshot, nicht über
# den Shop.
#
# Die Headless Shell von Playwright klemmt nicht, gemessen am 15.09.2026 mit
# chromium_headless_shell-1234 (Chrome for Testing 151): 390x844 ergibt
# `window.innerWidth === 390` und ein Bild von 390 mal 844 Pixeln. Die Klemme
# gilt deshalb nur, wenn find_chrome Chrome oder Chromium liefert
# (CHROME_MIN_WIDTH weiter unten).
#
# Das Script kann die Klemme nicht heilen, also verschweigt es sie auch nicht:
# die Indexzeile trägt `viewport_width` mit der TATSÄCHLICHEN Breite und
# `viewport_clamped`, sobald die gewünschte Breite unterschritten wurde.
# Geräte-Emulation mit Pixeldichte und Touch bietet auch die Shell nicht, dafür
# braucht es Playwright selbst (`npx playwright install chromium`); das alte
# ecom-audit-Repo hat genau das getan.
MOBILE_UA="Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"

usage() {
  cat >&2 <<EOF
Usage: ${SCRIPT_NAME} --url <url> --name <page-type> --target <directory>

  --url    Seiten-URL, die aufgenommen wird
  --name   Seitentyp, wird zum Dateinamen-Präfix (z. B. start, produkt)
  --target Zielverzeichnis für die PNGs (wird bei Bedarf angelegt)

Schreibt <target>/<name>-desktop.png und <target>/<name>-mobil.png. Am Ende steht
eine Zeile "IMAGES_JSON: [...]" mit je einem Eintrag pro erfolgreich
geschriebenem Bild (page_type, device, captured_at, source_url, path).
EOF
}

# jq ist dokumentierte Voraussetzung des Plugins (README, wie in psi_pull.sh)
# und baut hier die JSON-Ausgabe, statt URLs und Pfade von Hand zu escapen.
if ! command -v jq >/dev/null 2>&1; then
  echo "Fehler: 'jq' ist nicht installiert, wird aber benötigt." >&2
  exit 1
fi

URL=""
NAME=""
TARGET=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --url)
      URL="${2:-}"
      shift 2
      ;;
    --name)
      NAME="${2:-}"
      shift 2
      ;;
    --target)
      TARGET="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Fehler: unbekannte Option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "$URL" || -z "$NAME" || -z "$TARGET" ]]; then
  usage
  exit 2
fi

# Pfad absolut machen: Chrome und die screens.json-Einträge brauchen einen
# Pfad, der auch dann noch stimmt, wenn der Aufrufer später das Verzeichnis
# wechselt (die Analysen lesen die Bilder ausschließlich über den Index).
abs_path() {
  case "$1" in
    /*) printf '%s' "$1" ;;
    *)  printf '%s/%s' "$(pwd)" "$1" ;;
  esac
}

TARGET_ABS="$(abs_path "$TARGET")"
mkdir -p "$TARGET_ABS"

# Browser finden: eine Suche für alle drei Aufrufer, scripts/lib/find_chrome.sh.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${SCRIPT_DIR}/../../../scripts/lib/find_chrome.sh"

if ! CHROME="$(find_chrome)"; then
  echo "Fehler: weder die Headless Shell von Playwright noch Google Chrome oder Chromium gefunden." >&2
  echo "Screenshots brauchen eins davon. Installieren: ${BROWSER_INSTALL_HINT}, dann erneut ausführen." >&2
  exit 1
fi

# Kleinste Fensterbreite, die der gefundene Browser wirklich rendert, 0 heißt
# ohne Klemme. Warum das am Browser hängt, steht im Kopf dieses Scripts.
if is_headless_shell "$CHROME"; then
  readonly CHROME_MIN_WIDTH=0
else
  readonly CHROME_MIN_WIDTH=500
fi

PROBLEMS=0
CLAMPED_ANY=0
ENTRIES=()

# Eine Aufnahme (ein Gerät). Schreibt nie ab unter set -e: ein Chrome-Fehlschlag
# bei einem Gerät darf das andere nicht verhindern, deshalb läuft der
# Chrome-Aufruf selbst in einem geführten if, nie nackt.
#
# --dump-dom läuft im selben Aufruf mit, ohne zweiten Chrome-Start: bei einem
# Verbindungsfehler (DNS, Timeout, TLS) schreibt Chrome trotzdem ein Bild und
# beendet sich mit Exit 0, nur eben ein Bild von Chromes eigener
# Fehlerseite ("Die Website ist nicht erreichbar" bzw. "This site can't be
# reached"), nicht von der Zielseite. Das ist genau das falsche Bild, das
# durch keinen Größen- oder Exit-Code-Check auffällt: die Fehlerseite ist
# einige Zehn-KB groß, wie eine echte Seite. Die interne Chromium-Markierung
# dieser Fehlerseite (`main-frame-error`) ist über Sprache und Chrome-Version
# stabil, ein einzelner echter Shop müsste zufällig genau diese Zeichenkette
# im eigenen Markup tragen, um das fälschlich auszulösen.
# Zeitlimit für einen Chrome-Aufruf in Sekunden, per Env übersteuerbar.
# Headless Chrome kehrt auf manchen Seiten nicht zurück: am 07.09.2026 hing die
# Mobil-Aufnahme einer Blog-Seite 26 Minuten, während die Desktop-Aufnahme
# derselben Adresse durchlief. Ohne Limit blockiert das im Audit-Orchestrator
# Phase 1 unbegrenzt, ohne dass irgendwo ein Fehler auftaucht.
SHOOT_TIMEOUT="${SHOOT_TIMEOUT:-90}"

# Kommando mit Zeitlimit: timeout/gtimeout, wenn vorhanden, sonst
# Hintergrundprozess plus Wächter (bash 3.2 auf macOS hat kein timeout).
# Exit 124 bzw. 143 heißt: Zeitlimit gerissen. Dieselbe Mechanik wie in
# scripts/check_env.sh, dort seit dem Setup-Wizard bewährt.
run_with_timeout() {
  local secs="$1"; shift
  if command -v timeout >/dev/null 2>&1; then
    timeout "$secs" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then
    gtimeout "$secs" "$@"
  else
    "$@" &
    local pid=$!
    ( sleep "$secs"; kill -TERM "$pid" 2>/dev/null ) &
    local waechter=$!
    wait "$pid" 2>/dev/null
    local code=$?
    kill "$waechter" 2>/dev/null
    return "$code"
  fi
}

capture() {
  local device="$1" window="$2" ua="$3"
  local out="${TARGET_ABS}/${NAME}-${device}.png"
  local -a cmd=(
    "$CHROME" --headless --disable-gpu --hide-scrollbars
    --force-device-scale-factor=1
    --window-size="$window"
    --screenshot="$out"
    --dump-dom
  )
  if [[ -n "$ua" ]]; then
    cmd+=(--user-agent="$ua")
  fi
  cmd+=("$URL")

  # Geführter Kontext, nie nackt: unter `set -e` beendet ein Rückgabewert
  # ungleich null das Script sofort, und die Prüfung darunter liefe nie.
  local chrome_out code=0
  chrome_out="$(run_with_timeout "$SHOOT_TIMEOUT" "${cmd[@]}" 2>&1)" || code=$?
  if [[ "$code" -eq 124 || "$code" -eq 143 ]]; then
    echo "Fehler: Chrome ist nach ${SHOOT_TIMEOUT}s nicht zurückgekehrt (${device}, ${NAME}, ${URL})." >&2
    echo "Aufnahme abgebrochen, die übrigen Seitentypen laufen weiter." >&2
    rm -f "$out"
    PROBLEMS=$((PROBLEMS + 1))
    return 0
  fi
  if [[ "$code" -ne 0 ]]; then
    echo "Fehler: Chrome-Aufnahme (${device}) fehlgeschlagen für ${NAME} (${URL})." >&2
    echo "$chrome_out" >&2
    PROBLEMS=$((PROBLEMS + 1))
    return 0
  fi

  if grep -q 'main-frame-error' <<<"$chrome_out"; then
    echo "Fehler: ${URL} nicht erreichbar (${device}), Chrome hat seine eigene" >&2
    echo "Fehlerseite fotografiert statt der Zielseite. Bild verworfen." >&2
    rm -f "$out"
    PROBLEMS=$((PROBLEMS + 1))
    return 0
  fi

  # Die Headless Shell von Playwright hat keine solche Fehlerseite. Bei einem
  # Verbindungsfehler beendet sie sich ebenfalls mit Exit 0, schreibt ein leeres
  # Bild und liefert als DOM genau die Zeile unten, gemessen am 15.09.2026 an
  # einem abgewiesenen lokalen Port und an einer fehlenden file://-Datei. Ohne
  # diese Prüfung ginge das leere Bild als Aufnahme der Zielseite durch. Eine
  # ausgelieferte Shop-Seite hat nie Kopf und Körper zugleich leer.
  if grep -qxF '<html><head></head><body></body></html>' <<<"$chrome_out"; then
    echo "Fehler: ${URL} nicht erreichbar oder leer (${device}), der Browser hat eine" >&2
    echo "leere Seite fotografiert statt der Zielseite. Bild verworfen." >&2
    rm -f "$out"
    PROBLEMS=$((PROBLEMS + 1))
    return 0
  fi

  if [[ ! -s "$out" ]]; then
    echo "Fehler: Chrome lief durch, aber unter ${out} liegt kein Bild (${device}, ${NAME})." >&2
    PROBLEMS=$((PROBLEMS + 1))
    return 0
  fi

  local size timestamp
  size="$(wc -c < "$out" | tr -d '[:space:]')"
  timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "OK: ${out} (${size} Bytes, ${device})"
  # Die tatsächliche Breite, nicht die gewünschte: Chrome klemmt bei
  # CHROME_MIN_WIDTH und schneidet das Bild danach auf das gewünschte Maß zu,
  # die Headless Shell klemmt nicht (CHROME_MIN_WIDTH 0). Wer diese beiden
  # Felder liest, kann einen beschnittenen 500er nicht mehr für eine
  # Handy-Ansicht halten.
  local want_w actual_w clamped
  want_w="${window%%,*}"
  if (( want_w < CHROME_MIN_WIDTH )); then
    actual_w="$CHROME_MIN_WIDTH"; clamped=true; CLAMPED_ANY=1
  else
    actual_w="$want_w"; clamped=false
  fi
  ENTRIES+=("$(jq -nc \
    --arg page_type "$NAME" --arg device "$device" --arg timestamp "$timestamp" \
    --arg url "$URL" --arg path "$out" \
    --argjson requested_width "$want_w" --argjson viewport_width "$actual_w" \
    --argjson viewport_clamped "$clamped" \
    '{page_type: $page_type, device: $device, captured_at: $timestamp, source_url: $url,
      path: $path, requested_width: $requested_width, viewport_width: $viewport_width,
      viewport_clamped: $viewport_clamped}')")
}

capture "desktop" "1440,900" ""
capture "mobil" "390,844" "$MOBILE_UA"

if [[ "$CLAMPED_ANY" -eq 1 && "${MOBILE_CLAMP_WARNED:-0}" -eq 0 ]]; then
  echo "Hinweis: die mobile Aufnahme entsteht bei ${CHROME_MIN_WIDTH}px Breite und wird" >&2
  echo "auf 390px beschnitten, headless Chrome klemmt darunter. Das Bild taugt als" >&2
  echo "Inhaltsbeleg, NICHT als Beleg fuer ein mobiles Layout. Siehe Kopf dieses Scripts." >&2
fi

if [[ "${#ENTRIES[@]}" -gt 0 ]]; then
  printf 'IMAGES_JSON: %s\n' "$(printf '%s\n' "${ENTRIES[@]}" | jq -sc '.')"
fi

if [[ "$PROBLEMS" -gt 0 ]]; then
  echo "Fehler: ${PROBLEMS} von 2 Aufnahmen fehlgeschlagen für ${NAME} (${URL})." >&2
fi

exit "$PROBLEMS"
