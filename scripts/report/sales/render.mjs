// Verkaufs-Report aus content.json zu HTML rendern.
//
// Der Report von audit-light ist ein anderes Dokument als der Monats-Report und
// als der Baseline-Report des grossen Audits: er geht an einen Lead, nicht an
// einen Kunden, und er argumentiert (Cover-Hook, Marktlage, Quadrant, Matrix,
// Score-Balken, Triage, Fahrplan) statt zu berichten. Deshalb hat er ein eigenes
// Modul und eine eigene Formatschicht, statt das Skelett des Kunden-Reports zu
// beugen, bis beide halb passen.
//
// Aufgabenteilung: dieses Modul erzeugt HTML, das PDF macht danach
// skills/report/scripts/render_pdf.sh. Beides zu koppeln war im alten Repo die
// Quelle eines eigenen Incidents, weil Chrome nach dem Schreiben der PDF nicht
// beendet hat und der Aufrufer daran haengen blieb.
//
// CLI: node render.mjs <content.json> [out.html]
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { istHauptmodul } from "./is-main.mjs";

import { renderReportHtml } from "./report-pdf-full.mjs";

const isMain = istHauptmodul(import.meta.url);

if (isMain) {
  const [contentPath, outHtml] = process.argv.slice(2);
  if (!contentPath) {
    console.error("Aufruf: node render.mjs <content.json> [out.html]");
    process.exit(1);
  }
  const ziel = outHtml || contentPath.replace(/\.json$/, ".html");

  let data;
  try {
    data = JSON.parse(readFileSync(contentPath, "utf8"));
  } catch (err) {
    console.error(`content.json nicht lesbar: ${err.message}`);
    process.exit(1);
  }

  // Fruehe, klare Meldung statt eines halb gerenderten PDFs: der Renderer greift
  // auf diese vier Felder ohne Fallback zu.
  const fehlt = ["shop", "exec", "chapters", "fahrplan"].filter((k) => !data[k]);
  if (fehlt.length) {
    console.error(`content.json unvollstaendig, es fehlt: ${fehlt.join(", ")}`);
    process.exit(1);
  }

  mkdirSync(dirname(resolve(ziel)), { recursive: true });
  writeFileSync(ziel, renderReportHtml(data));
  console.log(`HTML -> ${ziel}`);
  console.log(`PDF:   bash "$CLAUDE_PLUGIN_ROOT/skills/report/scripts/render_pdf.sh" "${ziel}" "${ziel.replace(/\.html$/, ".pdf")}"`);
}
