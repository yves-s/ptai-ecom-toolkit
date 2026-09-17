// Läuft diese Datei als Kommandozeilen-Programm oder wurde sie importiert?
//
// Die naheliegende Prüfung `import.meta.url === pathToFileURL(resolve(argv[1]))`
// ist falsch, sobald das Skript über einen Symlink aufgerufen wird. Node löst
// für `import.meta.url` den echten Pfad auf, `argv[1]` bleibt der Pfad, den der
// Aufrufer getippt hat. Beide sind dann verschieden, der Vergleich schlägt fehl,
// und das Programm beendet sich still mit Code 0 ohne eine Zeile Ausgabe.
//
// Genau das ist der Normalfall: das Plugin liegt in
// ~/.claude/skills/ptai-ecom, das ein Symlink ins Entwicklungs-Repo ist, und
// beide SKILL.md rufen die Skripte über diesen Pfad auf. Am 07.09.2026 hat
// `db.mjs get <audit-id>` deshalb nichts ausgegeben.
import { realpathSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

/** @param {string} metaUrl `import.meta.url` der aufrufenden Datei. */
export function istHauptmodul(metaUrl) {
  if (!process.argv[1]) return false;
  let pfad;
  try {
    pfad = realpathSync(process.argv[1]);
  } catch {
    pfad = resolve(process.argv[1]); // gelöschtes oder virtuelles Argument
  }
  return metaUrl === pathToFileURL(pfad).href;
}
