// Fehlt einer der beiden Supabase-Schlüssel in der Umgebung, kommt er aus der
// zentralen Betreiber-.env. Ohne das müsste jeder Aufruf ein --env-file
// mitschleppen. Gesetzt werden nur diese beiden, nie der Rest der Datei;
// send-report.mjs liest seine Schlüssel selbst.
//
// Dieselben Regeln wie scripts/audit/env.py und der Lader in send-report.mjs:
// umschließende Quotes weg, ein leerer Wert zählt nicht, bei doppeltem
// Schlüssel gewinnt der letzte. Ein leeres PTAI_ENV_FILE heißt "keine zentrale
// Datei" (`??`, nicht `||`), wie in env.py und scripts/check_env.sh. Bis
// 11.09.2026 gewann hier der erste Wert. Weil ES-Importe vor dem Code des
// importierenden Moduls laufen, galt beim Versand diese Regel und nicht die
// von send-report.mjs.
import { readFileSync as _readEnv } from "node:fs";
import { homedir as _home } from "node:os";
import { join as _join } from "node:path";
const _KEYS = ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"];
if (_KEYS.some((k) => !process.env[k])) {
  const _central = {};
  try {
    const _t = _readEnv(process.env.PTAI_ENV_FILE ?? _join(_home(), ".config", "ptai-ecom", ".env"), "utf8");
    for (const _z of _t.split("\n")) {
      const _m = _z.match(/^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$/);
      const _v = _m ? _m[2].replace(/^(["'])(.*)\1$/, "$2") : "";
      if (_v) _central[_m[1]] = _v;
    }
  } catch { /* keine zentrale Datei, dann bleibt es bei der Umgebung */ }
  for (const _k of _KEYS) if (!process.env[_k] && _central[_k]) process.env[_k] = _central[_k];
}

const URL_ = process.env.SUPABASE_URL;
const KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;
const H = { apikey: KEY, Authorization: `Bearer ${KEY}`, "Content-Type": "application/json" };
const base = `${URL_}/rest/v1`;

const FCOLS = ["pillar","severity","title","detail","recommendation","evidence","skill_source","confidence","impact","effort"];

export async function getAudit(id) {
  const r = await fetch(`${base}/audits?id=eq.${id}&select=*`, { headers: H });
  return (await r.json())[0];
}
export async function updateAudit(id, fields) {
  const r = await fetch(`${base}/audits?id=eq.${id}`, { method: "PATCH", headers: { ...H, Prefer: "return=minimal" }, body: JSON.stringify(fields) });
  if (!r.ok) throw new Error(`updateAudit ${r.status}: ${await r.text()}`);
}
export async function saveFindings(auditId, findings) {
  // uniform key set across all rows (PostgREST PGRST102 guard)
  const rows = findings.map((f, i) => {
    const row = { audit_id: auditId, position: i };
    for (const c of FCOLS) row[c] = f[c] ?? null;
    return row;
  });
  const r = await fetch(`${base}/findings`, { method: "POST", headers: { ...H, Prefer: "return=minimal" }, body: JSON.stringify(rows) });
  if (!r.ok) throw new Error(`saveFindings ${r.status}: ${await r.text()}`);
}

// CLI: node --env-file=.env.local engine/db.mjs get <id> | save <id> <findings.json> | status <id> <status> [score]
// Main-module guard: importers (send-report.mjs) must not trigger CLI dispatch on their argv.
const { istHauptmodul } = await import("./is-main.mjs");
const isMain = istHauptmodul(import.meta.url);
const [,, cmd, ...a] = process.argv;
if (isMain && cmd) {
  if (cmd === "get") console.log(JSON.stringify(await getAudit(a[0]), null, 2));
  else if (cmd === "save") { const fs = await import("node:fs"); await saveFindings(a[0], JSON.parse(fs.readFileSync(a[1], "utf8"))); console.log("ok"); }
  else if (cmd === "status") { await updateAudit(a[0], { status: a[1], ...(a[2] ? { score: Number(a[2]) } : {}), ...(a[1] === "sent" ? { sent_at: new Date().toISOString() } : {}) }); console.log("ok"); }
  else { console.error("unknown cmd:", cmd); process.exit(1); }
}
