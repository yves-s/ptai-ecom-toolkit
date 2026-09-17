// Absenderangaben ohne Vorgabe und der Lader der zentralen Datei
// (Spec 2026-09-11, B3 und D6).
//
// Kein Test hier geht ins Netz oder verschickt eine Mail. Die Supabase-URL ist
// absichtlich keine URL: fetch() lehnt sie schon beim Parsen ab, bevor eine
// Verbindung entsteht. Kommt ein Lauf bis zur Datenbank, steht deshalb
// "Failed to parse URL" in stderr, und das ist hier das Zeichen dafür, dass die
// Prüfung davor ihn durchgelassen hat. HOME zeigt in ein eigenes Verzeichnis,
// damit nie die echte ~/.config/ptai-ecom/.env gelesen wird.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const AUDIT_ID = '00000000-0000-0000-0000-000000000000';
const OFFLINE = { SUPABASE_URL: 'kein-url', SUPABASE_SERVICE_ROLE_KEY: 'x', RESEND_API_KEY: 'x' };
const SENDER = 'PTAI_MAIL_FROM="Beispiel <audit@example.com>"\nPTAI_MAIL_REPLY_TO=antwort@example.com\n';
const REACHED_DB = /Failed to parse URL/;

/**
 * Startet ein Skript mit genau dieser Umgebung und nichts sonst.
 * `homeEnv` liegt als zentrale Datei am Standardort unter HOME, `centralEnv`
 * in einer eigenen Datei, auf die PTAI_ENV_FILE zeigt.
 */
function run(script, args, { env = {}, homeEnv = null, centralEnv = null } = {}) {
  const tmp = mkdtempSync(join(tmpdir(), 'send-report-'));
  const home = join(tmp, 'home');
  mkdirSync(join(home, '.config', 'ptai-ecom'), { recursive: true });
  if (homeEnv !== null) writeFileSync(join(home, '.config', 'ptai-ecom', '.env'), homeEnv);
  const vars = { HOME: home, ...env };
  if (centralEnv !== null) {
    vars.PTAI_ENV_FILE = join(tmp, 'central.env');
    writeFileSync(vars.PTAI_ENV_FILE, centralEnv);
  }
  const content = join(tmp, 'content.json');
  writeFileSync(content, JSON.stringify({ shop: 'beispielshop.de' }));
  const result = spawnSync(process.execPath, [join(HERE, script), ...args(content, tmp)],
                           { encoding: 'utf8', env: vars });
  return { status: result.status, stderr: result.stderr };
}

const send = (options) =>
  run('send-report.mjs', (content, tmp) => [AUDIT_ID, content, join(tmp, 'report.pdf')], options);
const db = (options) => run('db.mjs', () => ['get', AUDIT_ID], options);

test('ohne PTAI_MAIL_FROM bricht der Versand vor der Datenbank ab', () => {
  const r = send({ env: { ...OFFLINE, PTAI_ENV_FILE: '', PTAI_MAIL_REPLY_TO: 'antwort@example.com' } });
  assert.equal(r.status, 1);
  assert.match(r.stderr, /Versand abgebrochen: PTAI_MAIL_FROM fehlt/);
  assert.doesNotMatch(r.stderr, REACHED_DB);
});

test('ohne PTAI_MAIL_REPLY_TO ebenso', () => {
  const r = send({ env: { ...OFFLINE, PTAI_ENV_FILE: '', PTAI_MAIL_FROM: 'Beispiel <audit@example.com>' } });
  assert.equal(r.status, 1);
  assert.match(r.stderr, /Versand abgebrochen: PTAI_MAIL_REPLY_TO fehlt/);
  assert.doesNotMatch(r.stderr, REACHED_DB);
});

test('fehlende Absenderangaben kommen einzeln aus der zentralen Datei', () => {
  // Die drei Funnel-Schlüssel stehen in der Umgebung. Bis 11.09.2026 las der
  // Lader die zentrale Datei dann gar nicht, und der Versand bräche hier ab.
  const r = send({ env: OFFLINE, centralEnv: SENDER });
  assert.match(r.stderr, REACHED_DB);
  assert.doesNotMatch(r.stderr, /PTAI_MAIL_/);
});

test('ein leeres PTAI_ENV_FILE heißt keine zentrale Datei, auch beim Versand', () => {
  const r = send({ env: { ...OFFLINE, PTAI_ENV_FILE: '' }, homeEnv: SENDER });
  assert.equal(r.status, 1);
  assert.match(r.stderr, /PTAI_MAIL_FROM/);
});

test('db.mjs liest bei leerem PTAI_ENV_FILE keine zentrale Datei', () => {
  const r = db({ env: { PTAI_ENV_FILE: '' }, homeEnv: 'SUPABASE_URL=aus-der-zentralen-datei\n' });
  assert.doesNotMatch(r.stderr, /aus-der-zentralen-datei/);
  assert.match(r.stderr, /undefined\/rest\/v1/);
});

test('db.mjs liest ohne PTAI_ENV_FILE die Datei am Standardort', () => {
  const r = db({ homeEnv: 'SUPABASE_URL=aus-der-zentralen-datei\n' });
  assert.match(r.stderr, /aus-der-zentralen-datei\/rest\/v1/);
});

test('db.mjs: bei doppeltem Schlüssel gewinnt der letzte Wert, wie env.parse_env()', () => {
  const r = db({ homeEnv: 'SUPABASE_URL=erster-wert\nSUPABASE_URL=letzter-wert\n' });
  assert.match(r.stderr, /letzter-wert\/rest\/v1/);
});
