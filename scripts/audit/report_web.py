#!/usr/bin/env python3
"""Die Web-Fassung des Audits: dieselben Inhalte, andere Navigation.

Zwei Fassungen sind belegte Praxis, keine Bequemlichkeit. IIA Global Internal
Audit Standards 15.1: *"Multiple versions of a final communication may be
issued, with formats, content, and level of detail customized to address
specific audiences."* Das PDF ist das Dokument, das man weitergibt und
ausdruckt; diese Fassung ist die, in der man arbeitet: springen, filtern,
suchen.

**Der Inhalt kommt aus `report_build.content()`, nie aus einem zweiten
Builder.** Zwei Builder waeren zwei Wahrheiten, und die erste Zahl, die nur in
einer von beiden korrigiert wird, faellt niemandem auf.

Alles steht in einer Datei: kein CDN, kein externes Skript, keine Schrift von
aussen. Die Seite muss auch dann funktionieren, wenn sie in einem Jahr aus
einem Ordner heraus geoeffnet wird.

**Der Schluss ist derselbe wie in der Druckfassung.** Unter dem Inhalt steht
dasselbe Panel zwischen denselben Markierungen, und `closing.apply` setzt dort
die Schlussseite aus `PTAI_CLOSING_FILE` oder den neutralen Schluss ein. Auf dem
Schirm steht die A4-Seite des Betreibers mittig in einem eigenen Band, mit
Abstand darüber; die Regeln dafür gibt es nur hier, die Datei selbst bleibt
unverändert. Bis zum 15.09.2026 hatte die Web-Fassung keinen Schluss, und das
Portal zeigt sie vor der Druckfassung: wer den Audit dort las, sah ihn nie.
"""
from __future__ import annotations

import argparse
import base64
import re
import sys
from pathlib import Path

from audit import closing
from audit import report_build as rb

# Die Marke, so weit sie ohne Schriftdateien traegt. Die Web-Fassung laedt
# bewusst keine Fonts: eine Datei, die offline funktioniert, schlaegt eine,
# die im richtigen Schnitt gesetzt ist und im Zweifel gar nicht laedt.
#: Die vier Schnitte, die die Marke traegt. Sie werden als data-URI in die
#: Datei eingebettet, nicht verlinkt: die Seite muss auch dann richtig
#: aussehen, wenn sie in einem Jahr aus einem Ordner heraus geoeffnet wird,
#: und ein relativer Font-Pfad ueberlebt das erste Verschieben nicht.
FONTS = (
    ("Archivo Black", 400, "normal", "archivo-black.woff2"),
    ("Inter", 400, "normal", "inter-regular.woff2"),
    ("Inter", 600, "normal", "inter-semibold.woff2"),
    ("JetBrains Mono", 500, "normal", "jetbrains-mono-medium.woff2"),
)


def _fonts(assets: Path) -> str:
    regeln = []
    for familie, gewicht, stil, filename in FONTS:
        pfad = assets / "fonts" / filename
        if not pfad.exists():
            continue
        b64 = base64.b64encode(pfad.read_bytes()).decode("ascii")
        regeln.append(
            f"@font-face{{font-family:'{familie}';font-weight:{gewicht};"
            f"font-style:{stil};font-display:swap;"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2')}}")
    return "".join(regeln)


def _logo(assets: Path, filename: str = "logo.svg", css_class: str = "logo") -> str:
    """Ein Logo inline, damit die Datei ohne Nachbarn funktioniert."""
    pfad = assets / filename
    if not pfad.exists():
        return ""
    svg = pfad.read_text(encoding="utf-8")
    svg = re.sub(r"<\?xml.*?\?>", "", svg, flags=re.S).strip()
    return re.sub(r"<svg ", f'<svg class="{css_class}" ', svg, count=1)


#: Die Marke, uebernommen aus assets/brand/report.css. Bewusst dieselben
#: Farbwerte und dieselbe Schriftrolle: bis zum 07.09.2026 hatte die
#: Web-Fassung ein eigenes Stylesheet mit eigenen Farben, und sie sah nicht
#: nach Path to AI aus. Yves dazu: *"Warum ist das nicht CI?"*
STYLE = """
:root{
 --p2a-paper:#FFFFFF;--p2a-surface:#F5F5F2;--p2a-ink:#14150F;
 --p2a-ink-soft:#5A5E57;--p2a-accent:#E2381B;--p2a-accent-deep:#C62F14;
 --p2a-blue:#1F3F8F;--p2a-blue-wash:#E6ECFA;--p2a-rule:rgba(20,21,15,.13);
 --p2a-font-display:'Archivo Black','Archivo',system-ui,sans-serif;
 --p2a-font-body:'Inter',system-ui,-apple-system,'Segoe UI',sans-serif;
 --p2a-font-mono:'JetBrains Mono',ui-monospace,'SFMono-Regular',monospace;
}
*{box-sizing:border-box}
body{margin:0;background:var(--p2a-paper);color:var(--p2a-ink);
 font:15px/1.55 var(--p2a-font-body);-webkit-font-smoothing:antialiased}
a{color:var(--p2a-accent-deep)}
.wrap{display:grid;grid-template-columns:262px minmax(0,1fr);
 max-width:1440px;margin:0 auto}
/* Alles, was unter der Kopfleiste sitzt, rechnet mit ihrer Hoehe. Die steht
   als --topbar und wird beim Laden und bei jeder Groessenaenderung gemessen,
   nicht geschaetzt: auf schmalen Schirmen laeuft die Leiste zweizeilig, und
   ein fester Wert war dort zu klein. Genau daran hing, dass die Leiste die
   Navigation verdeckt hat und Ankersprünge unter ihr landeten. */
/* Der Wert stimmt auch ohne Skript: einzeilig auf breiten Schirmen,
   zweizeilig darunter. Das Skript misst nach und korrigiert Rundungen. */
:root{--topbar:38px}
@media (max-width:900px){:root{--topbar:70px}}
nav{position:sticky;top:var(--topbar);align-self:start;
 max-height:calc(100vh - var(--topbar));overflow:auto;
 padding:26px 18px 40px;border-right:1px solid var(--p2a-rule);
 background:var(--p2a-surface)}
/* Ein Ankersprung landet unter der Leiste, nicht dahinter. */
section,#oben{scroll-margin-top:calc(var(--topbar) + 12px)}
nav .brand{font-family:var(--p2a-font-display);font-size:13px;
 letter-spacing:.02em;margin:0 0 2px}
nav .sub{font-family:var(--p2a-font-mono);font-size:9.5px;letter-spacing:.12em;
 text-transform:uppercase;color:var(--p2a-blue);margin:0 0 18px}
nav a{display:block;padding:6px 9px;border-radius:5px;text-decoration:none;
 color:var(--p2a-ink);font-size:13.5px;line-height:1.3}
nav a:hover{background:var(--p2a-paper)}
nav a[aria-current="true"]{background:var(--p2a-paper);font-weight:600;
 box-shadow:inset 2px 0 0 var(--p2a-accent)}
nav a[aria-current="true"] .num{color:var(--p2a-accent)}
/* Kein globales scroll-behavior: es ueberschreibt das 'auto' beim langen
   Sprung, und der Sprung ist dann wieder eine Reise. */
nav .num{font-family:var(--p2a-font-mono);font-size:10.5px;
 color:var(--p2a-blue);margin-right:8px}
main{padding:30px 42px 110px;min-width:0}
.meta{font-family:var(--p2a-font-mono);font-size:10.5px;letter-spacing:.12em;
 text-transform:uppercase;color:var(--p2a-ink-soft)}
h1{font-family:var(--p2a-font-display);font-style:italic;font-size:40px;
 line-height:1.04;letter-spacing:-.015em;margin:.24em 0 .5em;max-width:22ch}
h1 .dot{color:var(--p2a-accent)}
h2{font-family:var(--p2a-font-display);font-size:23px;letter-spacing:-.01em;
 margin:2.4em 0 .5em;padding-top:.55em;border-top:2px solid var(--p2a-ink)}
h3{font-family:var(--p2a-font-display);font-size:15px;letter-spacing:-.005em;
 margin:1.15em 0 .4em}
.lead p{font-size:16.5px;line-height:1.6;max-width:66ch}
.section-message{font-family:var(--p2a-font-display);font-size:19px;
 line-height:1.3;letter-spacing:-.01em;margin:0 0 14px;max-width:46ch}
.eyebrow{font-family:var(--p2a-font-mono);font-size:10.5px;letter-spacing:.12em;
 text-transform:uppercase;color:var(--p2a-blue);margin:26px 0 8px;
 display:flex;align-items:center;gap:8px}
.eyebrow::before{content:"";width:22px;height:2px;background:var(--p2a-accent);
 flex:none}
.kpi-period{font-family:var(--p2a-font-mono);font-size:10.5px;
 letter-spacing:.12em;text-transform:uppercase;color:var(--p2a-blue);
 margin:30px 0 10px}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
 gap:18px 24px}
.kpi{border-top:1.5px solid var(--p2a-ink);padding-top:8px}
.kpi .label{font-family:var(--p2a-font-mono);font-size:10px;letter-spacing:.11em;
 text-transform:uppercase;color:var(--p2a-blue);margin:0 0 3px}
.kpi .value{font-family:var(--p2a-font-display);font-size:29px;
 letter-spacing:-.02em;margin:0}
.kpi .value--leer{font-family:var(--p2a-font-body);font-size:15px;
 font-weight:600;color:var(--p2a-ink-soft)}
.kpi .caption{font-size:12px;line-height:1.4;color:var(--p2a-ink-soft);
 margin:4px 0 0}
.score-total{display:flex;align-items:baseline;gap:18px;flex-wrap:wrap;
 border-top:2.5px solid var(--p2a-ink);padding-top:12px;margin:26px 0 6px}
.score-total .value{font-family:var(--p2a-font-display);font-size:56px;
 line-height:1;letter-spacing:-.03em;margin:0}
.score-total .arrow{font-family:var(--p2a-font-display);font-size:26px;
 color:var(--p2a-accent-deep);margin:0}
/* Der Pfeil als Zeichen, nicht als CSS-Escape. Ein Backslash mit Ziffern ist
   in einem normalen Python-String ein Oktal-Escape, kein CSS-Escape, und im
   Dokument stand daraufhin Zeichensalat statt eines Pfeils. */
.score-total .arrow::before{content:"→ "}
.score-total .label{font-family:var(--p2a-font-mono);font-size:10.5px;
 letter-spacing:.11em;text-transform:uppercase;color:var(--p2a-blue);margin:0;
 flex-basis:100%}
.score-grid{display:flex;gap:24px;margin:16px 0 26px;flex-wrap:wrap}
.score{flex:1;min-width:170px}
.score .label{font-family:var(--p2a-font-mono);font-size:10px;
 letter-spacing:.11em;text-transform:uppercase;color:var(--p2a-blue);
 margin:0 0 3px}
.score .value{font-family:var(--p2a-font-display);font-size:30px;line-height:1;
 margin:0}
.score .caption{font-size:11.5px;line-height:1.4;color:var(--p2a-ink-soft);
 margin:6px 0 0}
.score-total .value .unit,.score .value .unit,.section-score .unit{
 font-family:var(--p2a-font-body);font-weight:600;color:var(--p2a-ink-soft);
 letter-spacing:0}
.score-total .value .unit{font-size:21px}
.score .value .unit{font-size:14px}
.scorebar{position:relative;height:5px;background:var(--p2a-surface);
 margin:7px 0 0}
.scorebar span{display:block;height:100%;background:var(--p2a-blue)}
.scorebar i{position:absolute;top:-3px;width:2px;height:11px;
 background:var(--p2a-accent)}
.section-score{border-top:1.5px solid var(--p2a-ink);padding-top:9px;
 margin:0 0 18px;max-width:400px}
.section-score .label{font-family:var(--p2a-font-mono);font-size:10px;
 letter-spacing:.11em;text-transform:uppercase;color:var(--p2a-blue);
 margin:0 0 3px}
.section-score .value{font-family:var(--p2a-font-display);font-size:32px;
 line-height:1;margin:0}
.section-score .value .unit{font-size:15px}
.section-score .value .arrow{font-family:var(--p2a-font-display);font-size:19px;
 color:var(--p2a-accent-deep);margin-left:12px}
.section-score .value .arrow::before{content:"→ "}
.section-score .caption{font-size:11.5px;line-height:1.4;
 color:var(--p2a-ink-soft);margin:7px 0 0}
.problem-grid{display:flex;gap:28px;margin:8px 0 26px;flex-wrap:wrap}
.problem{flex:1;min-width:210px;border-top:2.5px solid var(--p2a-accent-deep);
 padding-top:10px}
.problem .value{font-family:var(--p2a-font-display);font-size:40px;
 line-height:1;letter-spacing:-.02em;margin:0}
.problem .value .unit{font-family:var(--p2a-font-body);font-weight:600;
 font-size:17px;letter-spacing:0;color:var(--p2a-ink-soft);margin-left:5px}
.problem .label{font-size:15px;font-weight:600;line-height:1.25;
 margin:8px 0 5px}
.problem .caption{font-size:12px;line-height:1.45;color:var(--p2a-ink-soft);
 margin:0}
.problem .ref{font-family:var(--p2a-font-mono);font-size:10px;
 letter-spacing:.06em;white-space:nowrap;color:var(--p2a-blue)}
table{border-collapse:collapse;width:100%;margin:12px 0 18px;font-size:13.5px}
th{text-align:left;font-family:var(--p2a-font-mono);font-size:10px;
 letter-spacing:.11em;text-transform:uppercase;color:var(--p2a-blue);
 border-bottom:1.5px solid var(--p2a-ink);padding:6px 10px 6px 0}
td{padding:7px 10px 7px 0;border-bottom:1px solid var(--p2a-rule);
 vertical-align:top}
th.num,td.num{text-align:right;font-variant-numeric:tabular-nums}
td.neg{color:var(--p2a-accent-deep);background:rgba(226,56,27,.07)}
.evidence{font-family:var(--p2a-font-mono);font-size:11px;line-height:1.5;
 color:var(--p2a-ink-soft);word-break:break-word;margin:8px 0 0}
.finding-block,.measure{background:var(--p2a-surface);
 padding:16px 18px;margin:12px 0;border-left:3px solid var(--p2a-rule)}
.finding-block--hoch{border-left-color:var(--p2a-accent)}
.finding-block--mittel{border-left-color:var(--p2a-blue)}
.finding-block>.eyebrow,.measure>.eyebrow{margin:0 0 4px}
.summary{display:grid;margin:16px 0}
.summary-row{display:grid;grid-template-columns:170px minmax(0,1fr);gap:16px;
 padding:10px 0;border-bottom:1px solid var(--p2a-rule)}
.summary-label{font-family:var(--p2a-font-mono);font-size:10px;
 letter-spacing:.11em;text-transform:uppercase;color:var(--p2a-blue)}
figure.chart{margin:14px 0 20px}
figure.chart svg{width:100%;height:auto}
.filter{position:sticky;top:var(--topbar);z-index:5;background:var(--p2a-paper);
 padding:12px 0;margin-top:20px;border-bottom:1.5px solid var(--p2a-ink);
 display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.filter input{flex:1;min-width:200px;padding:8px 12px;font:14px var(--p2a-font-body);
 border:1px solid var(--p2a-rule);background:var(--p2a-surface);
 color:var(--p2a-ink)}
.filter button{padding:7px 14px;font-family:var(--p2a-font-mono);font-size:10.5px;
 letter-spacing:.1em;text-transform:uppercase;border:1px solid var(--p2a-ink);
 background:var(--p2a-paper);color:var(--p2a-ink);cursor:pointer;
 transition:background .12s,color .12s}
.filter button:hover{background:var(--p2a-surface)}
.filter button:focus-visible{outline:2px solid var(--p2a-accent);
 outline-offset:2px}
.filter button[aria-pressed="true"]{background:var(--p2a-ink);
 color:var(--p2a-paper)}
.count{font-family:var(--p2a-font-mono);font-size:10.5px;
 color:var(--p2a-ink-soft)}
.next-step{background:var(--p2a-ink);color:var(--p2a-paper);padding:26px 28px;
 margin:36px 0 0}
.next-step .meta,.next-step .eyebrow{color:#fff}
.next-step .eyebrow::before{background:var(--p2a-accent)}
.next-step a{color:#fff}
.logo{height:15px;width:auto}
ol,ul{max-width:70ch}
[hidden]{display:none!important}
/* Die mitlaufende Kopfleiste. Ohne sie weiss man nach dem ersten Bildschirm
   nicht mehr, wo man ist, und kommt nirgendwo hin. Auf breiten Schirmen zeigt
   sie den aktuellen Abschnitt, auf schmalen zusaetzlich den Menue-Knopf. */
.topbar{position:sticky;top:0;z-index:20;display:flex;align-items:center;
 gap:12px;padding:9px 16px;background:var(--p2a-paper);
 border-bottom:1px solid var(--p2a-rule)}
.topbar .burger{display:none;width:34px;height:32px;flex:none;padding:0;
 border:1px solid var(--p2a-rule);background:var(--p2a-surface);
 color:var(--p2a-ink);cursor:pointer;font-size:15px;line-height:1}
.topbar .hier{font-family:var(--p2a-font-mono);font-size:10.5px;
 letter-spacing:.11em;text-transform:uppercase;color:var(--p2a-blue);
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.topbar .fortschritt{flex:1;height:3px;background:var(--p2a-surface);
 min-width:40px}
.topbar .fortschritt span{display:block;height:100%;
 background:var(--p2a-accent);width:0}
.topbar .logo{height:17px;flex:none}
.wrap{padding-top:0}
/* Der Schluss: die Schlussseite des Betreibers oder das neutrale Panel, als
   eigenes Band unter Navigation und Inhalt. Die Spalte ist höchstens so breit
   wie ein A4-Blatt und steht mittig, mit Abstand darüber. Ist das Blatt breiter
   als der Schirm, verkleinert das Skript es auf die Breite des Bands; ohne
   Skript läuft es über die Spalte hinaus und scrollt im Band, statt die Seite
   zu verbreitern. Für die Datei des Betreibers steht hier keine
   eigene Regel, nur das Band um sie herum. */
.closing-web{display:grid;grid-template-columns:minmax(0,210mm);
 justify-content:center;padding:72px 24px 96px;overflow-x:auto;
 background:var(--p2a-surface);border-top:1px solid var(--p2a-rule)}
footer.closing{background:var(--p2a-ink);color:var(--p2a-paper);
 padding:44px 48px 26px}
footer.closing .logo-reversed{display:block;height:20px;width:auto;
 margin:0 0 30px}
footer.closing .eyebrow{color:var(--p2a-accent);margin:0 0 4px}
footer.closing .eyebrow--line::before{background:var(--p2a-accent)}
footer.closing .summary{max-width:120mm;margin:10px 0 0;
 border-top:1px solid rgba(255,255,255,.28)}
footer.closing .summary-row{border-bottom-color:rgba(255,255,255,.28)}
footer.closing .summary-label{color:rgba(255,255,255,.6)}
footer.closing .summary-value{color:var(--p2a-paper)}
footer.closing a{color:var(--p2a-accent)}
footer.closing .origin{margin:26px 0 0;font-size:12px;
 color:rgba(255,255,255,.6)}
footer.closing .logo-reversed+.origin{margin-top:0}
footer.closing .panel-footer{display:flex;justify-content:space-between;
 flex-wrap:wrap;gap:6px 16px;margin-top:48px;
 font-family:var(--p2a-font-mono);font-size:10px;letter-spacing:.08em;
 text-transform:uppercase;color:rgba(255,255,255,.6)}

@media (max-width:900px){
 .wrap{grid-template-columns:1fr}
 /* Die Seitennavigation wird zum Menue hinter dem Burger: sie steht sonst als
    15-Zeilen-Block ueber dem Einstieg und schiebt den Report nach unten. */
 /* Ohne Skript bleibt die Navigation zu: sonst liegt sie als Vollbild ueber
    dem Report und laesst sich nicht schliessen. Das Skript oeffnet sie. */
 nav{display:none;position:fixed;top:var(--topbar);left:0;right:0;bottom:0;
  z-index:19;max-height:none;border-right:0;
  border-bottom:1px solid var(--p2a-rule);overflow:auto;padding:16px}
 nav[data-offen="ja"]{display:block}
 nav[hidden]{display:none!important}
 .topbar .burger{display:block}
 /* Zweizeilig: Logo, Knopf und Abschnittsname nebeneinander sind auf einem
    Telefon zu viel in einer Zeile, und der Abschnittsname wird abgeschnitten. */
 .topbar{flex-wrap:wrap;row-gap:6px;padding:7px 14px}
 .topbar .hier{order:3;flex-basis:100%;white-space:normal}
 .topbar .fortschritt{order:2}
 main{padding:18px}
 h1{font-size:30px}
 .score-grid,.problem-grid,.kpi-grid{gap:18px}
 .summary-row{grid-template-columns:1fr;gap:3px}
 .closing-web{padding:40px 12px 56px}
 footer.closing{padding:28px 22px 20px}
}
"""

SCRIPT = """
(function(){
 // Jeder Baustein laeuft fuer sich. Faellt einer aus, funktionieren die
 // anderen weiter, und die Navigation funktioniert ohnehin ohne Skript.
 function versuch(name, fn){
  try { fn(); } catch (e) {
   if (window.console) console.error('Audit-Report, ' + name + ':', e);
  }
 }

 // Die Schlussseite des Betreibers ist ein A4-Blatt und auf einem Telefon
 // breiter als der Schirm. zoom verkleinert nur dieses Blatt auf die Breite
 // des Bands, statt es rechts abzuschneiden; ohne Skript scrollt es im Band.
 // Das neutrale Panel ist kein section-Element und bleibt unberuehrt. Steht
 // ganz oben, damit ein Fehler weiter unten den Schluss nicht mitnimmt.
 versuch('Schlussseite', function(){
  var band=document.querySelector('.closing-web'),
      sheet=band && band.querySelector(':scope > section');
  if(!sheet) return;
  function fitClosingPage(){
   sheet.style.zoom='';
   var style=getComputedStyle(band),
       room=band.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight),
       scale=Math.min(1, room/sheet.offsetWidth);
   sheet.style.zoom = scale<1 ? String(scale) : '';
  }
  fitClosingPage();
  window.addEventListener('resize',fitClosingPage);
 });

 var suche=document.getElementById('q'),
     knoepfe=[].slice.call(document.querySelectorAll('.filter button')),
     // Nur im Inhalt: die Schlussseite unter dem Inhalt ist selbst ein
     // section-Element und verschwaende sonst beim Filtern.
     bloecke=[].slice.call(document.querySelectorAll('main .finding-block,main .measure')),
     sektionen=[].slice.call(document.querySelectorAll('main section')),
     leiste=document.querySelector('.filter'),
     zaehler=document.getElementById('count'), grad='alle';

 function filtern(){
  var q=(suche.value||'').toLowerCase().trim(), sichtbar=0;
  bloecke.forEach(function(b){
   var passtGrad = grad==='alle' || b.dataset.severity===grad,
       passtText = !q || b.textContent.toLowerCase().indexOf(q)>-1;
   b.hidden = !(passtGrad && passtText);
   if(!b.hidden) sichtbar++;
  });
  // Eine Sektion ohne sichtbaren Block verschwindet mit: sonst bleiben
  // Ueberschriften ohne Inhalt stehen und der Filter sieht kaputt aus.
  sektionen.forEach(function(s){
   var eigene=s.querySelectorAll('.finding-block,.measure');
   if(!eigene.length){ s.hidden = (grad!=='alle'||!!q); return; }
   s.hidden = ![].some.call(eigene,function(b){return !b.hidden;});
  });
  zaehler.textContent = sichtbar+' von '+bloecke.length+' Einträgen';
  // Nach dem Filtern schrumpft die Seite. Wer weit unten stand, landet sonst
  // hinter dem neuen Dokumentende und sieht eine leere Flaeche: der Filter
  // wirkt dann kaputt, obwohl er gerade gearbeitet hat.
  if(leiste.getBoundingClientRect().top < 0){
   window.scrollTo({top: leiste.offsetTop - 8, behavior:'auto'});
  }
  markieren();
 }

 versuch('Filter', function(){
  suche.addEventListener('input',filtern);
  knoepfe.forEach(function(k){k.addEventListener('click',function(){
   grad=k.dataset.severity;
   knoepfe.forEach(function(o){o.setAttribute('aria-pressed', o===k ? 'true':'false');});
   filtern();
  });});
 });

 // --- Navigation: markieren wo man ist, und weich dorthin scrollen --------
 var nav=document.getElementById('nav'),
     burger=document.querySelector('.topbar .burger'),
     hier=document.getElementById('hier'),
     fortschritt=document.getElementById('fortschritt'),
     links=[].slice.call(nav.querySelectorAll('a')),
     ziele=links.map(function(a){
      return document.querySelector(a.getAttribute('href'));
     });

 function schmal(){ return window.matchMedia('(max-width:900px)').matches; }
 function menue(auf){
  nav.hidden = schmal() ? !auf : false;
  nav.setAttribute('data-offen', auf ? 'ja' : 'nein');
  burger.setAttribute('aria-expanded', auf ? 'true' : 'false');
 }
 burger.addEventListener('click',function(){
  menue(burger.getAttribute('aria-expanded') !== 'true');
 });
 window.addEventListener('resize',function(){ if(!schmal()) menue(false); });
 menue(false);

 function markieren(){
  var mitte=window.scrollY + leisteOben.getBoundingClientRect().height + 90,
      aktiv=-1;
  ziele.forEach(function(z,i){
   if(z && !z.hidden && z.offsetTop <= mitte) aktiv=i;
  });
  links.forEach(function(a,i){
   a.setAttribute('aria-current', i===aktiv ? 'true' : 'false');
  });
  // Der Kopf sagt, wo man ist, und wie weit man ist. Ohne beides weiss man
  // nach dem ersten Bildschirm nicht mehr, an welcher Stelle man liest.
  if(aktiv>-1){
   // Ohne die Nummer: textContent zieht das <span class="num"> mit, und im
   // Kopf stand "0Zusammenfassung".
   var num=links[aktiv].querySelector('.num');
   hier.textContent = links[aktiv].textContent
    .replace(num ? num.textContent : '', '').trim();
  }
  var hoehe=document.body.scrollHeight - window.innerHeight;
  fortschritt.style.width = hoehe>0
   ? Math.min(100, Math.round(window.scrollY / hoehe * 100)) + '%' : '0';
  if(aktiv>-1 && !schmal()){
   // Den aktiven Eintrag im Blick halten, wenn die Navigation selbst scrollt.
   var a=links[aktiv], r=a.getBoundingClientRect(),
       n=nav.getBoundingClientRect();
   if(r.top < n.top+8 || r.bottom > n.bottom-8) a.scrollIntoView({block:'nearest'});
  }
 }

 // Der Sprung selbst passiert nativ ueber den Anker, nicht per Skript. Das
 // Skript verhindert ihn nicht mehr und korrigiert ihn nicht: der Abstand zur
 // Kopfleiste kommt aus scroll-margin-top im Stylesheet. So funktioniert die
 // Navigation auch dann, wenn hier irgendwo etwas wirft, und genau das war am
 // 07.09.2026 der Fall: die Seite sah aus wie eine kaputte Navigation,
 // waehrend in Wahrheit nur eine Zeile weiter oben gescheitert war.
 links.forEach(function(a){a.addEventListener('click',function(){
  if(schmal()) menue(false);
 });});

 // Die Hoehe der Kopfleiste messen, statt sie zu setzen: sie ist auf einem
 // Telefon zweizeilig und auf einem Schirm einzeilig.
 var leisteOben=document.querySelector('.topbar');
 function leisteMessen(){
  document.documentElement.style.setProperty('--topbar',
   Math.round(leisteOben.getBoundingClientRect().height) + 'px');
 }
 leisteMessen();
 window.addEventListener('resize',leisteMessen);
 if(window.ResizeObserver) new ResizeObserver(leisteMessen).observe(leisteOben);

 var wartet=false;
 window.addEventListener('scroll',function(){
  if(wartet) return;
  wartet=true;
  requestAnimationFrame(function(){ markieren(); wartet=false; });
 },{passive:true});

 versuch('Startzustand', filtern);
})();
"""


def _data_attributes(html_text: str) -> str:
    """Schweregrad als data-Attribut, damit der Filter ihn lesen kann.

    Der Schweregrad steht in der Druckfassung nur als Text im Eyebrow. Statt
    ihn dort zusaetzlich als Attribut mitzuschleppen (und im PDF nutzlos zu
    haben), wird er hier aus derselben Zeile gezogen.
    """
    def block(m):
        klasse, remainder = m.group(1), m.group(2)
        grad = re.search(r"finding-block--(\w+)", klasse)
        return (f'<div class="{klasse}" data-severity='
                f'"{grad.group(1) if grad else "alle"}"{remainder}')
    html_text = re.sub(r'<div class="(finding-block[^"]*)"(>)', block, html_text)
    return html_text.replace('<div class="measure">',
                             '<div class="measure" data-severity="alle">')


def build(run: rb.Run, text: dict, inh: dict | None = None,
          assets: Path | None = None) -> str:
    assets = assets or (Path(__file__).resolve().parents[2] / "assets" / "brand")
    inh = inh or rb.content(run, text)
    w = inh["werte"]
    nav, koerper = [], []
    for key, block in inh["sektionen"].items():
        number, title = rb.SECTION_TITLES.get(key, rb.SECTION_APPENDIX.get(key))
        nav.append((number, title, key))
        koerper.append((number, f'<section id="s-{key}"><h2>{number} · '
                                f"{rb.esc(title)}</h2>{block}</section>"))
    nav.sort()
    koerper.sort()

    navigation = "".join(
        f'<a href="#s-{k}"><span class="num">{n}</span>{rb.esc(t)}</a>'
        for n, t, k in nav)
    inhalt_html = _data_attributes("".join(b for _, b in koerper))

    page = f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{w['__BRAND__']} · E-Com-Audit</title>
<style>{_fonts(assets)}{STYLE}</style></head><body>
<div class="topbar">
 <button class="burger" type="button" aria-expanded="false"
         aria-controls="nav" aria-label="Abschnitte anzeigen">☰</button>
 {_logo(assets)}
 <span class="hier" id="hier">Zusammenfassung</span>
 <span class="fortschritt"><span id="fortschritt"></span></span>
</div>
<div class="wrap">
<nav id="nav">
<p class="brand">{w['__BRAND__']}</p>
<p class="sub">E-Com-Audit · {w['__RUN_LABEL__']}</p>
<a href="#oben"><span class="num">0</span>Zusammenfassung</a>
{navigation}</nav>
<main>
<p class="meta" id="oben">E-Com-Audit · {w['__BRAND__']} ·
 {w['__RUN_LABEL__']} · erstellt am {w['__GENERATED_DATE__']}</p>
<h1>{w['__COVER_HEADLINE__']}<span class="dot">.</span></h1>
<div class="lead">{w['__INTRO__']}</div>
<p class="eyebrow">Was den Shop gerade am meisten kostet</p>
{w['__PROBLEMS__']}
<p class="eyebrow">Wo der Shop steht</p>
{w['__SCORES__']}
<p class="kpi-period">{rb.esc(w['__KPI_PERIOD__'])}</p>
<div class="kpi-grid">
{_tile("Umsatz", w['__KPI_REVENUE__'], w['__KPI_REVENUE_NOTE__'])}
{_tile("Bestellungen", w['__KPI_ORDERS__'], w['__KPI_ORDERS_NOTE__'])}
{_tile("Ø Bestellwert", w['__KPI_AOV__'], w['__KPI_AOV_NOTE__'])}
{_tile("Conversion Rate", w['__KPI_CR__'], w['__KPI_CR_NOTE__'])}
{_tile("Sitzungen", w['__KPI_SESSIONS__'], w['__KPI_SESSIONS_NOTE__'])}
{_tile(w['__KPI_SIXTH_LABEL__'], w['__KPI_SIXTH__'], w['__KPI_SIXTH_NOTE__'],
         w['__KPI_SIXTH_CLASS__'])}
</div>
<div class="summary">
{_row("Was du hier siehst", w['__SUMMARY_WHAT__'])}
{_row("Warum", w['__SUMMARY_WHY__'])}
{_row("Status quo", w['__SUMMARY_STATUS__'])}
{_row("Das Problem", w['__SUMMARY_PROBLEM__'])}
{_row("Was möglich ist", w['__SUMMARY_POSSIBLE__'])}
</div>
<p class="eyebrow">Die wichtigsten Erkenntnisse</p>
{w['__TAKEAWAYS__']}
<p class="eyebrow">Die Befunde im Überblick</p>
{w['__FINDINGS_OVERVIEW__']}
<div class="filter">
 <input id="q" type="search" placeholder="In Befunden und Maßnahmen suchen">
 <button data-severity="alle" aria-pressed="true">alle</button>
 <button data-severity="hoch" aria-pressed="false">nur schwerwiegend</button>
 <button data-severity="mittel" aria-pressed="false">mittel</button>
 <button data-severity="gering" aria-pressed="false">gering</button>
 <span class="count" id="count"></span>
</div>
{inhalt_html}
<div class="next-step"><p class="eyebrow">Nächster Schritt</p>
{w['__NEXT_STEP__']}</div>
</main></div>
{_closing_region(assets, w)}
<script>{SCRIPT}</script>
</body></html>"""
    # Zuletzt, wie in der Druckfassung: die Datei des Betreibers wird ungelesen
    # übernommen und ist kein Text dieses Audits.
    return closing.apply(page, run.ws)


def _closing_region(assets: Path, w: dict) -> str:
    """Der Schluss unter dem Inhalt, zwischen denselben Markierungen wie im Druck.

    Das Panel ist gebaut wie in `skills/audit/templates/audit.html`: Logo, der
    Platzhalter, die Fußzeile. Das Band `closing-web` liegt außerhalb der
    Markierungen und bleibt deshalb auch um die Schlussseite des Betreibers stehen.
    """
    return (f'<div class="closing-web">\n{closing.START}\n'
            '<footer class="closing">\n'
            f'{_logo(assets, "logo-reversed.svg", "logo-reversed")}\n'
            f'{closing.PLACEHOLDER}\n'
            '<div class="panel-footer"><span>Path to AI · path-to-ai.com</span>'
            f'<span>{w["__BRAND__"]} · E-Com-Audit {w["__RUN_LABEL__"]}</span></div>\n'
            f'</footer>\n{closing.END}\n</div>')


def _tile(label, value, notiz, klasse="") -> str:
    return (f'<div class="kpi"><p class="label">{rb.esc(label)}</p>'
            f'<p class="value {klasse}">{rb.esc(value)}</p>'
            f'<p class="caption">{rb.esc(notiz)}</p></div>')


def _row(label, value) -> str:
    return (f'<div class="summary-row"><div class="summary-label">'
            f'{rb.esc(label)}</div><div>{value}</div></div>')


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", default=".")
    p.add_argument("--run-id", required=True)
    p.add_argument("--text")
    p.add_argument("--out")
    a = p.parse_args(argv)

    ws = Path(a.workspace).resolve()
    run = rb.Run(ws, a.run_id)
    if not run.state:
        raise SystemExit(f"Kein Lauf {a.run_id} unter {ws}/reporting/runs/")
    textpfad = Path(a.text) if a.text else run.run / "report-text.json"
    if not textpfad.exists():
        raise SystemExit(f"{textpfad} fehlt. Erst report_build laufen lassen.")
    goal = Path(a.out) if a.out else run.run / "audit-web.html"
    hier = Path(__file__).resolve().parents[2]
    goal.write_text(build(run, rb.text_laden(textpfad),
                          assets=hier / "assets" / "brand"), encoding="utf-8")
    print(f"Geschrieben: {goal}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
