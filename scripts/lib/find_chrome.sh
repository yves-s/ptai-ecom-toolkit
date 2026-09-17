#!/usr/bin/env bash
# find_chrome.sh: sucht den Browser, der PDFs rendert und Screenshots aufnimmt.
#
# Aufruf, per source relativ zum eigenen Script:
#   . "<plugin-root>/scripts/lib/find_chrome.sh"
#   if ! CHROME="$(find_chrome)"; then
#     echo "Installieren: ${BROWSER_INSTALL_HINT}" >&2
#   fi
#
# Eingebunden von skills/report/scripts/render_pdf.sh,
# skills/capture-screens/scripts/shoot.sh und scripts/check_env.sh. Die
# Kandidaten stehen nur hier; bis 15.09.2026 trug jedes der drei Scripts eine
# eigene Kopie.
#
# Reihenfolge:
#   1. die Headless Shell von Playwright mit der höchsten Versionsnummer
#   2. Google Chrome und Chromium, in derselben Reihenfolge wie vorher
#
# Warum die Shell vorne steht: ein headless gestartetes Google Chrome öffnet
# auf macOS den Dialog "Schlüsselbund nicht gefunden" und hängt, bis jemand
# klickt, und nach einem Screenshot beendet es sich oft nicht, weil der
# Google-Updater startet. Die Shell braucht keinen Schlüsselbund, beendet sich
# sauber und klemmt schmale Fenster nicht auf 500 Pixel (siehe shoot.sh). Wer
# nur Chrome oder Chromium hat, rendert weiter damit.
#
# Setzt bewusst keine Shell-Optionen: die Aufrufer laufen unter
# set -euo pipefail, und das bleibt, wie es ist. Bash 3.2, nur Builtins.

# Was ein Aufrufer nennt, wenn nichts gefunden wurde.
BROWSER_INSTALL_HINT="bevorzugt die Headless Shell von Playwright (npx playwright install chromium-headless-shell), sonst Google Chrome oder Chromium"

# Die Headless Shell mit der höchsten Nummer über alle Ablagen und Plattformen.
# Playwright legt je Version einen Ordner chromium_headless_shell-<nummer> an,
# und alte Versionen bleiben nach einem Update liegen. Verglichen wird als Zahl,
# als Text stünde 999 hinter 1000. Ein Ordner ohne ausführbare Datei ist ein
# abgebrochener Download und zählt nicht.
#
# Die Ablagen: PLAYWRIGHT_BROWSERS_PATH, wenn gesetzt, dann die Vorgabe von
# Playwright auf macOS und auf Linux.
find_headless_shell() {
  local root dir number platform candidate best="" best_number=-1
  for root in \
    "${PLAYWRIGHT_BROWSERS_PATH:-}" \
    "${HOME}/Library/Caches/ms-playwright" \
    "${HOME}/.cache/ms-playwright"
  do
    if [ -z "$root" ] || [ ! -d "$root" ]; then
      continue
    fi
    for dir in "$root"/chromium_headless_shell-*; do
      number="${dir##*/chromium_headless_shell-}"
      # Ohne Treffer bleibt das Muster selbst stehen, und "*" ist keine Zahl.
      case "$number" in
        ''|*[!0-9]*) continue ;;
      esac
      for platform in mac-arm64 mac-x64 linux64; do
        candidate="${dir}/chrome-headless-shell-${platform}/chrome-headless-shell"
        if [ -f "$candidate" ] && [ -x "$candidate" ]; then
          if [ "$number" -gt "$best_number" ]; then
            best="$candidate"
            best_number="$number"
          fi
          break
        fi
      done
    done
  done
  if [ -z "$best" ]; then
    return 1
  fi
  printf '%s' "$best"
}

# Pfad des Browsers auf stdout, Exit 1 ohne Fund.
#
# Nur für Tests: FIND_CHROME_SYSTEM_ROOT verschiebt die festen Kandidaten unter
# /Applications in ein Wegwerf-Verzeichnis, damit ein Chrome des Rechners nicht
# mitspielt. Im Betrieb nie setzen.
find_chrome() {
  local c system_root="${FIND_CHROME_SYSTEM_ROOT:-}"
  if find_headless_shell; then
    return 0
  fi
  for c in \
    "${system_root}/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "${HOME}/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "${system_root}/Applications/Chromium.app/Contents/MacOS/Chromium"
  do
    if [ -x "$c" ]; then
      printf '%s' "$c"
      return 0
    fi
  done
  for c in google-chrome chromium chromium-browser; do
    if command -v "$c" >/dev/null 2>&1; then
      printf '%s' "$(command -v "$c")"
      return 0
    fi
  done
  return 1
}

# Ob ein Fund die Headless Shell ist. shoot.sh hängt die Fensterklemme daran.
is_headless_shell() {
  case "$1" in
    */chrome-headless-shell) return 0 ;;
  esac
  return 1
}

# Name eines Funds für Meldungen.
browser_name() {
  case "$1" in
    */chrome-headless-shell) printf 'Headless Shell von Playwright' ;;
    */Chromium|*/chromium|*/chromium-browser) printf 'Chromium' ;;
    *) printf 'Google Chrome' ;;
  esac
}
