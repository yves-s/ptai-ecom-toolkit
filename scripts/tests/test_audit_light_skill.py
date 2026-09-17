"""Die audit-light-Skill gegen das prüfen, was es wirklich gibt.

Dieselbe Fehlerklasse wie in `test_agent_frontmatter.py`, eine Ebene höher: eine
Skill, die eine andere Skill unter einem Namen ruft, den es nicht gibt, oder ein
Script unter einem Pfad, der nicht existiert, scheitert erst im Lauf. Bis dahin
sind Stufe 0 und ein Teil von Stufe 1 gelaufen, und bei `--with-dfs` ist das
bezahlt. Der Fehler wäre in keiner Ausgabe zu sehen, nur in einem Agenten, der
meldet, er komme nicht weiter.

Deshalb wird hier statisch geprüft, was der Lauf sonst dynamisch herausfindet.
"""
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[2]
SKILLS = WURZEL / "skills"
AUDIT_LIGHT = SKILLS / "audit-light" / "SKILL.md"
NEUE_SKILLS = ("audit-light", "audit-light-send",
               "lens-purchase-path", "lens-trust", "lens-assortment")


def text(pfad: Path) -> str:
    return pfad.read_text(encoding="utf-8")


class TestFrontmatter(unittest.TestCase):
    def test_jede_neue_skill_hat_passendes_frontmatter(self):
        for name in NEUE_SKILLS:
            with self.subTest(skill=name):
                filename = SKILLS / name / "SKILL.md"
                self.assertTrue(filename.is_file(), f"{name}/SKILL.md fehlt")
                header = text(filename).split("---", 2)
                self.assertEqual(header[0], "", "Frontmatter muss in Zeile 1 beginnen")
                self.assertRegex(header[1], rf"(?m)^name:\s*{re.escape(name)}\s*$",
                                 f"name im Frontmatter muss {name} sein")
                beschreibung = re.search(r"^description:\s*(.+)$", header[1], re.M)
                self.assertIsNotNone(beschreibung, f"{name}: description fehlt")
                # Die Beschreibung ist das einzige, was der Router vor dem Laden
                # sieht. Zu kurz heisst: die Skill wird nie gefunden.
                self.assertGreater(len(beschreibung.group(1)), 180,
                                   f"{name}: description zu knapp zum Auffinden")


class TestVerweise(unittest.TestCase):
    def setUp(self):
        self.content = text(AUDIT_LIGHT)

    def test_jede_gerufene_plugin_skill_existiert(self):
        gerufen = set(re.findall(r"`ptai-ecom:([a-z0-9-]+)`", self.content))
        self.assertTrue(gerufen, "audit-light ruft gar keine Plugin-Skill, das kann nicht stimmen")
        for name in sorted(gerufen):
            with self.subTest(skill=name):
                self.assertTrue((SKILLS / name / "SKILL.md").is_file(),
                                f"audit-light ruft ptai-ecom:{name}, die Skill gibt es nicht")

    def test_die_vier_quellen_skills_werden_genannt(self):
        # Ein Lauf ohne eine dieser vier ist kein Audit, sondern eine Stichprobe.
        for skill in ("crawl-site", "capture-screens", "pull-cwv", "check-geo"):
            self.assertIn(skill, self.content, f"{skill} kommt in audit-light nicht vor")

    def test_jedes_gerufene_script_existiert(self):
        # Nur pfadsichere Zeichen: sonst wandern Anfuehrungszeichen, Backticks
        # und schliessende Klammern aus dem Fliesstext in den vermeintlichen Pfad.
        pfade = re.findall(r'\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9_./-]+)', self.content)
        self.assertTrue(pfade, "audit-light ruft kein Script")
        for rel in sorted(set(pfade)):
            with self.subTest(pfad=rel):
                # Datei oder Verzeichnis: sys.path.insert zeigt auf scripts/
                # selbst, ein Script-Aufruf auf eine Datei darin.
                self.assertTrue((WURZEL / rel).exists(),
                                f"audit-light verweist auf {rel}, das gibt es nicht")

    def test_die_python_module_sind_importierbar(self):
        from audit import account, lightconf
        for name in ("resolve", "brand_of", "drive_path", "normalize_host", "accounts_root",
                     "slug_from_host", "create", "find_or_create"):
            self.assertTrue(hasattr(account, name), f"account.{name} fehlt")
        for name in ("build", "add_page_types", "set_geo_queries", "missing", "write"):
            self.assertTrue(hasattr(lightconf, name), f"lightconf.{name} fehlt")


class TestBefundVertrag(unittest.TestCase):
    """Die Linsen schreiben, was der Orchestrator liest. Ein Feld, das nur eine
    Seite kennt, faellt still unter den Tisch."""

    PFLICHTFELDER = ("severity", "title", "detail", "recommendation",
                     "evidence", "url", "impact", "effort", "confidence", "lens")

    def test_jede_linse_nennt_alle_pflichtfelder(self):
        for name in ("lens-purchase-path", "lens-trust", "lens-assortment"):
            content = text(SKILLS / name / "SKILL.md")
            for feld in self.PFLICHTFELDER:
                with self.subTest(skill=name, feld=feld):
                    self.assertIn(f"`{feld}", content,
                                  f"{name} nennt das Pflichtfeld {feld} nicht")

    def test_orchestrator_nennt_dieselben_felder(self):
        content = text(AUDIT_LIGHT)
        for feld in self.PFLICHTFELDER:
            with self.subTest(feld=feld):
                self.assertIn(f"`{feld}", content)

    def test_jede_linse_verlangt_ihre_coverage_datei(self):
        # Ohne coverage sieht eine geblockte Linse im Score aus wie ein guter Shop.
        for name in ("lens-purchase-path", "lens-trust", "lens-assortment"):
            with self.subTest(skill=name):
                content = text(SKILLS / name / "SKILL.md")
                self.assertIn("coverage.json", content)
                self.assertIn("not_checkable", content)

    def test_die_dateinamen_stimmen_zwischen_linse_und_lauf(self):
        for name, filename in (("lens-purchase-path", "L3-purchase-path.json"),
                            ("lens-trust", "L4-trust.json"),
                            ("lens-assortment", "L5-assortment.json")):
            with self.subTest(skill=name):
                self.assertIn(filename, text(SKILLS / name / "SKILL.md"))


class TestDisziplin(unittest.TestCase):
    """Regeln, die schon einmal verletzt wurden und deshalb festgeschrieben sind."""

    def test_browser_werkzeuge_bleiben_verboten(self):
        content = text(AUDIT_LIGHT)
        self.assertIn("WebFetch", content)
        self.assertIn("mcp__Claude_Browser__", content)

    def test_keine_gedankenstriche_in_den_neuen_skills(self):
        # Styleguide Abschnitt 10, gilt fuer alles, was unter Yves' Namen rausgeht.
        for name in NEUE_SKILLS:
            with self.subTest(skill=name):
                content = text(SKILLS / name / "SKILL.md")
                treffer = [z for z in content.splitlines() if "—" in z or "–" in z]
                self.assertEqual(treffer, [], f"{name}: Gedankenstrich in {treffer[:1]}")

    def test_der_lauf_nimmt_eine_audit_id(self):
        # Der Normalfall ist der Funnel-Lead, nicht die getippte URL. Ohne ID
        # gibt es keinen Empfaenger fuer den Report.
        content = text(AUDIT_LIGHT)
        self.assertIn("audit-id", content)
        self.assertIn("audit_id", content)
        self.assertIn("db.mjs", content)

    def test_der_lauf_haelt_nicht_an_und_fragt_nichts(self):
        content = text(AUDIT_LIGHT)
        self.assertIn("ohne Rückfrage", content)
        self.assertNotIn("entscheidest du, nicht das Skript", content)

    def test_der_lauf_haelt_an_keiner_stelle_fuer_eine_frage(self):
        # Ein Lauf, der auf eine Antwort wartet, ist kein Werkzeug. Die drei
        # Stellen, an denen frueher gefragt wurde, sind namentlich geschlossen:
        # Lead-Anlage, GEO-Fragen, Seitentypen.
        content = text(AUDIT_LIGHT)
        self.assertIn("Stell keine Rückfragen", content)
        self.assertIn("Der Lauf hält\ndabei nicht an", content.replace("\r", ""))
        for verboten in ("Yves wählt", "entscheidest du, nicht das Skript",
                         "Der\nSkill stellt dabei Rückfragen"):
            self.assertNotIn(verboten, content, f"alte Frage-Formulierung noch drin: {verboten}")

    def test_mehrdeutig_ist_ein_fehler_und_keine_frage(self):
        content = text(AUDIT_LIGHT)
        self.assertIn("abbrechen", content)
        self.assertIn("kaputter CRM-Zustand", content)

    def test_checkout_path_ist_per_default_aus(self):
        content = text(AUDIT_LIGHT)
        self.assertIn("checkout_capture: false", content)

    def test_vertrauen_urteilt_nicht_juristisch(self):
        content = text(SKILLS / "lens-trust" / "SKILL.md")
        self.assertIn("rechtswidrig", content, "die Abgrenzung selbst muss dastehen")
        self.assertRegex(content, r"kein\s+Rechtsrat")


class TestSendIsPathToAiFunnel(unittest.TestCase):
    """audit-light-send sagt vorn, wessen Funnel das ist (Spec 2026-09-11, B3, D4).

    Wer das Plugin unverändert übernimmt, soll vor dem ersten Versand lesen,
    dass Teaser-Mail, Kalenderlink und Datenbank zu Path to AI gehören.
    """

    SKILL = SKILLS / "audit-light-send" / "SKILL.md"

    def opening(self) -> str:
        """Der erste Absatz nach der H1, Zeilenumbrüche als Leerzeichen."""
        body = text(self.SKILL).split("---", 2)[2]
        after_heading = body.split("\n# ", 1)[1].split("\n", 1)[1]
        return " ".join(after_heading.strip().split("\n\n", 1)[0].split())

    def test_the_first_paragraph_names_the_funnel_and_what_it_needs(self):
        paragraph = self.opening()
        for needed in ("Lead-Funnel von Path to AI", "Supabase", "`audits`", "`findings`",
                       "Resend", "`PTAI_MAIL_FROM`", "`PTAI_MAIL_REPLY_TO`",
                       "report-email.mjs", "nicht Teil des Plugins"):
            with self.subTest(needed=needed):
                self.assertIn(needed, paragraph)

    def test_the_sender_settings_are_prerequisites(self):
        content = text(self.SKILL)
        prerequisites = content[content.index("## Voraussetzungen"):content.index("## Ablauf")]
        self.assertIn("PTAI_MAIL_FROM", prerequisites)
        self.assertIn("PTAI_MAIL_REPLY_TO", prerequisites)


class TestAccountDir(unittest.TestCase):
    """Ein Platzhalter für den Kundenordner, kein WorkOS (Spec 2026-09-11 public release, A2)."""

    def setUp(self):
        self.content = text(AUDIT_LIGHT)

    def test_no_workos_placeholder_or_folder(self):
        for old in ("<WORKOS>", "<drive>", "02-accounts", "WorkOS"):
            with self.subTest(old=old):
                self.assertNotIn(old, self.content)

    def test_one_placeholder_for_the_customer_folder(self):
        for used in ('cd "<account_dir>"', '--target "<account_dir>/material/',
                     'mkdir -p "<account_dir>/deliverables"', "<account_dir>/audit-runs/"):
            with self.subTest(used=used):
                self.assertIn(used, self.content)

    def test_a_missing_customer_is_created_without_workos(self):
        self.assertIn("python3 -m audit.account create", self.content)
        self.assertIn("--brand", self.content)
        self.assertIn("og:site_name", self.content)
        self.assertIn("marke aus: slug", self.content)

    def test_a_taken_folder_aborts_like_ambiguous(self):
        self.assertRegex(self.content, r"\| 3 \| \*\*abbrechen\*\*")

    def test_foreign_skills_only_if_installed(self):
        self.assertIn("falls installiert", self.content)
        self.assertIn("Ist `workos:lead` installiert", self.content)
        self.assertIn("Ist `workos:report` installiert", self.content)


class TestSendFindsTheRun(unittest.TestCase):
    """Der Versand sucht unter PTAI_ACCOUNTS_ROOT (Spec 2026-09-11 public release, A2)."""

    def setUp(self):
        self.content = text(SKILLS / "audit-light-send" / "SKILL.md")

    def test_searches_under_the_accounts_root(self):
        self.assertIn("account.accounts_root()", self.content)
        for old in ("<WORKOS>", "02-accounts", "$LAUF"):
            with self.subTest(old=old):
                self.assertNotIn(old, self.content)

    def test_takes_an_explicit_run(self):
        self.assertIn("--run <lauf-ordner>", self.content)

    def test_the_entity_note_only_when_the_file_exists(self):
        self.assertIn("wenn es dort eine `entity.md` gibt", self.content)
        self.assertRegex(self.content, r"Fehlt die\s+Datei, nichts anlegen")

    def test_the_search_picks_the_newest_run_including_a_second_one_that_day(self):
        # Bis 11.09.2026 fand das Muster `*-light` einen Lauf `-light-2` gar nicht,
        # und `head -1` nahm den älteren. Geprüft wird die Zeile aus der Skill selbst.
        snippet = re.search(r"RUN_DIR=\$\(grep -l .*?head -1\)", self.content, re.S)
        self.assertIsNotNone(snippet, "Suchzeile für RUN_DIR fehlt")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for slug, run, audit_id in (("beispielshop", "2026-09-11-light", "id-1"),
                                        ("beispielshop", "2026-09-11-light-2", "id-1"),
                                        ("anderer-shop", "2026-09-12-light", "id-2")):
                folder = root / slug / "audit-runs" / run
                folder.mkdir(parents=True)
                (folder / "run-config.json").write_text(json.dumps({"audit_id": audit_id}),
                                                        encoding="utf-8")
            script = snippet.group(0).replace("<audit-id>", "id-1") + '\nprintf %s "$RUN_DIR"'
            result = subprocess.run(["bash", "-c", script],
                                    env={**os.environ, "ACCOUNTS_ROOT": tmp},
                                    capture_output=True, text=True, timeout=30)
            expected = str(root / "beispielshop" / "audit-runs" / "2026-09-11-light-2")
        self.assertEqual(result.stdout, expected, result.stderr)


if __name__ == "__main__":
    unittest.main()
