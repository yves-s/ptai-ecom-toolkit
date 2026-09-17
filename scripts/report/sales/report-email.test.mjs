import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { renderTeaserEmail, esc } from './report-email.mjs';   // esc importieren: Titel werden escaped

const data = JSON.parse(readFileSync(new URL('./report-content.sample.full.json', import.meta.url)));
const html = renderTeaserEmail(data);

test('Teaser liest Scores aus exec.scores (short-Labels)', () => {
  for (const s of data.exec.scores) assert.ok(html.includes(s.short), `Score-Short fehlt: ${s.short}`); // short ('SEO'/'E-Com'/'GEO') ist escape-frei
});

test('Teaser zeigt genau die 3 exec.teaserFindings', () => {
  assert.equal(data.exec.teaserFindings.length, 3);
  // f.title wird im Mail-Renderer escaped ('Title & Meta…' → 'Title &amp; Meta…') → gegen esc(...) matchen
  for (const f of data.exec.teaserFindings) assert.ok(html.includes(esc(f.title)), `Teaser-Befund fehlt: ${f.title}`);
});
