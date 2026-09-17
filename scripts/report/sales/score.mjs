// Deterministische, verteidigbare Säulen- und Gesamtscores aus den gegateten Befunden.
//
// INPUT: das flache `findings.json`, also alle Befunde nach dem Beleg-Gate, jeder
// mit `lens`, `severity` und `confidence`. Nicht die Kapitel-Dateien, die
// verlieren die Confidence.
//
// Zwei Dinge unterscheiden diese Fassung von der aus dem alten Repo. Erstens die
// Säulen: dort waren es SEO, E-Com und GEO mit 0,4/0,3/0,3, also 70 Prozent
// Suche. Ein E-Commerce-Audit, dessen Kopfzahl zu zwei Dritteln aus Suche
// besteht, misst am Geschäft vorbei. Zweitens die Abdeckung: die Engine rechnet
// 100 minus Strafpunkte, bis zum 11.09.2026 gedeckelt bei 92. Eine Linse, die nichts
// findet, weil sie geblockt wurde, erzeugte damit denselben Höchstwert wie ein
// wirklich guter Shop.
// Jetzt bekommt eine Säule ohne Abdeckung keinen Score, sondern `null`.
//
// CLI: node score.mjs <findings.json> [coverage-verzeichnis]

//: Linse zu Säule. Eine Linse speist genau eine Säule; `markt` speist keine,
//: eine Marktposition ist keine Note.
//: Die Bereichsnamen sind die des ausführlichen Audits (scripts/audit/score.py),
//: nicht selbst gebaute. "Gefunden werden", "Kaufen" und "Vertrauen" standen bis zum 11.09.2026 hier.
const SAEULEN = {
  gefunden:  { label: 'AKQUISITION', gewicht: 0.30, linsen: ['auffindbarkeit', 'ki-sichtbarkeit'] },
  kaufen:    { label: 'CONVERSION RATE OPTIMIERUNG', gewicht: 0.45, linsen: ['kaufstrecke', 'sortiment'] },
  vertrauen: { label: 'TRUST UND COMPLIANCE', gewicht: 0.25, linsen: ['vertrauen'] },
};

const SEV_WEIGHT  = { crit: 14, warn: 5, ok: 0 };
const CONF_FACTOR = { high: 1.0, medium: 0.7, low: 0.4 };
// Bis 11.09.2026 lag jedes Ergebnis zwischen FLOOR = 35 und CEIL = 92, übernommen aus
// dem alten ecom-audit-Repo (Commit 123c977, 27.06.2026), ohne Begründung im Code.
// Report und Mail zeigen den Wert aber als "/100". Eine Säule ohne Befund kam so nie
// über 92, eine schwache nie unter 35, und drei Light-Reports vom September 2026
// lagen genau auf dem Boden. MIN und MAX sind jetzt nur noch die Skala:
// die Strafe erreicht rechnerisch höchstens rund 92 Punkte (70 für beliebig viele
// crits, rund 22 für die zehn schwersten warns), eine Säule fällt also nie unter 8.
const MIN = 0, MAX = 100;

// Abnehmender Ertrag plus Warn-Deckel: eine gründlich geprüfte Säule soll nicht
// allein durch die MENGE der Warnungen gegen den Boden laufen. Crits zählen alle,
// die sind selten und schwer. Von den Warnungen zählen die schwersten zehn, sonst
// misst der Score die Prüftiefe statt die Shop-Qualität.
//
// Bis 09.09.2026 lag WARN_DIM bei 0,55 und WARN_CAP bei 5, unverändert aus dem
// alten ecom-audit-Repo übernommen (ein einziger Commit, 27.06.2026, nie an
// dieser Stelle geprüft). Das ergab einen harten Fall: eine Säule ganz ohne
// crit-Befund lag praktisch immer bei 88 bis 92, egal ob 5 oder 20 echte
// warn-Befunde vorlagen, weil ab dem sechsten Rang nichts mehr zählte und
// selbst die ersten fünf steil gegen null abklangen (max. Strafe ≈ 10,5 Punkte).
// Belegt an zwei realen Läufen: ein Shop mit 0 crit und 7 warn in der Saeule
// Kaufen ergab 90, ein anderer mit 0 crit und 9 warn in Vertrauen 89. WARN_DIM auf CRIT_DIM angehoben (dieselbe
// Abklingkurve für beide Schweregrade, nur das Gewicht bleibt niedriger) und
// WARN_CAP auf 10 verdoppelt, weil reale Säulen üblich 7 bis 19 warns tragen
// und der alte Deckel bei 5 in fast jedem Lauf sofort griff.
const CRIT_DIM = 0.8, WARN_DIM = 0.8, WARN_CAP = 10;

function saeuleVon(finding) {
  const linse = String(finding?.lens || '').trim().toLowerCase();
  for (const [key, s] of Object.entries(SAEULEN)) if (s.linsen.includes(linse)) return key;
  return null;
}

function pillarScore(findings) {
  const crit = [], warn = [];
  for (const f of findings) {
    const gewicht = CONF_FACTOR[f.confidence] ?? 0.7;
    if (f.severity === 'crit') crit.push(gewicht);
    else if (f.severity === 'warn') warn.push(gewicht);
  }
  crit.sort((a, b) => b - a);
  warn.sort((a, b) => b - a);
  let strafe = 0;
  crit.forEach((cf, i) => { strafe += SEV_WEIGHT.crit * cf * Math.pow(CRIT_DIM, i); });
  warn.slice(0, WARN_CAP).forEach((cf, i) => { strafe += SEV_WEIGHT.warn * cf * Math.pow(WARN_DIM, i); });
  return Math.max(MIN, Math.min(MAX, Math.round(100 - strafe)));
}

// Quick Win = crit oder warn auf Tages- statt Wochenskala. Grundlage des Ziels.
function quickWins(findings) {
  return findings.filter((f) =>
    (f.severity === 'crit' || f.severity === 'warn') && !/woche/i.test(String(f.effort || ''))).length;
}
function targetFor(score, findings) {
  if (score === null) return null;
  const gap = Math.min(24, Math.max(8, 8 + quickWins(findings) * 3), MAX - score);
  return Math.min(MAX, score + gap);
}

/** Hat diese Säule genug Abdeckung, um bewertet zu werden?
 *
 * `coverage` ist `{ <linse>: { checked: [...], not_checkable: [...] } }`, exakt
 * die Feldnamen aus dem `L<n>-<lens>.coverage.json`-Vertrag in den Linsen-Skills
 * (audit-light/SKILL.md, lens-purchase-path, lens-trust, lens-assortment). Eine
 * Linse, die keinen einzigen Pflicht-Check ausführen konnte, trägt nichts bei.
 * Konnte KEINE Linse der Säule etwas prüfen, gibt es keinen Score, sondern eine
 * ausgewiesene Lücke. Fehlt die Abdeckungsangabe ganz, wird gewertet: eine alte
 * Datei ohne coverage soll nicht rückwirkend jeden Score löschen.
 */
export function hatAbdeckung(saeule, coverage) {
  const linsen = SAEULEN[saeule].linsen;
  const bekannt = linsen.filter((l) => coverage && coverage[l]);
  if (bekannt.length === 0) return true;
  return bekannt.some((l) => (coverage[l].checked || []).length > 0);
}

export function compositeOf(werte) {
  const gewertet = Object.entries(werte).filter(([, v]) => v !== null);
  if (gewertet.length === 0) return null;
  // Die Gewichte der ausgefallenen Säulen werden auf die verbliebenen verteilt,
  // sonst faellt der Gesamtscore allein dadurch, dass etwas nicht messbar war.
  const summe = gewertet.reduce((acc, [k]) => acc + SAEULEN[k].gewicht, 0);
  return Math.round(gewertet.reduce((acc, [k, v]) => acc + (SAEULEN[k].gewicht / summe) * v, 0));
}

export function computeScores(findings, coverage = null) {
  const liste = Array.isArray(findings) ? findings : [];
  const eimer = {}, scores = {}, targets = {}, luecken = [];

  for (const key of Object.keys(SAEULEN)) {
    eimer[key] = liste.filter((f) => saeuleVon(f) === key);
    if (!hatAbdeckung(key, coverage)) {
      scores[key] = null;
      targets[key] = null;
      luecken.push(key);
    } else {
      scores[key] = pillarScore(eimer[key]);
      targets[key] = targetFor(scores[key], eimer[key]);
    }
  }

  return {
    scores,
    targets,
    composite: compositeOf(scores),
    ohne_score: luecken,
    labels: Object.fromEntries(Object.entries(SAEULEN).map(([k, s]) => [k, s.label])),
    gewichte: Object.fromEntries(Object.entries(SAEULEN).map(([k, s]) => [k, s.gewicht])),
    debug: Object.fromEntries(Object.entries(eimer).map(([k, v]) => [k, {
      befunde: v.length,
      crit: v.filter((f) => f.severity === 'crit').length,
      warn: v.filter((f) => f.severity === 'warn').length,
      ok: v.filter((f) => f.severity === 'ok').length,
    }])),
    ohne_saeule: liste.filter((f) => saeuleVon(f) === null)
      .map((f) => ({ lens: f.lens ?? null, title: f.title })),
  };
}

// ---------- CLI ----------
import { join, basename } from 'node:path';
import { istHauptmodul } from './is-main.mjs';

if (istHauptmodul(import.meta.url)) {
  const { readFileSync, readdirSync, existsSync } = await import('node:fs');
  const [pfad, coverageDir] = process.argv.slice(2);
  if (!pfad) {
    console.error('Aufruf: node score.mjs <findings.json> [coverage-verzeichnis]');
    process.exit(1);
  }
  let coverage = null;
  if (coverageDir && existsSync(coverageDir)) {
    coverage = {};
    for (const datei of readdirSync(coverageDir).filter((d) => d.endsWith('.coverage.json'))) {
      try {
        const inhalt = JSON.parse(readFileSync(join(coverageDir, datei), 'utf8'));
        // L3-kaufstrecke.coverage.json -> kaufstrecke
        const linse = basename(datei, '.coverage.json').replace(/^L\d+-/, '');
        coverage[linse] = inhalt;
      } catch { /* unlesbare Datei zaehlt als keine Angabe */ }
    }
  }
  console.log(JSON.stringify(computeScores(JSON.parse(readFileSync(pfad, 'utf8')), coverage), null, 2));
}
