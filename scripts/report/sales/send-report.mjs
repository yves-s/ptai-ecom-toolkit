// Send the report teaser email with the PDF attached, then mark the audit sent.
// CLI: node --env-file=.env.local engine/send-report.mjs <audit-id> <content.json> [pdf-path]
//
// Jeder Schlüssel, der in der Umgebung fehlt, kommt einzeln aus der zentralen
// Betreiber-.env, wie bei scripts/audit/env.py. Bis 11.09.2026 las der Lader
// die Datei nur, wenn einer der drei Funnel-Schlüssel fehlte; standen die in
// der Umgebung, fielen die Absenderangaben aus der zentralen Datei still weg.
// Ein leeres PTAI_ENV_FILE heißt "keine zentrale Datei" (`??`, nicht `||`), wie
// in env.py und check_env.sh. db.mjs hat einen eigenen Lader mit denselben
// Regeln: es läuft als Import vor diesem Code und liest die Supabase-Schlüssel
// schon beim Laden.
import { readFileSync as _readEnv } from "node:fs";
import { homedir as _home } from "node:os";
import { join as _join } from "node:path";
const _KEYS = ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "RESEND_API_KEY",
               "PTAI_MAIL_FROM", "PTAI_MAIL_REPLY_TO"];
if (_KEYS.some((k) => !process.env[k])) {
  const _central = {};
  try {
    const _t = _readEnv(process.env.PTAI_ENV_FILE ?? _join(_home(), ".config", "ptai-ecom", ".env"), "utf8");
    for (const _z of _t.split("\n")) {
      const _m = _z.match(/^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$/);
      // Umschließende Quotes weg, ein leerer Wert zählt nicht, der letzte
      // gewinnt: dieselben Regeln wie env.parse_env().
      const _v = _m ? _m[2].replace(/^(["'])(.*)\1$/, "$2") : "";
      if (_v) _central[_m[1]] = _v;
    }
  } catch { /* keine zentrale Datei, dann bleibt es bei der Umgebung */ }
  for (const _k of _KEYS) if (!process.env[_k] && _central[_k]) process.env[_k] = _central[_k];
}

import { renderTeaserEmail } from "./report-email.mjs";
import { getAudit, updateAudit } from "./db.mjs";
import { readFileSync } from "node:fs";

const [, , auditId, contentPath, pdfPath = "/tmp/report.pdf"] = process.argv;
if (!auditId || !contentPath) { console.error("usage: node --env-file=.env.local engine/send-report.mjs <audit-id> <content.json> [pdf-path]"); process.exit(1); }

// Absender und Antwortadresse haben keine Vorgabe (Spec 2026-09-11, D6). Eine
// Vorgabe auf Yves' Adresse leitete Antworten auf die Leads eines fremden
// Betreibers still an Yves. Geprüft wird vor dem ersten Aufruf nach außen.
const from = process.env.PTAI_MAIL_FROM;
const replyTo = process.env.PTAI_MAIL_REPLY_TO;
const missing = [["PTAI_MAIL_FROM", from], ["PTAI_MAIL_REPLY_TO", replyTo]]
  .filter(([, value]) => !value).map(([name]) => name);
if (missing.length) {
  console.error(`Versand abgebrochen: ${missing.join(" und ")} ${missing.length > 1 ? "fehlen" : "fehlt"}. `
    + "Eintragen in ~/.config/ptai-ecom/.env oder in die Umgebung: der Absender im Format "
    + "\"Name <adresse>\", bei Resend verifiziert, dazu die Adresse für Antworten. "
    + "Es ist nichts rausgegangen.");
  process.exit(1);
}

const audit = await getAudit(auditId);
if (!audit) { console.error("audit not found:", auditId); process.exit(1); }
const data = JSON.parse(readFileSync(contentPath, "utf8"));
const pdf = readFileSync(pdfPath);
const slug = String(data.shop || audit.shop_url).replace(/^https?:\/\//, "").replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "");

const res = await fetch("https://api.resend.com/emails", {
  method: "POST",
  headers: { Authorization: `Bearer ${process.env.RESEND_API_KEY}`, "Content-Type": "application/json" },
  body: JSON.stringify({
    from,
    to: audit.email,
    reply_to: replyTo,
    subject: `Dein E-Commerce-Audit für ${data.shop} ist da`,
    html: renderTeaserEmail(data),
    attachments: [{ filename: `Path-to-AI_E-Commerce-Audit_${slug}.pdf`, content: pdf.toString("base64") }],
  }),
});
if (!res.ok) { console.error("send failed", res.status, await res.text()); process.exit(1); }

await updateAudit(auditId, { status: "sent", sent_at: new Date().toISOString() });
console.log("✓ Report gesendet an", audit.email, "· status=sent");
