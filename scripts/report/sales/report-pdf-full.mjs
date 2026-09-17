// Ecom-Audit PDF report — comprehensive flowing renderer (story-arc layout).
// Designed HTML (A4), rendered to PDF via headless Chrome.
// v2: flowing layout (no height:297mm clip), all findings per chapter, chapter-level skill attribution.
// v3: brand fonts embedded (engine/fonts.mjs, base64) — zero network dependency at render time.
// v4: story-arc — data-driven cover, market + shop-at-a-glance, positioning quadrant, comparison
//     matrix, top-first/compact findings, strategy triage, AI levers, sources. All new sections are
//     OPTIONAL: a missing content.json field simply skips its section (graceful degradation, and an
//     old content.json still renders cover + exec + chapters + fahrplan + closing).

// Marken-Fonts als Dateien, relativ zu diesem Modul. Der alte Stand trug sie als
// base64 im Repo (fonts.mjs allein 712 KB), weil der Renderer ohne Netz
// auskommen musste. Das Plugin hat die echten Dateien unter assets/brand/, und
// Chrome liest sie ueber file:// genauso offline.
import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';

const BRAND = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', 'assets', 'brand');
const asset = (...p) => pathToFileURL(join(BRAND, ...p)).href;

const FONT_FACE_CSS = `
@font-face{font-family:'Archivo';font-weight:900;font-style:normal;font-display:block;src:url("${asset('fonts','archivo-black.woff2')}") format('woff2')}
@font-face{font-family:'Archivo';font-weight:900;font-style:italic;font-display:block;src:url("${asset('fonts','archivo-black-italic.woff2')}") format('woff2')}
@font-face{font-family:'Inter';font-weight:400;font-style:normal;font-display:block;src:url("${asset('fonts','inter-regular.woff2')}") format('woff2')}
@font-face{font-family:'Inter';font-weight:600;font-style:normal;font-display:block;src:url("${asset('fonts','inter-semibold.woff2')}") format('woff2')}
@font-face{font-family:'JetBrains Mono';font-weight:500;font-style:normal;font-display:block;src:url("${asset('fonts','jetbrains-mono-medium.woff2')}") format('woff2')}
`;

export const esc = (s) =>
  String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// Common named HTML entities the consolidator agents emit in prose. Numeric entities (&#NNNN; /
// &#xNN;) are handled generically below — this map only covers names that have no numeric escape
// in the source text. Unknown names are left untouched (they get esc'd → render literally, safely).
const NAMED_ENTITIES = {
  nbsp: ' ', amp: '&', lt: '<', gt: '>', quot: '"', apos: "'",
  mdash: '—', ndash: '–', hellip: '…', euro: '€',
  copy: '©', reg: '®', trade: '™', deg: '°', times: '×',
  rarr: '→', larr: '←', laquo: '«', raquo: '»',
  bdquo: '„', ldquo: '“', rdquo: '”', sbquo: '‚', lsquo: '‘', rsquo: '’',
};

// Decode HTML entities to real Unicode. The Phase-2 agents naturally write &nbsp; (glue spaces),
// numeric entities like &#8222;/&#8220; (German quotes) and &#8902; (⋆) — without this they'd
// render LITERALLY as "&nbsp;"/"&#8222;" in the PDF. Single pass over each &…; token; unknown
// entities are returned verbatim so esc() can render them as harmless literal text.
export const decodeEntities = (s) =>
  String(s ?? '').replace(/&(#x[0-9a-f]+|#\d+|[a-z][a-z0-9]*);/gi, (m, ent) => {
    if (ent[0] === '#') {
      const cp = ent[1].toLowerCase() === 'x' ? parseInt(ent.slice(2), 16) : parseInt(ent.slice(1), 10);
      return Number.isFinite(cp) && cp > 0 && cp <= 0x10ffff ? String.fromCodePoint(cp) : m;
    }
    const c = NAMED_ENTITIES[ent.toLowerCase()];
    return c === undefined ? m : c;
  });

// Decode entities → escape ALL tags → restore a safe inline-formatting allowlist. Decoding first
// means agent-emitted &nbsp;/&#8222;/&amp; become real characters (then esc re-escapes any bare
// & < > " into valid HTML). Escaping then restoring lets finding bodies/intros QUOTE raw site HTML
// (e.g. <title>, <h1>, <meta>) as readable literal text without the browser parsing it as real
// elements — while still rendering intentional <span class='hl'> / <b> emphasis and <code> spans.
export const safeHtml = (s) => {
  let out = esc(decodeEntities(s));
  out = out.replace(/&lt;(\/?)(b|i|em|strong|code)&gt;/gi, '<$1$2>');
  out = out.replace(/&lt;br\s*\/?&gt;/gi, '<br>');
  // <span>-Allowlist: genau ein Attribut, class=hl — die einzige Inline-Klasse, die das Report-CSS
  // kennt (.lead .hl / .ch-intro .hl). Der Wert darf in doppelten Quotes stehen (esc() hat die zu
  // diesem Zeitpunkt schon in &quot; verwandelt), in einfachen oder in gar keinen; content.json
  // darf also beide Schreibweisen benutzen. Die Quotes werden nur INNERHALB dieser gematchten Form
  // zurückgewandelt, die Zeichenklasse bleibt zu. Alles andere — fremde Klasse, style/onclick,
  // nacktes <span> — bleibt escapter Text, denn das sind Befunde, die Shop-Markup ZITIEREN.
  // Ein </span> wird nur zurückgewandelt, wenn es ein geöffnetes Highlight schließt: sonst würde
  // ein zitiertes </span> die echte Hervorhebung vorzeitig beenden.
  let open = 0;
  out = out.replace(/&lt;span\s+class=(&quot;|'|)(?:hl)\1\s*&gt;|&lt;\/span&gt;/gi, (m, q) => {
    if (m.startsWith('&lt;/')) {
      if (open === 0) return m;
      open--;
      return '</span>';
    }
    open++;
    const quote = q === '&quot;' ? '"' : q;
    return `<span class=${quote}hl${quote}>`;
  });
  return out;
};

// ---------- shared bits ----------

// Neue CI kennt kein Gelb/Grün: Rot = Handlungsbedarf (laut), Tinte = teilweise, Blau = ruhig/ok.
const SEVERITY_COLOR = { crit: '#C62F14', warn: '#14150F', info: '#1F3F8F', ok: '#1F3F8F' };

// Cover headline: plaintext in; colour the sentence-ending periods in signal orange.
function coverHeadline(d) {
  const h = d.cover && d.cover.headline;
  if (!h) return `Gefunden<span class="dot">.</span> Empfohlen<span class="dot">.</span> Gekauft<span class="dot">.</span>`;
  return esc(h).replace(/\.(\s|$)/g, '<span class="dot">.</span>$1');
}

// Harvey ball for the comparison matrix (0 = empty, 1 = half, 2 = full). Inline SVG so it renders
// identically in headless Chrome regardless of font glyph coverage.
function hb(n) {
  const c = '#1F3F8F';
  if (n >= 2) return `<svg width="14" height="14" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" fill="${c}"/></svg>`;
  if (n === 1) return `<svg width="14" height="14" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" fill="none" stroke="${c}" stroke-width="1.5"/><path d="M8 1 A7 7 0 0 1 8 15 Z" fill="${c}"/></svg>`;
  return `<svg width="14" height="14" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" fill="none" stroke="${c}" stroke-width="1.5"/></svg>`;
}

// ---------- exec / fahrplan sub-renderers ----------

// Ampel-Variante (exec.scoreStyle === 'ampel'): Status statt 0-100-Zahl.
function ampelLevel(score) {
  const s = Math.max(0, Math.min(100, Number(score) || 0));
  if (s >= 75) return { color: '#1F3F8F', word: 'Stark', idx: 2 };
  if (s >= 50) return { color: '#14150F', word: 'Ausbaufähig', idx: 1 };
  return { color: '#C62F14', word: 'Handlungsbedarf', idx: 0 };
}

function ampelDots(level, size) {
  const cols = ['#C62F14', '#14150F', '#1F3F8F'];
  return `<div class="ampel">${cols.map((c, i) => `<span class="ad${i === level.idx ? ' on' : ''}" style="${i === level.idx ? `background:${c}` : `border:1.5px solid ${c};opacity:.35`};width:${size}px;height:${size}px"></span>`).join('')}</div>`;
}

function scoreCol(s, style) {
  const score = Math.max(0, Math.min(100, s.score));
  const target = Math.max(0, Math.min(100, s.target ?? 0));
  if (style === 'potenzial') {
    const lvl = ampelLevel(score);
    return `<div class="scol">
    <div class="mono lbl">${esc(s.label)}</div>
    <div class="num">${score}<span class="den">/100</span></div>
    <div class="bar"><div class="fill" style="width:${score}%;background:${lvl.color}"></div>
      ${s.target ? `<div class="mark" style="left:${target}%"></div><div class="goal mono" style="left:${target}%">Ziel ${target}</div>` : ''}
    </div>
    ${s.target && target > score ? `<div class="pot mono">+${target - score} PUNKTE ERREICHBAR</div>` : ''}
    <div class="cap">${esc(s.caption)}</div>
  </div>`;
  }
  if (style === 'ampel') {
    const now = ampelLevel(score);
    const goal = s.target ? ampelLevel(target) : null;
    return `<div class="scol">
    <div class="mono lbl">${esc(s.label)}</div>
    ${ampelDots(now, 13)}
    <div class="aword">${esc(now.word)}</div>
    ${goal ? `<div class="agoal mono">ZIEL NACH UMSETZUNG: <span style="color:${goal.color}">${esc(goal.word.toUpperCase())}</span></div>` : ''}
    <div class="cap">${esc(s.caption)}</div>
  </div>`;
  }
  return `<div class="scol">
    <div class="mono lbl">${esc(s.label)}</div>
    <div class="num">${score}<span class="den">/100</span></div>
    <div class="bar"><div class="fill" style="width:${score}%"></div>
      ${s.target ? `<div class="mark" style="left:${target}%"></div><div class="goal mono" style="left:${target}%">Ziel ${target}</div>` : ''}
    </div>
    <div class="cap">${esc(s.caption)}</div>
  </div>`;
}

function stageCol(s) {
  return `<div class="stage">
    <div class="mono slbl">${esc(s.stage)}</div>
    <div class="stitle">${esc(s.title)}</div>
    <ul>${s.items.map((it) => `<li>${esc(it)}</li>`).join('')}</ul>
  </div>`;
}

// ---------- findings ----------

function findingBlock(f, i) {
  const dot = SEVERITY_COLOR[f.severity] || SEVERITY_COLOR.info;
  // f.evidence is intentionally NOT rendered in the client-facing PDF — raw evidence lives in
  // findings.json, the job-folder .md reports, and the aggregated Sources section.
  return `<div class="fcard">
    <div class="fsev" style="background:${dot}"></div>
    <div class="fbody">
      <div class="fhead"><span class="fnum mono">Befund ${String(i + 1).padStart(2, '0')}</span>${f.effort ? `<span class="fbadge mono">${esc(f.effort)}</span>` : ''}</div>
      <div class="ftitle">${esc(f.title)}</div>
      <div class="ftext">${safeHtml(f.body)}</div>
      ${f.recommendation ? `<div class="frec"><span class="mono frec-lbl">EMPFEHLUNG</span> ${esc(f.recommendation)}</div>` : ''}
      ${f.impact ? `<div class="fimpact"><span class="mono">Wirkung</span> ${esc(f.impact)}</div>` : ''}
      ${f.skill_source ? `<div class="fskill mono">${esc(f.skill_source)}</div>` : ''}
      ${f.url ? `<a class="floc mono" href="${esc(f.url)}">↗ zur Stelle ansehen</a>` : ''}
    </div>
  </div>`;
}

function compactFinding(f) {
  const dot = SEVERITY_COLOR[f.severity] || SEVERITY_COLOR.info;
  return `<div class="fcrow"><span class="fcdot" style="background:${dot}"></span><div><div class="fct">${esc(f.title)}</div>${f.impact ? `<div class="fci">${esc(f.impact)}</div>` : ''}</div></div>`;
}

const PILLAR_LABEL = { found: 'AKQUISITION', convince: 'CONVERSION RATE OPTIMIERUNG', trust: 'TRUST UND COMPLIANCE', market: 'MARKT & WETTBEWERB' };

function chapterSection(ch, idx, headHtml) {
  const pillarLabel = PILLAR_LABEL[ch.pillar] || (ch.pillar || '').toUpperCase();
  const skillsHtml = ch.skills && ch.skills.length
    ? `<div class="ch-skills mono">Skills: ${ch.skills.map(esc).join(' · ')}</div>`
    : '';
  const topN = ch.topN ?? 4;
  const top = ch.findings.slice(0, topN);
  const rest = ch.findings.slice(topN);
  const restHtml = rest.length
    ? `<div class="fcompact-lbl mono">WEITERE BEFUNDE</div><div class="fcompact">${rest.map(compactFinding).join('')}</div>`
    : '';
  return `<div class="chapter">
  ${headHtml}
  <div class="eyebrow2 mono">KAPITEL ${idx + 1} · ${esc(pillarLabel)}</div>
  <h2>${esc(ch.title)}</h2>
  <div class="lead ch-intro">${safeHtml(ch.intro)}</div>
  ${skillsHtml}
  <div class="findings">${top.map((f, i) => findingBlock(f, i)).join('')}</div>
  ${restHtml}
</div>`;
}

// ---------- new story-arc sections (all optional) ----------

function marketProfileSection(d, head) {
  const m = d.market || {};
  const p = d.profile || {};
  const callouts = (m.callouts || []).map((c) => `<div class="callout">
    <div class="cval disp">${esc(c.value)}${c.unit ? `<span class="cunit"> ${esc(c.unit)}</span>` : ''}</div>
    <div class="cbody">${safeHtml(c.body)}</div>
  </div>`).join('');
  const narrative = (m.narrative || []).map((para) => `<p class="lead">${safeHtml(para)}</p>`).join('');
  const rows = (p.rows || []).map((r) => `<div class="prow"><span class="pk mono">${esc(r.k)}</span><span class="pv">${esc(r.v)}</span></div>`).join('');
  return `<div class="chapter">
  ${head}
  ${m.eyebrow ? `<div class="eyebrow2 mono">${esc(m.eyebrow)}</div>` : ''}
  ${m.headline ? `<h2>${esc(m.headline.replace(/\s*\.\s*$/, ''))}<span class="dot">.</span></h2>` : ''}
  ${narrative}
  ${callouts ? `<div class="callouts">${callouts}</div>` : ''}
  ${p.eyebrow ? `<div class="eyebrowmini mono">${esc(p.eyebrow)}</div>` : ''}
  ${rows ? `<div class="pgrid">${rows}</div>` : ''}
  ${p.positioningLine ? `<div class="posline">${safeHtml(p.positioningLine)}</div>` : ''}
  ${p.note ? `<div class="pnote">${esc(p.note)}</div>` : ''}
</div>`;
}

function quadrantSection(d, head) {
  const p = d.positioning;
  const PL = 72, PR = 612, PT = 40, PB = 380;
  const W = PR - PL, H = PB - PT, CX = (PL + PR) / 2, CY = (PT + PB) / 2;
  const hqMap = { tl: [PL, PT], tr: [CX, PT], bl: [PL, CY], br: [CX, CY] };
  const hq = hqMap[p.highlightQuadrant] || null;
  const hl = hq ? `<rect x="${hq[0]}" y="${hq[1]}" width="${W / 2}" height="${H / 2}" fill="#E6ECFA" opacity="0.6"></rect>` : '';
  const tierFill = { self: '#E2381B', direct: '#1F3F8F', heritage: '#888780', indirect: 'none' };
  const pts = (p.points || []).map((pt) => {
    const px = PL + (pt.x || 0) * W, py = PT + (pt.y || 0) * H;
    const isSelf = pt.tier === 'self';
    const r = isSelf ? 8 : 5;
    const fill = tierFill[pt.tier] || '#1F3F8F';
    const circle = fill === 'none'
      ? `<circle cx="${px}" cy="${py}" r="${r}" fill="none" stroke="#5A5E57" stroke-width="1.4"></circle>`
      : `<circle cx="${px}" cy="${py}" r="${r}" fill="${fill}"></circle>`;
    const labelFill = pt.tier === 'indirect' ? '#5A5E57' : '#14150F';
    const labelAttr = isSelf ? `fill="${labelFill}" style="font-size:12.5px;font-weight:600"` : `fill="${labelFill}" style="font-size:11px"`;
    // Flip labels to the left for points near the right plot edge so long names don't clip off-page.
    const flip = px > PR - 140;
    const off = isSelf ? 14 : 10;
    const lblX = flip ? px - off : px + off;
    const anchorAttr = flip ? ' text-anchor="end"' : '';
    return `${circle}<text x="${lblX}" y="${py + 3}"${anchorAttr} ${labelAttr}>${esc(pt.label)}</text>`;
  }).join('');
  const ax = p.axisX || {}, ay = p.axisY || {};
  const legend = [
    [d.shop || 'Shop', '#E2381B', false],
    ['Direkte Wettbewerber', '#1F3F8F', false],
    ['Heritage', '#888780', false],
    ['Indirekt / Marktplatz', null, true],
  ].map(([lab, col, open]) => `<span class="qleg"><span class="qdot" style="${open ? 'border:1.4px solid #5A5E57' : `background:${col}`}"></span>${esc(lab)}</span>`).join('');
  return `<div class="chapter">
  ${head}
  ${p.eyebrow ? `<div class="eyebrow2 mono">${esc(p.eyebrow)}</div>` : ''}
  <h2>${esc(p.headline || '')}</h2>
  ${p.intro ? `<p class="lead">${safeHtml(p.intro)}</p>` : ''}
  <svg viewBox="0 0 640 430" width="100%" style="margin-top:8mm" role="img">
    ${hl}
    <line x1="${PL}" y1="${PT}" x2="${PL}" y2="${PB}" stroke="#14150F" stroke-width="1"></line>
    <line x1="${PL}" y1="${PB}" x2="${PR}" y2="${PB}" stroke="#14150F" stroke-width="1"></line>
    <line x1="${CX}" y1="${PT}" x2="${CX}" y2="${PB}" stroke="#14150F" stroke-opacity="0.15" stroke-width="1"></line>
    <line x1="${PL}" y1="${CY}" x2="${PR}" y2="${CY}" stroke="#14150F" stroke-opacity="0.15" stroke-width="1"></line>
    <text x="${CX}" y="30" text-anchor="middle" class="mono" fill="#5A5E57" style="font-size:9.5px">${esc(ay.top || '')}</text>
    <text x="${CX}" y="404" text-anchor="middle" class="mono" fill="#5A5E57" style="font-size:9.5px">${esc(ay.bottom || '')}</text>
    <text x="58" y="${CY}" text-anchor="middle" transform="rotate(-90 58 ${CY})" class="mono" fill="#5A5E57" style="font-size:9.5px">${esc(ax.left || '')}</text>
    <text x="626" y="${CY}" text-anchor="middle" transform="rotate(90 626 ${CY})" class="mono" fill="#5A5E57" style="font-size:9.5px">${esc(ax.right || '')}</text>
    ${pts}
  </svg>
  <div class="quad-legend">${legend}${p.note ? `<span class="qnote">${esc(p.note)}</span>` : ''}</div>
</div>`;
}

function matrixSection(d, head) {
  const m = d.matrix;
  const cols = m.columns || [];
  const headCells = cols.map((c, i) => `<td class="mh${i === 0 ? ' mself' : ''}">${esc(c)}</td>`).join('');
  const body = (m.capabilities || []).map((cap) => {
    const cells = (cap.ratings || []).map((r, i) => `<td class="mcell${i === 0 ? ' mself' : ''}">${hb(r)}</td>`).join('');
    return `<tr><td class="mcap">${esc(cap.label)}</td>${cells}</tr>`;
  }).join('');
  return `<div class="chapter">
  ${head}
  ${m.eyebrow ? `<div class="eyebrow2 mono">${esc(m.eyebrow)}</div>` : ''}
  <h2>${esc(m.headline || '')}</h2>
  ${m.intro ? `<p class="lead">${safeHtml(m.intro)}</p>` : ''}
  <table class="mtx"><thead><tr><td></td>${headCells}</tr></thead><tbody>${body}</tbody></table>
  <div class="mlegend"><span>${hb(2)} stark / führend</span><span>${hb(1)} solide / vorhanden</span><span>${hb(0)} schwach / fehlt</span></div>
  ${m.takeaway ? `<div class="mtake">${safeHtml(m.takeaway)}</div>` : ''}
</div>`;
}

// triage renders INSIDE the combined strategy+fahrplan section (no own page break), so the short
// triage and the roadmap share one well-filled page instead of two sparse ones.
function triageInner(t) {
  const cols = (t.columns || []).map((c) => `<div class="tcol">
    <div class="tlbl mono">${esc(c.label)}</div>
    <ul>${(c.items || []).map((it) => `<li>${esc(it)}</li>`).join('')}</ul>
  </div>`).join('');
  return `${t.eyebrow ? `<div class="eyebrow2 mono">${esc(t.eyebrow)}</div>` : ''}
  <h2>${esc(t.headline || '')}</h2>
  <div class="triage">${cols}</div>`;
}

function leversSection(l, head, tail = '') {
  const pillClass = (r) => ({ OFFEN: 'pill-open', 'TEILWEISE': 'pill-part', VORREITER: 'pill-lead' }[(r || '').toUpperCase()] || 'pill-part');
  const rows = (l.rows || []).map((r) => `<tr>
    <td class="lh">${esc(r.hebel)}</td>
    <td>${esc(r.wirkung)}</td>
    <td><span class="pill ${pillClass(r.reife)} mono">${esc(r.reife)}</span></td>
  </tr>`).join('');
  return `<div class="chapter">
  ${head}
  ${l.eyebrow ? `<div class="eyebrow2 mono">${esc(l.eyebrow)}</div>` : ''}
  <h2>${esc(l.headline || '')}</h2>
  ${l.intro ? `<p class="lead">${safeHtml(l.intro)}</p>` : ''}
  <table class="lev"><thead><tr><th>HEBEL</th><th>WIRKUNG</th><th>STAND HEUTE</th></tr></thead><tbody>${rows}</tbody></table>${tail}
</div>`;
}

function sourcesSection(s, head, tail = '') {
  const groups = (s.groups || []).map((g) => `<div class="srcgroup">
    <div class="sgt mono">${esc(g.title)}</div>
    ${(g.items || []).map((it) => `<div class="srcitem"><div class="sl">${esc(it.label)}</div>${it.url ? `<div class="su">${esc(it.url)}</div>` : ''}</div>`).join('')}
  </div>`).join('');
  return `<div class="chapter">
  ${head}
  ${s.eyebrow ? `<div class="eyebrow2 mono">${esc(s.eyebrow)}</div>` : ''}
  <h2>${esc(s.headline || '')}</h2>
  <div class="srcgrid">${groups}</div>
  ${s.methodik ? `<div class="methodik">${esc(s.methodik)}</div>` : ''}${tail}
</div>`;
}

// ---------- Schluss: Schlussseite des Betreibers oder neutraler Schluss ----------
//
// Entscheidung vom 15.09.2026, zweiter Teil: jedes Dokument des Plugins endet
// mit derselben Schlussseite, auch dieser Report. Sie liegt als HTML-Datei
// außerhalb des Repos, PTAI_CLOSING_FILE zeigt darauf, und ihr Inhalt wird
// unverändert als letzte Seite eingesetzt, ohne ihn zu lesen. Ohne sie endet der
// Report mit dem neutralen Schluss aus scripts/audit/closing.py: dieselben
// Fakten und Regeln, im Satz dieses Reports. Bis dahin stand hier ein fester
// Schluss mit Porträt, Kontaktzeilen, Terminlink und Stationen eines einzelnen
// Betreibers.
//
// Gesucht wird wie in db.mjs: zuerst die Umgebung, dann die zentrale Datei aus
// PTAI_ENV_FILE, sonst ~/.config/ptai-ecom/.env. Ein leeres PTAI_ENV_FILE heißt
// "keine zentrale Datei" (`??`, nicht `||`). Einen Workspace hat audit-light
// nicht. Aufgelöst wird beim Rendern, nie beim Laden des Moduls.

const ENV_LINE = /^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$/;

/** Die Suche nach Einstellungen des Betreibers: Umgebung, dann zentrale Datei. */
export function operatorSettings(env = process.env) {
  let central = null;
  return (name) => {
    if (env[name]) return env[name];
    if (central === null) {
      central = {};
      try {
        const text = readFileSync(env.PTAI_ENV_FILE ?? join(homedir(), '.config', 'ptai-ecom', '.env'), 'utf8');
        for (const line of text.split('\n')) {
          // Umschließende Quotes weg, ein leerer Wert zählt nicht, der letzte gewinnt.
          const m = line.match(ENV_LINE);
          const value = m ? m[2].replace(/^(["'])(.*)\1$/, '$2') : '';
          if (value) central[m[1]] = value;
        }
      } catch { /* keine zentrale Datei, dann bleibt es bei der Umgebung */ }
    }
    return central[name];
  };
}

const ORIGIN_HTML = 'Erstellt mit ptai-ecom von <a href="https://path-to-ai.com">Path to AI</a>.';

// Eine Adresse der Form name@beispiel.example, wie `_EMAIL` in closing.py. Dort
// ist \w Unicode, hier deshalb \p{L}\p{N}_.
const EMAIL = /^[\p{L}\p{N}_.%+-]+@[\p{L}\p{N}_-]+(?:\.[\p{L}\p{N}_-]+)+$/u;

const settingValue = (setting, name) => String(setting(name) ?? '').trim();

// Der Terminlink, nur mit http oder https und einem Host, wie urlsplit in
// closing.py. Alles andere fällt weg statt im href zu landen, auch javascript:.
function bookingUrl(value) {
  if (!value || /\s/.test(value)) return null;
  const m = /^([A-Za-z][A-Za-z0-9+.-]*):\/\/([^/?#]*)/.exec(value);
  if (!m || !['http', 'https'].includes(m[1].toLowerCase()) || !m[2]) return null;
  if (m[2].includes('[') !== m[2].includes(']')) return null;
  return value;
}

// Sichtbarer Linktext: ohne Schema, ohne Schrägstrich am Ende.
const linkText = (url) => url.replace(/^https?:\/\//, '').replace(/\/+$/, '');

const contactRow = (label, valueHtml) =>
  `<div class="contact-row"><div class="ck mono">${label}</div><div class="cv">${valueHtml}</div></div>`;

// Eine Kontaktzeile je gesetztem und gültigem Wert, darunter immer die
// Herkunftszeile, kein Satz. Der Firmenname nur, wenn er ausdrücklich gesetzt ist.
function neutralClosing(setting, head) {
  const name = settingValue(setting, 'PTAI_OPERATOR_NAME');
  const contact = settingValue(setting, 'PTAI_OPERATOR_CONTACT');
  const email = settingValue(setting, 'PTAI_OPERATOR_EMAIL');
  const url = bookingUrl(settingValue(setting, 'PTAI_OPERATOR_BOOKING_URL'));
  const rows = [];
  if (name) rows.push(contactRow('Unternehmen', esc(name)));
  if (contact) rows.push(contactRow('Ansprechpartner', esc(contact)));
  if (EMAIL.test(email)) rows.push(contactRow('E-Mail', `<a href="mailto:${esc(email)}">${esc(email)}</a>`));
  if (url) rows.push(contactRow('Termin', `<a href="${esc(url)}">${esc(linkText(url))}</a>`));
  const contactBlock = rows.length
    ? `\n  <div class="eyebrow2 mono">Kontakt</div>\n  <div class="contact-rows">${rows.join('')}</div>`
    : '';
  return `<section class="closing">
  ${head}${contactBlock}
  <p class="fine">${ORIGIN_HTML}</p>
</section>`;
}

// Die Schlussseite aus PTAI_CLOSING_FILE, unverändert, oder null. Ist die
// Einstellung gesetzt, die Datei aber nicht brauchbar, meldet `warn` das in
// einer Zeile, und der Report bekommt den neutralen Schluss.
function closingFile(setting, warn) {
  const value = settingValue(setting, 'PTAI_CLOSING_FILE');
  if (!value) return null;
  const path = value === '~' ? homedir() : value.startsWith('~/') ? join(homedir(), value.slice(2)) : value;
  let reason;
  try {
    // fatal: eine Datei, die kein UTF-8 ist, gilt wie in closing.py als nicht lesbar.
    const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(readFileSync(path));
    if (text.trim()) return text;
    reason = 'ist leer';
  } catch (err) {
    reason = err?.code === 'ENOENT' ? 'gibt es nicht' : 'ist nicht lesbar';
  }
  warn(`Hinweis: PTAI_CLOSING_FILE zeigt auf ${value}, die Datei ${reason}. Das Dokument endet mit dem neutralen Schluss.`);
  return null;
}

// ---------- main renderer ----------

// `setting` und `warn` lassen sich für Tests ersetzen. Ohne sie gelten die
// Einstellungen zum Zeitpunkt des Renderns, und Warnungen gehen auf stderr.
export function renderReportHtml(d, { setting = operatorSettings(), warn = (message) => console.error(message) } = {}) {
  const head = `<div class="phead"><span class="wm">Path to AI<span class="dot">.</span></span><span class="mono vt">VERTRAULICH · FÜR ${esc(d.meta?.erstelltFuer || d.shop)}</span></div>`;

  const takeawaysList = d.exec.takeaways && d.exec.takeaways.length
    ? `<ul class="takeaways">${d.exec.takeaways.map((t) => `<li>${esc(t)}</li>`).join('')}</ul>`
    : '';

  // Der Kleindruck steht am Ende der letzten Inhaltsseite: die Schlussseite
  // gehört dem Betreiber, und mit PTAI_CLOSING_FILE fiele er sonst weg. Das
  // Copyright nennt den Betreiber, nur wenn PTAI_OPERATOR_NAME ausdrücklich
  // gesetzt ist, sonst entfällt der Satz. Bis zum 15.09.2026 stand hier fest ein
  // einzelner Betreiber, in jedem Report jedes Betreibers.
  const operator = settingValue(setting, 'PTAI_OPERATOR_NAME');
  const copyright = operator ? ` © ${esc(d.meta?.year || '2026')} ${esc(operator)}.` : '';
  const fine = `<div class="fine">Dieser Audit basiert auf öffentlich zugänglichen Daten von ${esc(d.shop)} (Stand ${esc(d.meta?.stand || '')}) und mehreren strukturierten Audits: SEO, E-Commerce, KI-Sichtbarkeit/GEO und Wettbewerb. Mit „~"/„Schätzung" markierte Werte sind Orientierung, keine geprüften Zahlen. Die Scores sind Orientierung, keine Garantie.${copyright}</div>`;
  const last = d.sources ? 'sources' : d.levers ? 'levers' : 'fahrplan';
  const closing = closingFile(setting, warn) ?? neutralClosing(setting, head);

  return `<!doctype html><html lang="de"><head><meta charset="utf-8">
<style>
${FONT_FACE_CSS}

/* ---- PRINT / PAGE SETUP ---- */
@page { size: A4; margin: 0; }
* { box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; margin: 0; }

/* ---- DESIGN TOKENS (Styleguide von Path to AI: weisser Grund, ein lautes Rot, ein ruhiges Blau) ---- */
:root {
  --paper: #FFFFFF;
  --ink:   #14150F;
  --ink-80: rgba(20,21,15,.80);
  --ink-soft: #5A5E57;
  --accent: #E2381B;        /* laut: grosse Typo, Marker, Flächen ohne Kleintext */
  --accent-deep: #C62F14;   /* Buttons, Links, Kleintext */
  --blue: #1F3F8F;          /* ruhig: Labels, Links, positive Signale */
  --blue-wash: #E6ECFA;     /* Callout-Flächen */
  --line: rgba(20,21,15,.13);
}
html, body { font-family: 'Inter', system-ui, sans-serif; color: var(--ink); background: var(--paper); }
.disp  { font-family: 'Archivo', system-ui, sans-serif; font-weight: 900; letter-spacing: -0.02em; }
.mono  { font-family: 'JetBrains Mono', monospace; }
code   { font-family: 'JetBrains Mono', monospace; font-size: .9em; background: rgba(31,63,143,.08); color: var(--blue); padding: .05em .35em; border-radius: 3px; }
.dot   { color: var(--accent); }
.wm    { font-family: 'Archivo', system-ui, sans-serif; font-weight: 900; font-style: italic; text-transform: uppercase; letter-spacing: -0.015em; }

/* ---- COVER — full-bleed dark page ---- */
.cover { width: 210mm; height: 297mm; padding: 20mm 18mm; position: relative; overflow: hidden; page-break-after: always; background: var(--ink); color: var(--paper); }
.cover .wm { font-size: 21px; color: var(--paper); }
.cover .eyebrow { display: flex; align-items: center; gap: 14px; margin-top: 120mm; font-size: 11px; letter-spacing: .22em; color: rgba(255,255,255,.7); }
.cover .eyebrow .ln { width: 34px; height: 2px; background: var(--accent); }
.cover h1 { font-family: 'Archivo', system-ui, sans-serif; font-weight: 900; font-style: italic; letter-spacing: -0.02em; font-size: 44px; line-height: 1.02; margin-top: 14px; color: var(--paper); }
.cover .intro { font-size: 16px; line-height: 1.55; color: rgba(255,255,255,.82); max-width: 128mm; margin-top: 20px; }
.cover .ghost { position: absolute; right: -16mm; bottom: -42mm; font-family: 'Archivo', system-ui, sans-serif; font-weight: 900; font-style: italic; font-size: 400px; line-height: 1; color: rgba(255,255,255,.09); }
.cover .meta { position: absolute; left: 18mm; right: 18mm; bottom: 18mm; display: flex; gap: 24px; border-top: 1px solid rgba(255,255,255,.18); padding-top: 14px; }
.cover .meta .mb { flex: 1; }
.cover .meta .mk { font-size: 9.5px; letter-spacing: .18em; color: rgba(255,255,255,.55); }
.cover .meta .mv { font-size: 13px; color: var(--paper); margin-top: 6px; }

/* ---- SECTION HEADER ---- */
.phead { display: flex; justify-content: space-between; align-items: baseline; border-bottom: 1px solid rgba(20,21,15,.12); padding-bottom: 8px; }
.phead .wm { font-size: 15px; color: var(--ink); }
.phead .vt { font-size: 10px; letter-spacing: .16em; color: var(--ink-soft); }

/* ---- FLOWING SECTIONS ---- */
.section, .chapter { padding: 16mm 16mm 14mm; -webkit-box-decoration-break: clone; box-decoration-break: clone; }
.chapter { page-break-before: always; }
.fcard, .scol, .stage, .proj, .callout, .tcol, .srcgroup { break-inside: avoid; }
svg { break-inside: avoid; }

/* ---- TYPOGRAPHY ---- */
.eyebrow2 { font-size: 10.5px; letter-spacing: .18em; color: var(--blue); margin-top: 8mm; }
h2 { font-family: 'Archivo', system-ui, sans-serif; font-weight: 900; font-style: italic; letter-spacing: -0.02em; font-size: 27px; line-height: 1.06; color: var(--ink); margin-top: 10px; }
.lead { font-size: 14px; line-height: 1.6; color: var(--ink-80); margin-top: 14px; }
.lead .hl, .ch-intro .hl { color: var(--ink); font-weight: 500; }

/* ---- EXECUTIVE SCORES ---- */
.scores { display: flex; gap: 10mm; margin-top: 16mm; }
.scol { flex: 1; }
.scol .lbl { font-size: 10px; letter-spacing: .12em; color: var(--ink-soft); border-top: 2px solid var(--ink); padding-top: 10px; }
.scol .num { font-family: 'Archivo', system-ui, sans-serif; font-weight: 900; letter-spacing: -0.02em; font-size: 44px; color: var(--ink); line-height: 1; margin-top: 8px; }
.scol .den { font-size: 18px; color: var(--ink-soft); }
.bar { position: relative; height: 6px; background: rgba(20,21,15,.10); margin-top: 18px; }
.bar .fill { height: 100%; background: var(--blue); }
.bar .mark { position: absolute; top: -3px; width: 2px; height: 12px; background: var(--accent-deep); transform: translateX(-1px); }
.bar .goal { position: absolute; top: -18px; font-size: 9px; color: var(--accent-deep); transform: translateX(-50%); white-space: nowrap; }
.scol .cap { font-size: 12.5px; line-height: 1.5; color: var(--ink-soft); margin-top: 14px; }

/* ---- POTENZIAL-VARIANTE (exec.scoreStyle === 'potenzial') + STÄRKEN ---- */
.pot { font-size: 9px; letter-spacing: .14em; color: var(--blue); margin-top: 8px; }
.sgrid { display: flex; gap: 8mm; margin-top: 6mm; break-inside: avoid; }
.sitem { flex: 1; font-size: 12.5px; line-height: 1.5; color: var(--ink); border-top: 2px solid var(--blue); padding-top: 10px; }
.scheck { color: var(--blue); font-weight: 600; margin-right: 6px; }
.cto { font-family: 'Archivo', system-ui, sans-serif; font-weight: 900; letter-spacing: -0.015em; font-size: 21px; color: var(--blue); line-height: 1.1; }

/* ---- AMPEL-VARIANTE (exec.scoreStyle === 'ampel') ---- */
.ampel { display: flex; gap: 8px; align-items: center; margin-top: 16px; }
.ampel .ad { border-radius: 50%; display: inline-block; box-sizing: border-box; }
.ampel .ad.on { transform: scale(1.3); }
.aword { font-family: 'Archivo', system-ui, sans-serif; font-weight: 900; letter-spacing: -0.015em; font-size: 22px; color: var(--ink); line-height: 1.1; margin-top: 10px; }
.agoal { font-size: 9px; letter-spacing: .14em; color: var(--ink-soft); margin-top: 8px; }
.composite .ampel { margin-top: 0; }

/* ---- COMPOSITE SCORE ---- */
.composite { display: flex; align-items: baseline; gap: 16px; margin-top: 16mm; border-top: 2px solid var(--ink); padding-top: 14px; }
.composite .cnum { font-family: 'Archivo', system-ui, sans-serif; font-weight: 900; letter-spacing: -0.02em; font-size: 50px; color: var(--ink); line-height: .9; }
.composite .cden { font-size: 22px; color: var(--ink-soft); }
.composite .clbl { font-size: 10px; letter-spacing: .14em; color: var(--ink-soft); line-height: 1.5; text-transform: uppercase; }

/* ---- TAKEAWAYS ---- */
.takeaways { list-style: none; padding: 0; margin-top: 12mm; }
.takeaways li { font-size: 13px; line-height: 1.55; color: var(--ink-80); padding-left: 18px; position: relative; margin-bottom: 10px; }
.takeaways li:before { content: ''; position: absolute; left: 0; top: 7px; width: 6px; height: 6px; background: var(--accent-deep); border-radius: 50%; }

/* ---- MARKET CALLOUTS (Hauptpotenziale) ---- */
.callouts { display: flex; gap: 8mm; margin-top: 14mm; }
.callout { flex: 1; border-top: 2px solid var(--accent-deep); padding-top: 12px; }
.callout .cval { font-size: 30px; line-height: 1; color: var(--ink); }
.callout .cunit { font-size: 15px; color: var(--ink-soft); }
.callout .cbody { font-size: 12px; line-height: 1.5; color: var(--ink-80); margin-top: 8px; }
.callout .cbody b { color: var(--ink); }

/* ---- PROFILE / COMPANY CARD ---- */
.eyebrowmini { font-size: 10px; letter-spacing: .16em; color: var(--blue); margin-top: 16mm; }
.pgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 14mm; margin-top: 10px; }
.prow { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; border-bottom: .5px solid rgba(20,21,15,.14); padding: 9px 0; }
.prow .pk { letter-spacing: .10em; font-size: 9.5px; color: var(--ink-soft); white-space: nowrap; }
.prow .pv { font-size: 12.5px; color: var(--ink); text-align: right; }
.posline { background: var(--blue-wash); padding: 12px 16px; margin-top: 14px; font-size: 13px; line-height: 1.5; color: var(--ink); }
.posline b { font-weight: 600; }
.pnote { font-size: 9px; color: var(--ink-soft); margin-top: 12px; }

/* ---- QUADRANT ---- */
.quad-legend { display: flex; flex-wrap: wrap; gap: 14px; border-top: .5px solid rgba(20,21,15,.12); padding-top: 10px; margin-top: 6px; align-items: center; }
.qleg { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--ink-80); }
.qdot { width: 10px; height: 10px; border-radius: 50%; }
.qnote { font-size: 9.5px; color: var(--ink-soft); margin-left: auto; }

/* ---- COMPARISON MATRIX ---- */
.mtx { width: 100%; border-collapse: collapse; margin-top: 10mm; table-layout: fixed; }
.mtx td { padding: 11px 0; }
.mtx thead .mh { font-size: 9.5px; letter-spacing: .08em; color: var(--ink-soft); text-align: center; }
.mtx .mself { background: rgba(226,56,27,.06); }
.mtx .mcap { font-size: 12.5px; color: var(--ink); padding-right: 8px; width: 32%; }
.mtx tbody tr { border-top: .5px solid rgba(20,21,15,.12); }
.mtx .mcell { text-align: center; }
.mlegend { display: flex; gap: 18px; margin-top: 12px; font-size: 10px; color: var(--ink-soft); align-items: center; }
.mlegend span { display: flex; align-items: center; gap: 6px; }
.mtake { background: var(--blue-wash); padding: 14px 18px; margin-top: 12mm; font-size: 13px; line-height: 1.55; color: var(--ink); }
.mtake b { color: var(--blue); }

/* ---- STRATEGY TRIAGE ---- */
.triage { display: flex; gap: 8mm; margin-top: 12mm; }
.tcol { flex: 1; }
.tcol + .tcol { border-left: 1px solid rgba(20,21,15,.12); padding-left: 8mm; }
.tcol .tlbl { font-size: 10px; letter-spacing: .12em; color: var(--blue); }
.tcol ul { list-style: none; margin-top: 14px; }
.tcol li { font-size: 12px; line-height: 1.45; color: var(--ink-80); padding-left: 14px; position: relative; margin-bottom: 11px; }
.tcol li:before { content: ''; position: absolute; left: 0; top: 7px; width: 5px; height: 5px; background: var(--accent-deep); }

/* ---- AI LEVERS ---- */
.lev { width: 100%; border-collapse: collapse; margin-top: 10mm; }
.lev th { text-align: left; font-size: 9.5px; letter-spacing: .10em; color: var(--ink-soft); font-weight: 400; padding-bottom: 8px; border-bottom: 1px solid rgba(20,21,15,.12); }
.lev td { padding: 13px 0; border-bottom: .5px solid rgba(20,21,15,.12); font-size: 12.5px; color: var(--ink-80); vertical-align: top; }
.lev td:nth-child(2) { padding-left: 8px; padding-right: 8px; }
.lev .lh { font-weight: 500; color: var(--ink); }
.pill { display: inline-block; font-size: 9px; letter-spacing: .08em; padding: 4px 9px; border-radius: 3px; white-space: nowrap; }
.pill-open { background: rgba(226,56,27,.10); color: var(--accent-deep); }
.pill-part { background: rgba(20,21,15,.06); color: var(--ink-soft); }
.pill-lead { background: rgba(31,63,143,.10); color: var(--blue); }

/* ---- SOURCES & METHODOLOGY ---- */
.srcgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 8mm 12mm; margin-top: 10mm; }
.srcgroup .sgt { font-size: 9.5px; letter-spacing: .10em; color: var(--blue); border-bottom: 1px solid rgba(20,21,15,.12); padding-bottom: 6px; }
.srcitem { padding: 8px 0; border-bottom: .5px solid rgba(20,21,15,.10); }
.srcitem .sl { font-size: 12px; color: var(--ink); }
.srcitem .su { font-size: 9px; color: var(--ink-soft); word-break: break-all; margin-top: 3px; }
/* Der Methodik-Block steht am Fuss der Quellenseite und ist nur wenige Zeilen hoch.
   Ohne avoid reisst Chrome ihn mitten im Satz auf und schiebt zwei Zeilen auf eine
   sonst leere Folgeseite. Wie bei .roadmap gilt: passt er nicht mehr, wandert er
   ganz auf die naechste Seite. */
.methodik { font-size: 10px; line-height: 1.5; color: var(--ink-soft); margin-top: 10mm; border-top: 1px solid rgba(20,21,15,.12); padding-top: 12px; break-inside: avoid; }

/* ---- FINDING BLOCKS ---- */
.findings { margin-top: 10mm; }
.fcard { display: flex; gap: 12px; padding: 16px 0; border-top: 1px solid rgba(20,21,15,.10); break-inside: avoid; }
.fcard:last-child { border-bottom: 1px solid rgba(20,21,15,.10); }
.fsev { width: 4px; flex-shrink: 0; border-radius: 2px; align-self: stretch; min-height: 14px; }
.fbody { flex: 1; }
.fhead { display: flex; justify-content: space-between; align-items: baseline; }
.fnum { font-size: 9.5px; letter-spacing: .14em; color: var(--blue); margin-bottom: 4px; }
.fbadge { font-size: 8.5px; letter-spacing: .10em; color: var(--ink-soft); border: .5px solid rgba(20,21,15,.2); padding: 2px 8px; border-radius: 3px; }
.ftitle { font-family: 'Archivo', system-ui, sans-serif; font-weight: 900; letter-spacing: -0.015em; font-size: 15.5px; line-height: 1.2; color: var(--ink); }
.ftext { font-size: 13px; line-height: 1.55; color: var(--ink-80); margin-top: 8px; }
.frec { font-size: 12.5px; line-height: 1.5; color: var(--ink); margin-top: 10px; }
.frec-lbl { font-size: 9px; letter-spacing: .14em; color: var(--ink-soft); display: block; margin-bottom: 2px; }
.fimpact { font-size: 12px; line-height: 1.5; color: var(--blue); margin-top: 8px; }
.fimpact .mono { font-size: 9.5px; letter-spacing: .12em; color: var(--ink-soft); display: block; margin-bottom: 2px; }
.fskill { font-size: 9px; letter-spacing: .10em; color: var(--ink-soft); margin-top: 6px; }
.floc { display: inline-block; font-size: 9.5px; letter-spacing: .04em; color: var(--accent-deep); text-decoration: none; margin-top: 8px; border-bottom: .5px solid rgba(198,47,20,.35); }

/* ---- COMPACT FINDINGS (the long tail) ---- */
.fcompact-lbl { font-size: 9.5px; letter-spacing: .14em; color: var(--ink-soft); margin-top: 10mm; }
.fcompact { margin-top: 6px; display: grid; grid-template-columns: 1fr 1fr; gap: 0 10mm; }
.fcrow { display: flex; gap: 8px; padding: 9px 0; border-top: .5px solid rgba(20,21,15,.10); break-inside: avoid; }
.fcrow .fcdot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; margin-top: 5px; }
.fcrow .fct { font-size: 11.5px; line-height: 1.35; color: var(--ink); }
.fcrow .fci { font-size: 10px; line-height: 1.4; color: var(--ink-soft); margin-top: 2px; }

/* ---- FAHRPLAN ---- */
.stages { display: flex; gap: 9mm; margin-top: 14mm; }
.stage { flex: 1; }
.stage + .stage { border-left: 1px solid rgba(20,21,15,.12); padding-left: 8mm; }
.slbl { font-size: 10px; letter-spacing: .12em; color: var(--blue); }
.stitle { font-family: 'Archivo', system-ui, sans-serif; font-weight: 900; letter-spacing: -0.015em; font-size: 16.5px; line-height: 1.15; color: var(--ink); margin-top: 8px; }
.stage ul { list-style: none; margin-top: 14px; }
.stage li { font-size: 12.5px; line-height: 1.45; color: var(--ink-80); padding-left: 14px; position: relative; margin-bottom: 11px; }
.stage li:before { content: ''; position: absolute; left: 0; top: 7px; width: 5px; height: 5px; background: var(--accent-deep); }
/* Der Fahrplan ist EINE Einheit: Überschrift, Lead, Etappen und Projektion gehören zusammen.
   Ohne diese Klammer zerlegt der Fragmentierer sie auf zwei Arten, beide gemessen über 22 Läufe:
   die Projektion landet allein auf einer sonst leeren Seite (12 Läufe), oder Überschrift und Lead
   bleiben unten auf der Vorseite stehen, während Etappen und Projektion umbrechen (6 Läufe).
   Passt die Einheit auf die laufende Seite, ändert die Klammer nichts; sonst wandert sie komplett
   auf die nächste. Ist sie höher als eine Seite, ignoriert Chrome das avoid und bricht wie bisher. */
.roadmap { break-inside: avoid; }
.proj { display: flex; gap: 24px; align-items: center; background: var(--blue-wash); padding: 20px 24px; margin-top: 14mm; break-inside: avoid; }
.proj .big { font-family: 'Archivo', system-ui, sans-serif; font-weight: 900; letter-spacing: -0.02em; font-size: 30px; color: var(--ink); white-space: nowrap; }
.proj .big .to { color: var(--accent-deep); }
.proj .plbl { font-size: 9.5px; letter-spacing: .14em; color: var(--ink-soft); margin-top: 4px; }
.proj .ptext { font-size: 13px; line-height: 1.55; color: var(--ink); }
.proj .ptext b { color: var(--blue); }

/* ---- SCHLUSS: der neutrale Schluss ohne PTAI_CLOSING_FILE, eine eigene Seite mit
   den Kontaktzeilen des Betreibers und darunter der Herkunftszeile ---- */
.closing { page-break-before: always; background: var(--paper); padding: 16mm 16mm 14mm; }
.closing .eyebrow2 { text-transform: uppercase; }
.contact-rows { margin-top: 6mm; max-width: 120mm; }
.contact-row { border-top: 1px solid var(--line); padding: 9px 0; }
.ck { font-size: 9px; letter-spacing: .16em; color: var(--ink-soft); text-transform: uppercase; }
.cv { font-size: 13px; color: var(--ink); margin-top: 3px; }
.cv a { color: inherit; text-decoration: none; }
/* Kleindruck: der Hinweis zur Datengrundlage am Ende der letzten Inhaltsseite und
   die Herkunftszeile im neutralen Schluss. */
.fine { font-size: 9px; line-height: 1.5; color: var(--ink-soft); margin-top: 4mm; border-top: 1px solid var(--line); padding-top: 8px; break-inside: avoid; }
.fine a { color: var(--accent-deep); text-decoration: none; }

ul { padding: 0; }
</style></head><body>

<!-- COVER -->
<section class="cover">
  <span class="wm">Path to AI<span class="dot">.</span></span>
  <div class="eyebrow"><span class="ln"></span><span class="mono">${d.cover?.eyebrow ? esc(d.cover.eyebrow) : 'E&#8209;COMMERCE&#8209;AUDIT · SEO · KI&#8209;SICHTBARKEIT · WETTBEWERB'}</span></div>
  <h1>${coverHeadline(d)}</h1>
  <p class="intro">${d.cover?.intro ? safeHtml(d.cover.intro) : `Ein ehrlicher Blick auf <b>${esc(d.shop)}</b>: klassisches SEO bei Google, Sichtbarkeit in der KI-Suche, eure Produktdaten und der direkte Vergleich mit dem Wettbewerb.`}</p>
  <div class="ghost">P</div>
  <div class="meta">
    <div class="mb"><div class="mk">ERSTELLT FÜR</div><div class="mv">${esc(d.meta?.erstelltFuer || d.shop)}</div></div>
    <div class="mb"><div class="mk">ANALYSIERT</div><div class="mv">${esc(d.shop)}</div></div>
    <div class="mb"><div class="mk">VON</div><div class="mv">Path to AI</div></div>
    <div class="mb"><div class="mk">STAND</div><div class="mv">${esc(d.meta?.stand || '')}</div></div>
  </div>
</section>

<!-- DER MARKT & SHOP AUF EINEN BLICK -->
${(d.market || d.profile) ? marketProfileSection(d, head) : ''}

<!-- EXECUTIVE SUMMARY -->
<section class="chapter">
  ${head}
  <div class="eyebrow2 mono">AUF EINEN BLICK</div>
  <h2>${esc(d.exec.headline)}</h2>
  ${d.exec.summary.map((p) => `<p class="lead">${safeHtml(p)}</p>`).join('')}
  ${d.exec.strengths?.length ? `<div class="eyebrow2 mono" style="margin-top:12mm">WAS SCHON STEHT</div><div class="sgrid">${d.exec.strengths.map((x) => `<div class="sitem"><span class="scheck">✓</span>${esc(x)}</div>`).join('')}</div>` : ''}
  ${d.exec.composite ? (d.exec.scoreStyle === 'potenzial'
    ? `<div class="composite"><div class="cnum">${d.exec.composite}<span class="cden">/100</span></div><div>${d.fahrplan?.proj?.to ? `<div class="cto">→ ${esc(d.fahrplan.proj.to)} erreichbar</div>` : ''}<div class="clbl mono">PTAI E-Com Score · heute und nach Umsetzung der Maßnahmen</div></div></div>`
    : d.exec.scoreStyle === 'ampel'
    ? `<div class="composite"><div>${ampelDots(ampelLevel(d.exec.composite), 18)}<div class="aword" style="font-size:44px">${esc(ampelLevel(d.exec.composite).word)}</div></div><div class="clbl mono">GESAMT-STATUS<br>ÜBER ALLE DREI SÄULEN</div></div>`
    : `<div class="composite"><div class="cnum">${d.exec.composite}<span class="cden">/100</span></div><div class="clbl mono">GESAMT-SCORE<br>ÜBER ALLE DREI SÄULEN</div></div>`) : ''}
  <div class="scores">${d.exec.scores.map((s) => scoreCol(s, d.exec.scoreStyle)).join('')}</div>
  ${takeawaysList}
</section>

<!-- EUER QUADRANT -->
${d.positioning ? quadrantSection(d, head) : ''}

<!-- IM VERGLEICH -->
${d.matrix ? matrixSection(d, head) : ''}

<!-- MASSNAHMEN — chapters, top-first + compact tail -->
${d.chapters.map((ch, i) => chapterSection(ch, i, head)).join('\n')}

<!-- STRATEGIE & FAHRPLAN -->
<section class="chapter">
  ${head}
  ${d.triage ? triageInner(d.triage) : ''}
  <div class="roadmap">
  <div class="eyebrow2 mono"${d.triage ? ' style="margin-top:18mm"' : ''}>DER WEG NACH VORN</div>
  <h2>${esc(d.fahrplan.headline)}</h2>
  <p class="lead">${esc(d.fahrplan.lead)}</p>
  <div class="stages">${d.fahrplan.stages.map(stageCol).join('')}</div>
  ${d.fahrplan.proj ? (d.exec.scoreStyle === 'ampel'
    ? `<div class="proj"><div><div class="big" style="font-size:26px"><span style="color:${ampelLevel(parseInt(d.fahrplan.proj.from, 10)).color}">●</span> ${esc(ampelLevel(parseInt(d.fahrplan.proj.from, 10)).word)} <span style="color:#5A5E57">→</span> <span style="color:${ampelLevel(parseInt(d.fahrplan.proj.to, 10)).color}">●</span> ${esc(ampelLevel(parseInt(d.fahrplan.proj.to, 10)).word)}</div><div class="plbl">${esc(d.fahrplan.proj.label)}</div></div><div class="ptext">${safeHtml(d.fahrplan.proj.text)}</div></div>`
    : `<div class="proj"><div><div class="big">${esc(d.fahrplan.proj.from)} <span style="color:#5A5E57">→</span> <span class="to">${esc(d.fahrplan.proj.to)}</span></div><div class="plbl">${esc(d.fahrplan.proj.label)}</div></div><div class="ptext">${safeHtml(d.fahrplan.proj.text)}</div></div>`) : ''}
  </div>${last === 'fahrplan' ? fine : ''}
</section>

<!-- WO WIR ANDOCKEN -->
${d.levers ? leversSection(d.levers, head, last === 'levers' ? fine : '') : ''}

<!-- QUELLEN & METHODIK -->
${d.sources ? sourcesSection(d.sources, head, fine) : ''}

<!-- SCHLUSS: Schlussseite aus PTAI_CLOSING_FILE oder neutraler Schluss -->
${closing}

</body></html>`;
}
