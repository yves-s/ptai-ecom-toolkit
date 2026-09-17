# CLAUDE.md, ptai-ecom

Claude-Code-Plugin für E-Commerce-Audits und Reporting bei Shopify-Shops. Diese
Datei hält die Konventionen für jede Sitzung, die am Plugin arbeitet. Was das
Plugin tut und wie es eingerichtet wird, steht in `README.md`.

## Einstieg

| Datei | Wofür |
|---|---|
| `README.md` | Skills, Voraussetzungen, Setup in zwei Teilen, Einstufung der Quellen |
| `skills/audit/SKILL.md` | wie ein Audit abläuft: Phasen, Gates, Wiederaufnahme, ein Schreiber für den Zustand |
| `reference/metrics.md` | Formeln, Schwellen und Benchmarks, die einzige Quelle dafür |
| `reference/access.md` | welche Zugänge der Betreiber einmal braucht (Teil A) und welche der Kunde freigibt (Teil B) |
| `scripts/audit/tiers.py` | welche Quelle Pflicht, empfohlen oder optional ist |

## Sprache

**Alles Technische ist Englisch.** Bezeichner, Funktions- und Variablennamen,
CLI-Flags, JSON-Feldnamen, Dateinamen, Branch-Namen und Commit-Botschaften. Das
gilt auch für Shell-Funktionen, für Variablen in den Codebeispielen der Skills
und für Pfadsegmente. Ein halb deutscher Bezeichnersatz bleibt für immer
inkonsistent.

**Deutsch sind Docstrings, Kommentare und alles, was ein Kunde liest**: `SKILL.md`,
Reports und die erzeugten Markdown-Dateien. Dort echte Umlaute (ä ö ü ß) und
keine Gedankenstriche. Der Inhalt einer Datei darf deutsch sein, ihr Name und
ihre Schlüssel nicht.

## Code

- Python 3.10 oder neuer, **nur Standardbibliothek**, dazu `google-auth` für die
  Google-APIs. Kein `requests` im eigenen Code, kein `beautifulsoup4`, kein
  `lxml`, kein pytest.
- Shell: `#!/usr/bin/env bash`, deutscher Kommentarblock mit dem Aufruf, dann
  `set -euo pipefail`, lauffähig mit bash 3.2. Kein einzelner Fehlschlag bricht
  ein Skript ab: jeder wird zur Fehlerzeile plus Zähler, der Exit-Code ist die
  Zahl der Probleme. Muster: `scripts/check_env.sh`.
- Pfade in Skills laufen über `${CLAUDE_PLUGIN_ROOT}`, nie absolut.
- Jeder Pull ist isoliert: ein Fehler markiert die Quelle als nicht verfügbar,
  samt Grund, und legt nie den ganzen Lauf.
- Ein Schlüssel geht nie als Argument oder in einer URL an ein anderes Programm,
  sonst steht er in der Prozessliste. `psi_pull.sh` gibt den PageSpeed-Key als
  Header über stdin an `curl`.

## Prüfmaßstab

Die Frage bei jeder Änderung lautet: **erzeugt das eine falsche oder fehlende
Zahl?** Ein Absturz ist sichtbar und schnell behoben, eine falsche Zahl in einem
Kundenreport fällt niemandem auf. Härtung gegen ungewöhnliche Eingaben ist kein
Selbstzweck.

## Tests

- `bash scripts/run_tests.sh` startet die Python-Suite (`scripts/tests`,
  `unittest`) und die JavaScript-Suite (`node --test`). Kein Test geht ins Netz.
- Tests mit Kundenordnern oder Schlüsseln lenken `PTAI_ACCOUNTS_ROOT`, `HOME` und
  die zentrale Datei über `scripts/tests/support.py` in einen Temp-Ordner um.
  Kein Test liest die echte `~/.config/ptai-ecom/.env`.
- Neuer Code kommt mit einem Test, der vorher rot war.

## Kundendaten

Keine Kundennamen, keine echten Shop-Zahlen, keine einem Kunden zugeordneten
Tool-Stacks und keine Namen von Mitarbeitern in Code, Kommentaren, Tests oder
Commit-Botschaften. Beispieldaten heißen `beispielshop`, Domains enden auf
`.example`. `scripts/tests/test_no_customer_data.py` prüft Store-Domains und
GA4-Property-Nummern nach ihrer Form.

## Git

- Jeder Commit staged seine Dateien namentlich, nie `git add -A`, `git add .`
  oder `git commit -a`.
- Kein `git stash`, `git checkout`, `git reset` oder `git clean` über
  uncommittete Arbeit, die nicht die eigene ist.
- `.env`, `secrets/` und Schlüsseldateien nie committen.
