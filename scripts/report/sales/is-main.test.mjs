// Die drei CLI-Skripte müssen sich auch melden, wenn sie über den Symlink
// ~/.claude/skills/ptai-ecom aufgerufen werden. Genau so steht der Aufruf in
// beiden SKILL.md, und genau so war er bis 07.09.2026 kaputt: stiller Exit 0.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, symlinkSync, realpathSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const HIER = dirname(fileURLToPath(import.meta.url));

//: Ein Symlink auf das Verzeichnis, wie ihn das Plugin in ~/.claude/skills hat.
const VIA_SYMLINK = (() => {
  const tmp = mkdtempSync(join(tmpdir(), 'ismain-'));
  const link = join(tmp, 'sales');
  symlinkSync(HIER, link);
  return link;
})();

/** Startet ein Skript und gibt zurück, was es gesagt hat, egal auf welchem Kanal. */
function starte(verzeichnis, datei, ...args) {
  try {
    return execFileSync('node', [join(verzeichnis, datei), ...args],
                        { encoding: 'utf8', stdio: 'pipe' });
  } catch (e) {
    return `${e.stdout || ''}${e.stderr || ''}`;
  }
}

// score.mjs ohne Argument: die Nutzungszeile. db.mjs mit unbekanntem Befehl:
// die Fehlerzeile. Beide brauchen keine Schlüssel und kein Netz.
for (const [datei, args, erwartet] of [
  ['score.mjs', [], /Aufruf: node score\.mjs/],
  ['render.mjs', [], /content\.json/],
  ['db.mjs', ['quatsch'], /unknown cmd/],
]) {
  test(`${datei} meldet sich über den Symlink genauso wie über den echten Pfad`, () => {
    const echt = starte(realpathSync(HIER), datei, ...args);
    const ueberLink = starte(VIA_SYMLINK, datei, ...args);
    assert.match(echt, erwartet, 'schon über den echten Pfad stumm');
    assert.match(ueberLink, erwartet,
      `${datei} schweigt über den Symlink: der CLI-Zweig hat nicht gegriffen`);
  });
}

test('ein Import löst den CLI-Zweig nicht aus', async () => {
  // send-report.mjs importiert db.mjs. Würde der Zweig dabei greifen, liefe
  // beim Versand ein zweiter Datenbankbefehl auf dem argv des Versenders.
  const aus = starte(VIA_SYMLINK, 'is-main.test.helper.mjs', 'quatsch');
  assert.match(aus, /importiert-ohne-cli/);
  assert.doesNotMatch(aus, /unknown cmd/, 'der CLI-Zweig hat beim Import gegriffen');
});
