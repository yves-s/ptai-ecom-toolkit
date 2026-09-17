import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { renderReportHtml, esc, safeHtml } from './report-pdf-full.mjs';   // esc/safeHtml: Felder werden escaped/sanitisiert

// Die letzte Seite kommt aus den Einstellungen des Betreibers (Entscheidung
// 15.09.2026, zweiter Teil). Die echte zentrale Datei wird nie gelesen: HOME und
// PTAI_ENV_FILE zeigen in einen eigenen Temp-Ordner, und keine der fünf
// Einstellungen steht in der Umgebung. Der Renderer löst sie erst beim Rendern
// auf, deshalb reicht es, das vor dem ersten Aufruf zu setzen. Alle Werte sind
// erfunden.
const SETTINGS = ['PTAI_CLOSING_FILE', 'PTAI_OPERATOR_NAME', 'PTAI_OPERATOR_CONTACT',
                  'PTAI_OPERATOR_EMAIL', 'PTAI_OPERATOR_BOOKING_URL'];
const TMP = mkdtempSync(join(tmpdir(), 'report-pdf-full-'));
const HOME = join(TMP, 'home');
const CENTRAL = join(TMP, 'central.env');
mkdirSync(HOME);
process.env.HOME = HOME;
process.env.PTAI_ENV_FILE = CENTRAL;
for (const name of SETTINGS) delete process.env[name];
process.on('exit', () => rmSync(TMP, { recursive: true, force: true }));

const SAMPLE = new URL('./report-content.sample.full.json', import.meta.url);
const data = JSON.parse(readFileSync(SAMPLE));
const html = renderReportHtml(data);

const FRAGMENT = '<section class="beispiel-abbinder" style="break-before:page;width:210mm;height:297mm">Beispiel-Abbinder</section>\n';
const ORIGIN = 'Erstellt mit ptai-ecom von <a href="https://path-to-ai.com">Path to AI</a>.';
const DISCLAIMER = 'Dieser Audit basiert auf öffentlich zugänglichen Daten';

/** Rendert mit genau dieser zentralen Datei (null: keine) und sammelt die Warnungen. */
function render(central = null, probe = data) {
  rmSync(CENTRAL, { force: true });
  if (central !== null) writeFileSync(CENTRAL, central);
  const warnings = [];
  try {
    return { h: renderReportHtml(probe, { warn: (m) => warnings.push(m) }), warnings };
  } finally {
    rmSync(CENTRAL, { force: true });
  }
}

/** Der neutrale Schluss als Markup, ab <section class="closing"> bis zu seinem Ende. */
function closingSection(h) {
  const start = h.indexOf('<section class="closing">');
  return start < 0 ? '' : h.slice(start, h.indexOf('</section>', start));
}

/** Die Kontaktzeilen des neutralen Schlusses als [Label, sichtbarer Wert]. */
function rows(h) {
  return [...closingSection(h).matchAll(/<div class="ck mono">(.*?)<\/div><div class="cv">(.*?)<\/div>/g)]
    .map((m) => [m[1], m[2].replace(/<[^>]+>/g, '')]);
}

const copy = (d) => JSON.parse(JSON.stringify(d));

// Regression: SEO-Befunde zitieren rohes Shop-HTML (<title>/<h1>/<meta>) im body. Wird das roh
// gerendert, parst der Browser es als echtes Element und verschluckt den Rest des Dokuments
// (Report bricht nach dem ersten solchen Befund ab). safeHtml muss Struktur-Tags escapen, aber
// <span class='hl'>/<b>/<i>/<em> erhalten.
test('safeHtml escapet Struktur-Tags, erhält Inline-Formatierung (kein Dokument-Abbruch)', () => {
  const out = safeHtml("Der <title>Beispielshop</title> fehlt, aber <span class='hl'>Keyword</span> und <b>fett</b> bleiben");
  assert.ok(out.includes('&lt;title&gt;'), 'rohes <title> muss escaped werden');
  assert.ok(!out.includes('<title>'), 'kein rohes <title> im Output');
  assert.ok(out.includes("<span class='hl'>"), 'hl-span bleibt erhalten');
  assert.ok(out.includes('<b>fett</b>'), 'b-Tag bleibt erhalten');
});

test('findingBlock rendert body über safeHtml (rohes <title> wird escaped, nicht roh)', () => {
  const probe = JSON.parse(JSON.stringify(data));
  probe.chapters[0].findings[0].body = "Der <title>X</title> ist zu kurz, <span class='hl'>wichtig</span>.";
  const h = renderReportHtml(probe);
  assert.ok(h.includes('&lt;title&gt;X&lt;/title&gt;'), 'body-<title> muss escaped sein');
  assert.ok(h.includes('<section class="closing">'), 'Closing rendert weiterhin (kein Abbruch nach dem Befund)');
});

// Regression: Die Phase-2-Konsolidierer emittieren von Natur aus HTML-Entities (&nbsp; für Glue-
// Spaces, numerische Entities wie &#8222;/&#8220; für deutsche Anführungszeichen, &#8902; für ⋆) und
// <code> für Inline-Code (z.B. <hero-slider>). Der alte safeHtml escapte alles und un-escapte nur
// <b><i><em><strong><br><span> → Entities und <code> landeten LITERAL im PDF ("&nbsp;", "<code>").
// safeHtml muss Entities zu echtem Unicode dekodieren UND <code> als Inline-Tag erlauben.
test('safeHtml dekodiert HTML-Entities (named + numerisch) statt sie literal zu rendern', () => {
  const out = safeHtml('100 Mio.&nbsp;€ — &#8222;Zitat&#8220; und &#8902; sowie &#x22C6;');
  assert.ok(!out.includes('&amp;nbsp;') && !out.includes('&nbsp;'), `&nbsp; literal geblieben: ${out}`);
  assert.ok(out.includes('100 Mio. €'), `&nbsp; nicht als U+00A0 dekodiert: ${out}`);
  assert.ok(out.includes('„') && out.includes('“'), `numerische Entities (deutsche Quotes) nicht dekodiert: ${out}`);
  assert.ok(out.includes('⋆'), `numerische dezimale/hex Entity (⋆) nicht dekodiert: ${out}`);
});

test('safeHtml erlaubt <code> als Inline-Tag (nicht literaler "<code>"-Text)', () => {
  const out = safeHtml('Der Hero hat nur <code>alt="SOCKEN"</code> — kein <code>&lt;h1&gt;</code>.');
  assert.ok(out.includes('<code>') && out.includes('</code>'), `<code> nicht als echtes Tag erhalten: ${out}`);
  assert.ok(!out.includes('&lt;code&gt;'), `<code> blieb escaped/literal: ${out}`);
  assert.ok(out.includes('&lt;h1&gt;'), `code-Inhalt (&lt;h1&gt;) muss als Literal escaped bleiben: ${out}`);
});

test('safeHtml lässt vorhandene Inline-Formatierung + Struktur-Escaping unberührt', () => {
  // Bestehender Vertrag darf nicht brechen: rohe Struktur-Tags escapen, Allowlist erhalten.
  const out = safeHtml("Der <title>X</title> bleibt Text, <span class='hl'>hl</span> & <b>fett</b> bleiben");
  assert.ok(out.includes('&lt;title&gt;X&lt;/title&gt;'), 'rohes <title> muss escaped werden');
  assert.ok(out.includes("<span class='hl'>") && out.includes('<b>fett</b>'), 'Allowlist-Tags müssen erhalten bleiben');
  assert.ok(out.includes('&amp;'), 'bare & muss als &amp; escaped sein (gültiges HTML)');
});

test('Renderer dekodiert Entities/<code> im Befund-Body (kein Literal-Müll im PDF-HTML)', () => {
  const probe = JSON.parse(JSON.stringify(data));
  probe.chapters[0].findings[0].body = 'Glue&nbsp;Wort, Inline-<code>alt</code>, &#8222;Zitat&#8220;.';
  const h = renderReportHtml(probe);
  assert.ok(!h.includes('&amp;nbsp;'), 'literal &nbsp; im gerenderten Report');
  assert.ok(h.includes('<code>alt</code>'), '<code> nicht als Tag im Report');
  assert.ok(h.includes('„') && h.includes('“'), 'numerische Entities nicht dekodiert im Report');
});

// WICHTIG: title/label sind Plain-Text → der Renderer escaped sie. Kapitel-/Befund-Titel
// enthalten '&' (z.B. "Sichtbarkeit & KI-Präsenz") → im HTML steht '&amp;'. Tests deshalb
// gegen esc(...) matchen, NICHT gegen den Rohwert (sonst schlägt korrekter Code fehl).
test('rendert Cover, Executive, alle Kapitel, Fahrplan, Closing', () => {
  assert.ok(html.includes('class="cover"'), 'Cover fehlt');
  assert.match(html, /AUF EINEN BLICK|EXECUTIVE/i);
  for (const ch of data.chapters) assert.ok(html.includes(esc(ch.title)), `Kapitel fehlt: ${ch.title}`);
  assert.match(html, /DER WEG NACH VORN|FAHRPLAN/i);
  assert.ok(html.includes('<section class="closing">'), 'Closing fehlt');
  assert.ok(closingSection(html).includes(ORIGIN), 'Herkunftszeile fehlt');
});

test('Closing ignoriert Content-Overrides', () => {
  const probe = JSON.parse(JSON.stringify(data));
  probe.closing = { headline: 'Dynamischer Abschluss', lead: 'Dynamischer Text' };
  const h = renderReportHtml(probe);
  assert.ok(h.includes('<section class="closing">'), 'Closing fehlt');
  assert.ok(!h.includes('Dynamischer Abschluss') && !h.includes('Dynamischer Text'), 'Content-Override wurde gerendert');
});

test('escapet das Pillar-Label im Kapitel-Eyebrow (bare & → &amp;)', () => {
  // "market" → "MARKT & WETTBEWERB"; das '&' muss als '&amp;' im Eyebrow erscheinen.
  assert.ok(html.includes('MARKT &amp; WETTBEWERB'), 'Pillar-Label nicht escaped');
  assert.ok(!html.includes('MARKT & WETTBEWERB'), 'rohes & im Eyebrow → invalides HTML');
});

test('rendert JEDEN Befund aus JEDEM Kapitel (nichts abgeschnitten)', () => {
  for (const ch of data.chapters)
    for (const f of ch.findings)
      assert.ok(html.includes(esc(f.title)), `Befund fehlt im HTML: ${f.title}`);
});

test('attribuiert die beitragenden Skills je Kapitel', () => {
  for (const ch of data.chapters)
    for (const s of ch.skills)
      assert.ok(html.includes(s), `Skill-Attribution fehlt: ${s}`);
});

test('nutzt fließende Paginierung statt content-clipping', () => {
  assert.match(html, /break-inside\s*:\s*avoid/);
  assert.match(html, /page-break-before\s*:\s*always|break-before\s*:\s*page/);
  // kein height:297mm + overflow:hidden auf den fließenden Kapitel-Containern
  assert.ok(!/\.chapter\b[^{]*\{[^}]*overflow\s*:\s*hidden/.test(html), 'Kapitel-Container darf nicht clippen');
});

test('rendert 3 Score-Balken mit Ziel + escapet Plain-Text', () => {
  for (const s of data.exec.scores) { assert.ok(html.includes(String(s.score))); assert.ok(html.includes(esc(s.label))); }
  assert.ok(!html.includes('<script'), 'kein Script-Inject');
});

test('lässt Inline-HTML in fahrplan.proj.text roh durch', () => {
  // proj.text enthält im Fixture <b>…</b> — das muss als echtes Markup im Output ankommen.
  assert.match(data.fahrplan.proj.text, /<b>/, 'Fixture-Voraussetzung: proj.text enthält <b>');
  assert.ok(html.includes(data.fahrplan.proj.text), 'proj.text wurde nicht roh übernommen');
});

// Story-Arc: Cover-Hook + die neuen Sektionen müssen aus dem Sample rendern. Fängt ab, wenn eine
// Sektion versehentlich aus dem Renderer fällt oder der content.json-Vertrag bricht.
test('Story-Arc-Sektionen rendern aus dem Sample', () => {
  assert.ok(html.includes('Klare Kante'), 'Cover-Hook nicht datengetrieben');
  assert.ok(html.includes('DER MARKT') && html.includes(esc(data.market.headline)), 'Markt-Sektion fehlt');
  assert.ok(html.includes('Beispiel-Rucksack'), 'Markt-Callout (Hauptpotenzial) fehlt');
  assert.ok(html.includes('Musterstadt'), 'Company-Card-Zeile fehlt');
  assert.ok(html.includes('<svg') && html.includes(esc(data.positioning.axisX.right)), 'Quadrant-SVG/Achse fehlt');
  assert.ok(html.includes('wettbewerber-eins.example'), 'Quadrant-Wettbewerberpunkt fehlt');
  assert.ok(html.includes(esc(data.matrix.capabilities[1].label)), 'Vergleichsmatrix-Zeile fehlt');
  assert.ok(html.includes('DOPPELT DRAUF SETZEN'), 'Strategie-Triage fehlt');
  assert.ok(html.includes('WO WIR ANDOCKEN') && html.includes('pill-open'), 'AI-Levers/Reife-Pill fehlt');
  assert.ok(html.includes('QUELLEN &amp; METHODIK'), 'Quellen-Sektion fehlt');
  assert.ok(html.includes('GESAMT-SCORE'), 'Composite-Score auf der Exec-Seite fehlt');
});

// Spec 2026-09-11 public release, C1: das Sample war ein echter Audit eines Kunden.
// Es ist erfunden und bleibt es; ein neuer echter Lauf gehört nicht hierher.
test('das Sample ist ein erfundener Beispielshop', () => {
  assert.equal(data.shop, 'beispielshop.example');
  assert.equal(data.meta.erstelltFuer, 'Beispielshop');
});

// Regression: Die Markt-Headline ist die EINZIGE Sektion, die einen dekorativen orange Punkt
// (<span class="dot">.</span>) anhängt. Endet market.headline in content.json selbst auf "." (sehr
// natürlich geschrieben), entstand früher ein doppelter Punkt ("…Marktplatz.."). Der Renderer muss
// einen trailing "." (+ Whitespace) strippen, bevor er den Punkt anhängt → genau EIN Punkt.
test('Markt-Headline: trailing "." wird gestrippt, kein doppelter Punkt', () => {
  const probe = JSON.parse(JSON.stringify(data));
  probe.market.headline = 'Zwischen Direktkanal und Marktplatz.';
  const h = renderReportHtml(probe);
  assert.ok(h.includes('Marktplatz<span class="dot">.</span>'), 'genau ein dekorativer Punkt nach gestripptem Headline');
  assert.ok(!h.includes('Marktplatz.<span class="dot">.</span>'), 'roher "." + dekorativer Punkt → doppelter Punkt');
  assert.ok(!h.includes('Marktplatz..'), 'kein literaler doppelter Punkt im Output');
});

// Befund-Deep-Links: jedes Finding mit `url` bekommt einen klickbaren "↗ zur Stelle ansehen"-
// Link (funktioniert in HTML + PDF, da Chrome <a href> ins PDF backt). Die URL wird attr-escaped.
test('findingBlock rendert klickbaren ↗-Link bei finding.url (URL attr-escaped)', () => {
  const probe = JSON.parse(JSON.stringify(data));
  probe.chapters[0].findings[0].url = 'https://shop.example/products/x?a=1&b=2';
  const h = renderReportHtml(probe);
  assert.ok(h.includes('href="https://shop.example/products/x?a=1&amp;b=2"'), 'url muss als attr-escaped href erscheinen');
  assert.ok(h.includes('zur Stelle ansehen'), 'Link-Text fehlt');
});

test('findingBlock ohne url rendert KEINEN ↗-Link (Befund rendert trotzdem)', () => {
  const probe = JSON.parse(JSON.stringify(data));
  for (const ch of probe.chapters) for (const f of ch.findings) delete f.url;
  const h = renderReportHtml(probe);
  assert.ok(!h.includes('zur Stelle ansehen'), 'ohne url darf kein ↗-Link erscheinen');
  assert.ok(h.includes(esc(probe.chapters[0].findings[0].title)), 'Befund rendert trotzdem');
});

// Regression Paginierung: Der Fahrplan muss als EINE Einheit umbrechen. Ohne die .roadmap-Klammer
// zerlegte der Fragmentierer ihn (gemessen über 22 Läufe in audit-runs/): entweder stand die
// Projektion allein auf einer sonst leeren Seite (12 Läufe) oder Überschrift und Lead blieben unten
// auf der Vorseite zurück, während Etappen und Projektion umbrachen (6 Läufe).
test('Fahrplan bricht als eine Einheit um (.roadmap klammert Überschrift, Lead, Etappen, Projektion)', () => {
  assert.match(html, /\.roadmap\s*\{[^}]*break-inside\s*:\s*avoid/, '.roadmap braucht break-inside: avoid');
  const m = html.match(/<div class="roadmap">([\s\S]*?)\n\s*<\/div>\n<\/section>/);
  assert.ok(m, '.roadmap-Container fehlt oder schließt nicht vor dem Sektionsende');
  const unit = m[1];
  assert.ok(unit.includes('DER WEG NACH VORN'), 'Eyebrow gehört in die Einheit');
  assert.ok(unit.includes(esc(data.fahrplan.headline)), 'Fahrplan-Überschrift gehört in die Einheit');
  assert.ok(unit.includes(esc(data.fahrplan.lead)), 'Fahrplan-Lead gehört in die Einheit');
  assert.ok(unit.includes('class="stages"'), 'Etappen gehören in die Einheit');
  assert.ok(unit.includes('class="proj"'), 'Projektionsblock gehört in die Einheit');
  // Die Triage steht bewusst DAVOR: sie darf auf der Vorseite bleiben, wenn der Fahrplan umbricht.
  assert.ok(!unit.includes('class="triage"'), 'Triage darf nicht in die Fahrplan-Einheit');
});

// Ohne Triage rendert dieselbe Sektion ohne den 18mm-Vorspann — die Klammer muss trotzdem stehen.
test('Fahrplan-Einheit steht auch ohne Triage (Sektion ohne 18mm-Vorspann)', () => {
  const probe = JSON.parse(JSON.stringify(data));
  delete probe.triage;
  const h = renderReportHtml(probe);
  assert.ok(h.includes('<div class="roadmap">'), '.roadmap fehlt ohne Triage');
  assert.ok(!h.includes('margin-top:18mm'), 'ohne Triage darf kein 18mm-Vorspann gesetzt sein');
  assert.ok(h.includes('class="proj"'), 'Projektionsblock rendert weiterhin');
});


// Regression beispielshop.com (29.08.2026): esc() wandelt " in &quot; um, BEVOR die span-Allowlist
// greift. Die alte Zeichenklasse [^&<>]* konnte das Ergebnis nicht mehr matchen, also landete
// <span class="hl"> als sichtbarer Klartext auf Cover, Exec-Seite, Fahrplan und Hebel-Seite.
// Doppelte Anführungszeichen sind valides HTML und die verbreitetere Schreibweise: beide gehen.
test('safeHtml rendert <span class="hl"> in doppelten UND einfachen Quotes', () => {
  for (const [label, input] of [
    ['doppelt', 'Der Shop wird <span class="hl">namentlich genannt</span>.'],
    ['einfach', "Der Shop wird <span class='hl'>namentlich genannt</span>."],
    ['ohne Quotes', 'Der Shop wird <span class=hl>namentlich genannt</span>.'],
  ]) {
    const out = safeHtml(input);
    assert.ok(!out.includes('&lt;span'), `${label}: span-Tag blieb Klartext: ${out}`);
    assert.match(out, /<span class=("hl"|'hl'|hl)>namentlich genannt<\/span>/, `${label}: ${out}`);
  }
});

// Die Allowlist darf durch den Quote-Fix nicht aufweichen: durchgelassen wird ausschließlich
// class=hl (die einzige Inline-Klasse im Report-CSS), nichts sonst.
test('safeHtml escapet Fremd-HTML und span-Varianten außerhalb der Allowlist weiterhin', () => {
  const gefaehrlich = [
    '<script>alert(1)</script>',
    '<span onclick="alert(1)">Klick</span>',
    '<span class="hl" onclick="alert(1)">Klick</span>',
    '<span style="color:#F7766E;">rot</span>',
    '<img src=x onerror="alert(1)">',
    '<span onclick=alert(1)>Klick</span>',            // ohne Quotes: die alte Zeichenklasse ließ das durch
    '<span class=hl onclick=alert(1)>Klick</span>',   // zweites Attribut, ebenfalls ohne Quotes
    '<a href="https://evil.example/">Link</a>',
  ];
  for (const input of gefaehrlich) {
    const out = safeHtml(input);
    assert.ok(!/<(script|img|a|span)\b/i.test(out), `Fremd-HTML nicht escaped: ${input} → ${out}`);
    assert.ok(out.includes('&lt;'), `kein escaptes Tag im Output: ${input} → ${out}`);
  }
});

// Befunde ZITIEREN Shop-Markup (im Korpus u.a. <span class="util-ScreenReaderOnly">, <span>).
// Würde die Allowlist jede class durchlassen, verschwänden diese Zitate unsichtbar aus dem PDF.
test('safeHtml lässt zitiertes Shop-Markup als lesbaren Text stehen', () => {
  const out = safeHtml('Im Quelltext steht <span class="util-ScreenReaderOnly">Preis</span> und ein nacktes <span>Ausverkauft</span>.');
  assert.ok(out.includes('&lt;span class=&quot;util-ScreenReaderOnly&quot;&gt;'), `fremde Klasse muss Text bleiben: ${out}`);
  assert.ok(out.includes('&lt;span&gt;Ausverkauft&lt;/span&gt;'), `nacktes <span> muss Text bleiben: ${out}`);
  assert.ok(!out.includes('<span'), `kein echtes span-Element im Output: ${out}`);
});

// Ein zitiertes </span> ohne geöffnetes Highlight darf die Hervorhebung nicht vorzeitig schließen.
test('safeHtml wandelt </span> nur zurück, wenn es ein Highlight schließt', () => {
  const out = safeHtml('Ende des Blocks: </span> im Quelltext.');
  assert.ok(out.includes('&lt;/span&gt;'), `verwaistes </span> muss Text bleiben: ${out}`);
  const paar = safeHtml('<span class="hl">A</span> und </span> im Zitat');
  assert.ok(paar.includes('<span class="hl">A</span>'), `Highlight-Paar fehlt: ${paar}`);
  assert.ok(paar.includes('&lt;/span&gt;'), `zweites </span> muss Text bleiben: ${paar}`);
});

// Der Lauf beispielshop.com traf genau diese vier Felder — alle laufen über safeHtml, keins über esc.
test('Renderer rendert <span class="hl"> in Cover, Exec, Fahrplan und Hebeln als Tag', () => {
  const probe = JSON.parse(JSON.stringify(data));
  probe.cover.intro = 'Cover: <span class="hl">Cover-HL</span>.';
  probe.exec.summary[0] = 'Exec: <span class="hl">Exec-HL</span>.';
  probe.fahrplan.proj.text = 'Fahrplan: <span class="hl">Fahrplan-HL</span>.';
  probe.levers.intro = 'Hebel: <span class="hl">Hebel-HL</span>.';
  const h = renderReportHtml(probe);
  assert.ok(!h.includes('&lt;span class=&quot;hl&quot;&gt;'), 'span-Tag steht als Klartext im Report');
  for (const t of ['Cover-HL', 'Exec-HL', 'Fahrplan-HL', 'Hebel-HL']) {
    assert.ok(h.includes(`<span class="hl">${t}</span>`), `${t} nicht als Highlight gerendert`);
  }
});

// Spec 2026-09-11, D3: Porträts und Zitate der zwei Kundenkontakte sind raus.
// Seit dem 15.09.2026 auch das Porträt des Betreibers samt Kontaktblock.
test('das PDF zeigt keine Kundenstimmen und kein Porträt', () => {
  assert.doesNotMatch(html, /portraits\//);
  assert.doesNotMatch(html, /<img\b/);
  assert.doesNotMatch(html, /class="quotes?"/);
});

// ---------- Schluss (Entscheidung 15.09.2026, zweiter Teil) ----------

test('mit PTAI_CLOSING_FILE ist die Datei die letzte Seite, ohne neutrale Zeilen', () => {
  const path = join(TMP, 'schlussseite.html');
  writeFileSync(path, FRAGMENT);
  const { h, warnings } = render(`PTAI_CLOSING_FILE=${path}\nPTAI_OPERATOR_CONTACT=Mara Beispiel\n`);
  assert.equal(h.split(FRAGMENT).length - 1, 1, 'Schlussseite fehlt oder steht doppelt');
  assert.equal(h.slice(h.indexOf(FRAGMENT) + FRAGMENT.length).replace(/\s+/g, ''), '</body></html>');
  for (const gone of ['<section class="closing">', 'Mara Beispiel', 'Erstellt mit ptai-ecom', 'class="contact-row"']) {
    assert.ok(!h.includes(gone), `steht trotz Schlussseite im Report: ${gone}`);
  }
  assert.ok(h.indexOf(DISCLAIMER) < h.indexOf(FRAGMENT), 'Kleindruck gehört vor die Schlussseite');
  assert.deepEqual(warnings, []);
});

test('ohne PTAI_CLOSING_FILE folgen die Kontaktzeilen den Einstellungen', () => {
  const { h, warnings } = render('PTAI_OPERATOR_NAME=Beispiel GmbH\nPTAI_OPERATOR_CONTACT=Mara Beispiel\n'
    + 'PTAI_OPERATOR_EMAIL=kontakt@beispielshop.example\nPTAI_OPERATOR_BOOKING_URL="https://termine.example/30min/"\n');
  assert.deepEqual(rows(h), [['Unternehmen', 'Beispiel GmbH'], ['Ansprechpartner', 'Mara Beispiel'],
                             ['E-Mail', 'kontakt@beispielshop.example'], ['Termin', 'termine.example/30min']]);
  const section = closingSection(h);
  assert.ok(section.includes('<div class="eyebrow2 mono">Kontakt</div>'), 'Label Kontakt fehlt');
  assert.ok(section.includes('<a href="mailto:kontakt@beispielshop.example">kontakt@beispielshop.example</a>'));
  assert.ok(section.includes('<a href="https://termine.example/30min/">termine.example/30min</a>'));
  assert.ok(section.indexOf('class="contact-rows"') < section.indexOf(ORIGIN), 'Herkunftszeile gehört unter die Zeilen');
  assert.deepEqual(warnings, []);
});

test('ohne Einstellung nur die Herkunftszeile, der Firmenname nur ausdrücklich', () => {
  const none = closingSection(render().h);
  assert.ok(none.includes(ORIGIN), 'Herkunftszeile fehlt');
  assert.ok(!none.includes('contact-row') && !none.includes('Kontakt'), 'Zeilen ohne Einstellung');
  const { h } = render('PTAI_OPERATOR_CONTACT=Mara Beispiel\n');
  assert.deepEqual(rows(h), [['Ansprechpartner', 'Mara Beispiel']]);
  assert.ok(!closingSection(h).includes('Dienstleister') && !closingSection(h).includes('Unternehmen'));
});

test('ungültige Mailadressen und Terminlinks fallen weg, Werte werden escaped', () => {
  for (const url of ['javascript:alert(1)', 'JavaScript:alert(1)', 'data:text/html,x', 'ftp://termine.example/30min',
                     '//termine.example/30min', 'termine.example/30min', 'https://', 'https:termine.example',
                     'https://termine.example/30 min']) {
    assert.deepEqual(rows(render(`PTAI_OPERATOR_BOOKING_URL=${url}\n`).h), [], url);
  }
  assert.deepEqual(rows(render('PTAI_OPERATOR_BOOKING_URL=http://termine.example/30min\n').h),
                   [['Termin', 'termine.example/30min']]);
  for (const mail of ['keine-adresse', 'kontakt@beispielshop', 'kontakt beispielshop.example',
                      'kontakt@beispiel shop.example', '"><b>@x.example', 'a@b@beispiel.example']) {
    assert.deepEqual(rows(render(`PTAI_OPERATOR_EMAIL=${mail}\n`).h), [], mail);
  }
  const section = closingSection(render('PTAI_OPERATOR_NAME=Beispiel <b>GmbH</b>\n'
    + 'PTAI_OPERATOR_BOOKING_URL=https://termine.example/30min?a=1&b="2"\n').h);
  assert.ok(!section.includes('<b>'), 'Name nicht escaped');
  assert.ok(section.includes('Beispiel &lt;b&gt;GmbH&lt;/b&gt;'));
  assert.ok(section.includes('href="https://termine.example/30min?a=1&amp;b=&quot;2&quot;"'));
});

test('die Umgebung schlägt die zentrale Datei, ein leeres PTAI_ENV_FILE heißt keine', () => {
  process.env.PTAI_OPERATOR_CONTACT = 'Tom Beispiel';
  try {
    assert.deepEqual(rows(render('PTAI_OPERATOR_CONTACT=Mara Beispiel\n').h), [['Ansprechpartner', 'Tom Beispiel']]);
  } finally {
    delete process.env.PTAI_OPERATOR_CONTACT;
  }
  const standard = join(HOME, '.config', 'ptai-ecom');
  mkdirSync(standard, { recursive: true });
  writeFileSync(join(standard, '.env'), 'PTAI_OPERATOR_CONTACT=Mara Beispiel\n');
  try {
    delete process.env.PTAI_ENV_FILE;
    assert.deepEqual(rows(renderReportHtml(data)), [['Ansprechpartner', 'Mara Beispiel']], 'Standardort unter HOME');
    process.env.PTAI_ENV_FILE = '';
    assert.deepEqual(rows(renderReportHtml(data)), [], 'leeres PTAI_ENV_FILE');
  } finally {
    process.env.PTAI_ENV_FILE = CENTRAL;
    rmSync(standard, { recursive: true, force: true });
  }
});

test('fehlende, leere oder unlesbare Schlussseite: neutraler Schluss und eine Warnung', () => {
  const empty = join(TMP, 'leer.html');
  writeFileSync(empty, ' \n\n');
  const folder = join(TMP, 'ordner');
  mkdirSync(folder, { recursive: true });
  const broken = join(TMP, 'kein-utf8.html');
  writeFileSync(broken, Buffer.from([0x3c, 0x73, 0xff, 0xfe]));
  for (const [label, path] of [['fehlt', join(TMP, 'fehlt.html')], ['leer', empty], ['Ordner', folder],
                               ['kein UTF-8', broken]]) {
    const { h, warnings } = render(`PTAI_CLOSING_FILE=${path}\nPTAI_OPERATOR_CONTACT=Mara Beispiel\n`);
    assert.deepEqual(rows(h), [['Ansprechpartner', 'Mara Beispiel']], label);
    assert.ok(closingSection(h).includes(ORIGIN), label);
    assert.equal(warnings.length, 1, label);
    assert.match(warnings[0], /PTAI_CLOSING_FILE/, label);
    assert.ok(!warnings[0].includes('\n'), `${label}: Warnung über mehr als eine Zeile`);
  }
});

test('eine führende ~ in PTAI_CLOSING_FILE zeigt ins Home-Verzeichnis', () => {
  writeFileSync(join(HOME, 'schlussseite.html'), FRAGMENT);
  const { h, warnings } = render('PTAI_CLOSING_FILE=~/schlussseite.html\n');
  assert.ok(h.includes(FRAGMENT));
  assert.deepEqual(warnings, []);
});

test('render.mjs meldet eine fehlende Schlussseite in einer Zeile auf stderr und rendert', () => {
  const central = join(TMP, 'render.env');
  writeFileSync(central, `PTAI_CLOSING_FILE=${join(TMP, 'fehlt.html')}\n`);
  const out = join(TMP, 'render', 'report.html');
  const result = spawnSync(process.execPath,
                           [fileURLToPath(new URL('./render.mjs', import.meta.url)), fileURLToPath(SAMPLE), out],
                           { encoding: 'utf8', env: { HOME, PTAI_ENV_FILE: central } });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stderr.trim().split('\n').length, 1, result.stderr);
  assert.match(result.stderr, /PTAI_CLOSING_FILE/);
  assert.ok(readFileSync(out, 'utf8').includes('<section class="closing">'));
});

test('der Renderer trägt keine Daten und kein Porträt des Betreibers', () => {
  const source = readFileSync(new URL('./report-pdf-full.mjs', import.meta.url), 'utf8');
  // Zusammengesetzt, damit die Suche nach dem alten Schluss nicht diese Datei findet.
  for (const needle of ['yves-schleich' + '_hero', 'cal.com', 'yves@', 'Termin ' + 'vereinbaren', 'report-closing',
                        'portraits', 'Yves ' + 'Schleich']) {
    assert.ok(!source.includes(needle), `report-pdf-full.mjs enthält ${needle}`);
    assert.ok(!html.includes(needle), `der gerenderte Report enthält ${needle}`);
  }
});

test('der Kleindruck steht am Ende der letzten Inhaltsseite, nie auf der Schlussseite', () => {
  const withoutSources = copy(data);
  delete withoutSources.sources;
  const withoutBoth = copy(withoutSources);
  delete withoutBoth.levers;
  for (const [label, probe, last] of [['mit Quellen', data, 'QUELLEN &amp; METHODIK'],
                                      ['ohne Quellen', withoutSources, 'WO WIR ANDOCKEN'],
                                      ['ohne Quellen und Hebel', withoutBoth, 'DER WEG NACH VORN']]) {
    const h = renderReportHtml(probe);
    const fine = h.indexOf(DISCLAIMER);
    const closingAt = h.indexOf('<section class="closing">');
    assert.equal(h.split(DISCLAIMER).length - 1, 1, `${label}: Kleindruck fehlt oder steht doppelt`);
    assert.ok(fine > -1 && fine < closingAt, `${label}: Kleindruck nicht vor dem Schluss`);
    assert.ok(h.slice(h.lastIndexOf('class="chapter"', fine), fine).includes(last), `${label}: nicht in der letzten Seite`);
    assert.ok(!h.slice(fine, closingAt).includes('class="chapter"'), `${label}: nach dem Kleindruck folgt noch eine Seite`);
    assert.ok(!closingSection(h).includes(DISCLAIMER), `${label}: Kleindruck auf der Schlussseite`);
  }
});

// Das Copyright nennt den Betreiber aus PTAI_OPERATOR_NAME, gesucht wie der
// Schluss. Ohne ausdrücklich gesetzten Namen entfällt der Satz, statt in jedem
// fremden Report einen festen Betreiber zu nennen.
test('der Kleindruck endet mit dem Copyright des Betreibers, ohne Namen ohne Copyright', () => {
  const fineOf = (h) => {
    const start = h.indexOf(`<div class="fine">${DISCLAIMER}`);
    assert.ok(start > -1, 'Kleindruck fehlt');
    return h.slice(start, h.indexOf('</div>', start));
  };
  const scores = 'Die Scores sind Orientierung, keine Garantie.';
  const year = data.meta.year;
  const named = fineOf(render('PTAI_OPERATOR_NAME=Beispiel GmbH\n').h);
  assert.ok(named.endsWith(`${scores} © ${year} Beispiel GmbH.`), named);
  for (const [label, central] of [['ohne Einstellung', null], ['nur Leerzeichen', 'PTAI_OPERATOR_NAME="  "\n'],
                                  ['nur Kontakt', 'PTAI_OPERATOR_CONTACT=Mara Beispiel\n']]) {
    const fine = fineOf(render(central).h);
    assert.ok(fine.endsWith(scores), `${label}: ${fine}`);
    assert.ok(!fine.includes('©'), `${label}: Copyright ohne Namen`);
  }
  assert.ok(fineOf(render('PTAI_OPERATOR_NAME=Beispiel <b>GmbH</b>\n').h)
    .endsWith(`© ${year} Beispiel &lt;b&gt;GmbH&lt;/b&gt;.`), 'Name nicht escaped');
  process.env.PTAI_OPERATOR_NAME = 'Tom Beispiel GmbH';
  try {
    assert.ok(fineOf(render('PTAI_OPERATOR_NAME=Beispiel GmbH\n').h).endsWith(`© ${year} Tom Beispiel GmbH.`),
              'die Umgebung schlägt die zentrale Datei');
  } finally {
    delete process.env.PTAI_OPERATOR_NAME;
  }
});
