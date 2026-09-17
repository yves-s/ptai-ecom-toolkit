// Report teaser email (Node, command-side). Branded shell + score snapshot +
// a few findings + "full report attached (PDF)" + soft CTA + bio sign-off.
// CI nach dem Styleguide von Path to AI: die Wortmarke wird gesetzt (Typo, kein Bild). Mail-Clients
// laden kein Archivo, deshalb Arial Black als Fallback für die Display-Schnitte.
const DISP = "'Archivo','Arial Black',Arial,sans-serif";
const CAL = "https://cal.com/path-to-ai/30min";
export const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export function renderTeaserEmail(d) {
  const host = d.shop;
  const scores = d.exec?.scores || d.scores || [];
  const teaser = d.exec?.teaserFindings || (d.befunde?.items || []).slice(0, 3);
  const snapshot = scores.map((s) => `
    <td style="padding:0 6px;" width="33%">
      <div style="background:#E6ECFA;padding:14px 12px;text-align:center;">
        <div style="font:900 30px ${DISP};letter-spacing:-.02em;color:#1F3F8F;line-height:1;">${s.score}<span style="font:400 13px Arial,sans-serif;color:#5A5E57;">/100</span></div>
        <div style="font:400 9.5px Arial,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:#5A5E57;margin-top:7px;">${esc(s.short || s.label)}</div>
      </div>
    </td>`).join("");
  const findings = teaser.map((f) => `
    <tr><td style="padding:11px 0;border-bottom:1px solid #ECECE9;">
      <div style="font:700 15px Arial,sans-serif;color:#14150F;">${esc(f.title)}</div>
      <div style="font:400 13px/1.5 Arial,sans-serif;color:#3C3D37;margin-top:3px;">${esc(f.body || f.wirkung)}</div>
    </td></tr>`).join("");
  return `<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F5F5F2;-webkit-font-smoothing:antialiased;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">Dein E-Commerce-Audit für ${esc(host)} ist fertig, der vollständige Report liegt als PDF im Anhang.</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F5F5F2;"><tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#FFFFFF;border:1px solid #E4E4E1;">
  <tr><td style="padding:26px 30px 18px;border-bottom:1px solid #ECECE9;"><div style="font:italic 900 20px ${DISP};letter-spacing:-.015em;text-transform:uppercase;color:#14150F;">Path to AI<span style="color:#E2381B;">.</span></div></td></tr>
  <tr><td style="padding:26px 30px 0;">
    <div style="font:11px Arial,sans-serif;letter-spacing:.14em;text-transform:uppercase;color:#1F3F8F;">E-Commerce-Audit · Report</div>
    <div style="font:italic 900 26px/1.1 ${DISP};letter-spacing:-.02em;color:#14150F;margin-top:10px;">Dein Audit für ${esc(host)} ist da.</div>
    <div style="font:400 15px/1.65 Arial,sans-serif;color:#3C3D37;margin-top:12px;">Ich habe deinen Shop in drei Bereichen geprüft: Akquisition, Conversion Rate Optimierung sowie Trust und Compliance. Hier der Überblick; der <strong style="color:#14150F;">vollständige Report liegt als PDF im Anhang</strong>.</div>
  </td></tr>
  <tr><td style="padding:20px 24px 0;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>${snapshot}</tr></table></td></tr>
  <tr><td style="padding:24px 30px 0;">
    <div style="font:600 13px Arial,sans-serif;letter-spacing:.04em;text-transform:uppercase;color:#1F3F8F;">Drei Punkte aus dem Report</div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:6px;">${findings}</table>
  </td></tr>
  <tr><td style="padding:18px 30px 0;">
    <div style="background:#E6ECFA;padding:14px 18px;font:400 13px/1.6 Arial,sans-serif;color:#3C3D37;">
      Im Anhang: der vollständige <strong style="color:#14150F;">Report</strong> als PDF, alle Befunde mit Empfehlungen, Score-Überblick, Wettbewerb und ein Fahrplan.
    </div>
  </td></tr>
  <tr><td style="padding:26px 30px 4px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#14150F;"><tr><td style="padding:26px;">
      <div style="font:italic 900 22px ${DISP};letter-spacing:-.02em;color:#FFFFFF;">Den nächsten Schritt machen<span style="color:#E2381B;">.</span></div>
      <div style="font:400 14px/1.6 Arial,sans-serif;color:#C7C8C3;margin-top:8px;">Ich unterstütze E-Com-Brands dabei, mit AI zu skalieren: von SEO und GEO über SEA bis zur Shop- und Conversion-Optimierung. Wenn das für euch spannend ist, lass uns sprechen.</div>
      <table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:16px;"><tr><td style="background:#C62F14;"><a href="${CAL}" style="display:inline-block;padding:13px 26px;font:600 14px Arial,sans-serif;color:#FFFFFF;text-decoration:none;">Termin vereinbaren →</a></td></tr></table>
    </td></tr></table>
  </td></tr>
  <tr><td style="padding:24px 30px 0;">
    <div style="border-top:1px solid #ECECE9;padding-top:20px;font:400 13.5px/1.7 Arial,sans-serif;color:#5A5E57;">
      <strong style="color:#14150F;">Ich bin Yves.</strong> Fast 15 Jahre E-Commerce: ABOUT YOU, danach acht Jahre Aufbau von Lyska, meiner eigenen E-Commerce-Software-Beratung, zuletzt Tech und E-Commerce bei KarlvonDrais und Tech Lead Operations bei Liebscher &amp; Bracht. Mit Path to AI unterstütze ich E-Com-Brands dabei, mit AI zu skalieren. Konkret setze ich AI ein, um ihre Sichtbarkeit in Google und AI-Suchen zu verbessern, SEA-Kampagnen effizienter zu machen und Shops so zu optimieren, dass mehr Besucher zu Kunden werden. Auf <a href="https://www.linkedin.com/in/yves-schleich/" style="color:#C62F14;font-weight:600;">LinkedIn</a> schreibe ich über AI im E-Commerce aus operativer Sicht.
    </div>
  </td></tr>
  <tr><td style="padding:22px 30px 28px;font:400 12px/1.6 Arial,sans-serif;color:#8A8D85;">
    Path to AI · Yves Schleich · <a href="https://www.path-to-ai.com" style="color:#1F3F8F;">path-to-ai.com</a> · <a href="https://www.path-to-ai.com/datenschutz/" style="color:#8A8D85;">Datenschutz</a>
  </td></tr>
</table>
</td></tr></table>
</body></html>`;
}
