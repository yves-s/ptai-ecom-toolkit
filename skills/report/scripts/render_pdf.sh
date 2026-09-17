#!/usr/bin/env bash
# render_pdf.sh: rendert eine HTML-Datei headless nach PDF (A4), mit dem
# Browser aus scripts/lib/find_chrome.sh (bevorzugt die Headless Shell von
# Playwright, sonst Google Chrome oder Chromium).
# Aufruf: render_pdf.sh <html-datei> <pdf-out>
# Teil des Plugins ptai-ecom (Skill report). Bash 3.2-kompatibel.

set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Aufruf: $(basename "$0") <html-datei> <pdf-out>" >&2
  exit 1
fi

HTML_IN="$1"
PDF_OUT="$2"

if [ ! -f "$HTML_IN" ]; then
  echo "Fehler: HTML-Datei nicht gefunden: ${HTML_IN}" >&2
  exit 1
fi

# Pfade absolut machen: Chrome arbeitet nicht im Aufrufer-Verzeichnis.
abs_path() {
  case "$1" in
    /*) printf '%s' "$1" ;;
    *)  printf '%s/%s' "$(pwd)" "$1" ;;
  esac
}

HTML_ABS="$(abs_path "$HTML_IN")"
PDF_ABS="$(abs_path "$PDF_OUT")"

mkdir -p "$(dirname "$PDF_ABS")"

# Browser finden: eine Suche für alle drei Aufrufer, scripts/lib/find_chrome.sh.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${SCRIPT_DIR}/../../../scripts/lib/find_chrome.sh"

if ! CHROME="$(find_chrome)"; then
  echo "Fehler: weder die Headless Shell von Playwright noch Google Chrome oder Chromium gefunden." >&2
  echo "Das PDF-Rendering braucht eins davon. Installieren: ${BROWSER_INSTALL_HINT}, dann erneut ausführen." >&2
  exit 1
fi

# Render. --virtual-time-budget gibt Fonts und Layout Zeit, bevor gedruckt wird.
if ! CHROME_OUT="$("$CHROME" \
  --headless \
  --disable-gpu \
  --no-pdf-header-footer \
  --virtual-time-budget=10000 \
  --print-to-pdf="$PDF_ABS" \
  "$HTML_ABS" 2>&1)"; then
  echo "Fehler: Render mit $(browser_name "$CHROME") fehlgeschlagen (${CHROME})." >&2
  echo "$CHROME_OUT" >&2
  exit 1
fi

if [ ! -s "$PDF_ABS" ]; then
  echo "Fehler: $(browser_name "$CHROME") lief durch, aber unter ${PDF_ABS} liegt kein PDF." >&2
  exit 1
fi

# Grober Font-Proxy: unter 20 KB sind die Fonts sicher nicht eingebettet
# (ein leeres A4 mit Systemfonts bleibt darunter).
SIZE="$(wc -c < "$PDF_ABS" | tr -d '[:space:]')"
if [ "$SIZE" -le 20480 ]; then
  echo "Fehler: PDF ist nur ${SIZE} Bytes (unter 20 KB), vermutlich ohne Fonts" >&2
  echo "oder CSS gerendert. Sind __CSS_PATH__ und __LOGO_PATH__ im HTML durch" >&2
  echo "absolute Pfade ersetzt?" >&2
  exit 1
fi

echo "OK: PDF geschrieben: ${PDF_ABS} (${SIZE} Bytes)"
