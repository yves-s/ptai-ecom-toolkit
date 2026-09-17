#!/usr/bin/env bash
# Alle Tests des Plugins. Aufruf aus dem Repo-Root oder von überall:
#   scripts/run_tests.sh
#
# Drei Suiten nacheinander, jede mit den Bordmitteln ihrer Sprache:
#   Python      scripts/tests, unittest aus der Standardbibliothek
#   JavaScript  scripts/report/sales/*.test.mjs mit node --test; ohne node
#               eine Zeile "JS-Tests übersprungen (node fehlt)"
#   Release     release/tests, nur wenn es das Verzeichnis gibt
# Keine Suite hält die nächste an. Exit-Code: Zahl der gescheiterten Suiten.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
FAILED=0

cd "${SCRIPT_DIR}"
python3 -m unittest discover -s tests -t . -v || FAILED=$((FAILED + 1))

if command -v node >/dev/null 2>&1; then
  node --test report/sales/*.test.mjs || FAILED=$((FAILED + 1))
else
  echo "JS-Tests übersprungen (node fehlt)"
fi

if [[ -d "${REPO_ROOT}/release/tests" ]]; then
  (cd "${REPO_ROOT}" && python3 -m unittest discover -s release/tests -t . -v) || FAILED=$((FAILED + 1))
fi

exit "$FAILED"
