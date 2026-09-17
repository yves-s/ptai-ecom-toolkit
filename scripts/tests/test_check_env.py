"""check_env.sh gegen Wegwerf-Workspaces (Spec 2026-09-11, Abschnitte 4.2, 6, 8).

Kein Aufruf nach außen: CHECK_ENV_OFFLINE=1. Die Tests vergleichen Workspaces
miteinander statt absolute Exit-Codes zu prüfen, weil Chrome, jq und Shopify
CLI je Rechner verschieden sind.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "check_env.sh"

# Das bash des Systems, nicht das erste im PATH. Auf macOS ist /bin/bash die
# Version 3.2, und genau dort soll ein Rückfall auffallen; ein Homebrew-bash 5
# vorne im PATH ließe ihn durchgehen.
BASH = "/bin/bash" if Path("/bin/bash").exists() else "bash"

def _google_auth_ready() -> bool:
    # check_env.sh braucht den requests-Transport, nicht nur google.auth. Ohne
    # ihn melden beide Vergleichs-Workspaces "nicht möglich", und die Vergleiche
    # gehen nicht mehr an der geprüften Stelle auseinander.
    try:
        import google.auth.transport.requests  # noqa: F401
    except ImportError:
        return False
    return True


READY = (shutil.which("jq") is not None and sys.version_info >= (3, 10)
         and _google_auth_ready())


@unittest.skipUnless(READY, "braucht jq, python3 ab 3.10 und google-auth")
class CheckEnvCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def workspace(self, name="ws", env_lines=None, sources=None, drop=(), **overrides):
        ws = self.root / name
        (ws / "reporting").mkdir(parents=True)
        (ws / "secrets").mkdir()
        sa = ws / "secrets" / "google-sa.json"
        sa.write_text(json.dumps({"type": "service_account",
                                  "client_email": "sa@beispielshop.example",
                                  "private_key": "x"}), encoding="utf-8")
        drive = self.root / f"{name}-drive"
        drive.mkdir()
        config = {
            "brand": "Beispielshop", "domain": "https://beispielshop.example",
            "shopify_store": "beispielshop.myshopify.com", "ga4_property_id": "1",
            "gsc_site": "sc-domain:beispielshop.example", "cwv_urls": [],
            "sources": sources or {}, "account_slug": "beispielshop",
            "drive_path": str(drive), "geo_method": "browser",
            "market": {"location_code": 2276, "language_code": "de"},
        }
        config.update(overrides)
        for field in drop:
            config.pop(field)
        (ws / "reporting" / "config.json").write_text(json.dumps(config), encoding="utf-8")
        lines = [f"PTAI_GOOGLE_CREDENTIALS={sa}"] if env_lines is None else env_lines
        (ws / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return ws

    def central(self, name="central.env", **values):
        path = self.root / name
        path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
        return path

    def shopify_stub(self):
        # Eine Attrappe der Shopify CLI. Offline ruft der Check sie nie auf, er
        # fragt nur, ob es sie gibt. Ohne CLI ist Shopify offen, und ein Test,
        # der "Pflicht vollständig." erwartet, hinge am Rechner.
        bin_dir = self.root / "bin"
        bin_dir.mkdir(exist_ok=True)
        stub = bin_dir / "shopify"
        stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)
        return bin_dir

    def git(self, ws, *args):
        subprocess.run(["git", "-C", str(ws), *args], check=True,
                       capture_output=True, timeout=60)

    def git_repo(self, ws):
        subprocess.run(["git", "init", "-q", str(ws)], check=True,
                       capture_output=True, timeout=60)
        # Globale Ausschlüsse des Rechners aus dem Spiel nehmen, sonst hängt das
        # Ergebnis an der Git-Konfiguration dessen, der die Tests startet.
        self.git(ws, "config", "core.excludesFile", str(self.root / "no-global-excludes"))

    def run_check(self, ws, central, home=None, cwd=None, path_prefix=None, extra_env=None):
        # central=None lässt PTAI_ENV_FILE ungesetzt, "" setzt es leer. home
        # ersetzt HOME, damit die Standarddatei unter ~/.config im Test liegt und
        # nicht die des Betreibers gelesen wird. cwd ist das Verzeichnis, aus dem
        # der Check startet, path_prefix steht vorne im PATH, extra_env kommt
        # zuletzt dazu.
        env = {k: v for k, v in os.environ.items() if not k.startswith("PTAI_")}
        env.update({"CHECK_ENV_OFFLINE": "1",
                    "CHECK_ENV_VERBOSE": "1", "CHECK_ENV_SHOPIFY_TIMEOUT": "5"})
        if central is not None:
            env["PTAI_ENV_FILE"] = str(central)
        if home is not None:
            env["HOME"] = str(home)
        if path_prefix is not None:
            env["PATH"] = f"{path_prefix}{os.pathsep}{env.get('PATH', '')}"
        if extra_env:
            env.update(extra_env)
        result = subprocess.run([BASH, str(SCRIPT), str(ws)], env=env, cwd=cwd,
                                capture_output=True, text=True, timeout=120)
        return result.returncode, result.stdout


class TestKeyLookup(CheckEnvCase):
    def test_dataforseo_only_in_the_central_file_is_found(self):
        # Die genaue OK-Zeile. "DataForSEO" und "zentral" in irgendeiner Zeile
        # reichten nicht: die FEHLT-Zeile ("weder im Workspace noch zentral in")
        # und die KAPUTT-Zeile zum geteilten Paar enthalten beide Wörter auch, und
        # der Test blieb grün, wenn die zentrale Suche nichts fand.
        central = self.central(PTAI_DFS_LOGIN="betreiber@example.com", PTAI_DFS_PASSWORD="x")
        _, out = self.run_check(self.workspace(), central)
        self.assertIn("DataForSEO: PTAI_DFS_LOGIN und PTAI_DFS_PASSWORD gefunden (zentral)", out)
        self.assertNotIn("betreiber@example.com", out)

    def test_google_credentials_are_never_taken_from_the_central_file(self):
        # Die Meldung selbst, nicht ein Vergleich der Exit-Codes: ob eine offene
        # Zeile mitzählt, hängt an ihrer Gruppe, und ein höherer Exit-Code kann
        # auch aus einer ganz anderen Zeile kommen.
        ws = self.workspace("central", env_lines=[])
        sa = ws / "secrets" / "google-sa.json"
        _, out = self.run_check(ws, self.central("sa.env", PTAI_GOOGLE_CREDENTIALS=sa))
        self.assertIn("Google-Dienstkonto für GA4 und Search Console: PTAI_GOOGLE_CREDENTIALS "
                      "nicht in der .env des Workspace gesetzt", out)
        self.assertNotIn("Service-Account-JSON vorhanden", out)

    def test_invalid_service_account_json_is_broken(self):
        # Offline lief eine Datei, die kein Service-Account-JSON ist, bisher als
        # "Pflicht vollständig." durch, weil check_env.sh nur -f prüfte. Der
        # GA4-Test-Call hätte online sofort verlangt, was schon vorhanden ist.
        ws = self.workspace("bad-json")
        sa = ws / "secrets" / "google-sa.json"
        sa.write_text("nicht json", encoding="utf-8")
        _, out = self.run_check(ws, self.central())
        self.assertIn("ist kein gültiges Service-Account-JSON", out)
        pflicht_offen = next((l for l in out.splitlines()
                              if l.startswith("Pflicht offen:")), "")
        self.assertIn("Google Analytics 4", pflicht_offen, out)
        self.assertIn("Google Search Console", pflicht_offen, out)

    def test_offline_skips_every_test_call(self):
        central = self.central(PTAI_DFS_LOGIN="a", PTAI_DFS_PASSWORD="b", PTAI_PSI_KEY="k")
        _, out = self.run_check(self.workspace(), central)
        self.assertIn("ausgelassen", out)
        self.assertNotIn("fehlgeschlagen", out)

    def test_unittest_is_not_an_operator_check(self):
        _, out = self.run_check(self.workspace(), self.central())
        self.assertNotIn("unittest", out)

    def test_dataforseo_login_and_password_from_different_places_is_broken(self):
        # get_together() nimmt beide aus der Ebene des Logins. Ein Login nur
        # zentral und ein Passwort nur im Workspace ist für die Pulls kein Paar.
        # Geprüft werden die Meldungszeilen, nicht der Exit-Code: ob eine offene
        # DataForSEO-Zeile mitzählt, hängt an der Gruppe, in der sie steht, und
        # das Paar ist kaputt, egal wie gezählt wird.
        sa = self.root / "split" / "secrets" / "google-sa.json"
        ws_split = self.workspace("split", env_lines=[f"PTAI_GOOGLE_CREDENTIALS={sa}",
                                                      "PTAI_DFS_PASSWORD=p"])
        _, out = self.run_check(
            ws_split, self.central("login.env", PTAI_DFS_LOGIN="betreiber@example.com"))
        lines = out.splitlines()
        self.assertTrue(any("DataForSEO" in l and "nicht an derselben Stelle" in l
                            for l in lines), out)
        self.assertFalse(any("PTAI_DFS_LOGIN und PTAI_DFS_PASSWORD gefunden" in l
                             for l in lines), out)
        self.assertNotIn("betreiber@example.com", out)

    def test_relative_service_account_path_resolves_in_the_workspace(self):
        # run_check setzt kein cwd, der Check startet also im Verzeichnis des
        # Test-Runners und nicht im Workspace. Die Pulls laufen im Workspace.
        central = self.central()
        rc_abs, _ = self.run_check(self.workspace("abs"), central)
        ws_rel = self.workspace("rel", env_lines=["PTAI_GOOGLE_CREDENTIALS=secrets/google-sa.json"])
        self.assertNotEqual(Path.cwd().resolve(), ws_rel.resolve())
        rc_rel, out = self.run_check(ws_rel, central)
        self.assertNotIn("die Datei existiert nicht", out)
        self.assertEqual(rc_rel, rc_abs, out)

    def test_relative_env_file_resolves_in_the_workspace(self):
        # Die Pulls und der DataForSEO-Test-Call laufen im Workspace, ein
        # relatives PTAI_ENV_FILE gilt also dort. Der Check startet hier in einem
        # anderen Verzeichnis, das eine gleichnamige Datei ohne Paar hält: löst er
        # gegen sein eigenes Arbeitsverzeichnis auf, findet er nichts.
        ws = self.workspace()
        (ws / "operator.env").write_text("PTAI_DFS_LOGIN=a\nPTAI_DFS_PASSWORD=b\n",
                                         encoding="utf-8")
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "operator.env").write_text("", encoding="utf-8")
        _, out = self.run_check(ws, "operator.env", cwd=elsewhere)
        self.assertIn("DataForSEO: PTAI_DFS_LOGIN und PTAI_DFS_PASSWORD gefunden (zentral)", out)

    @unittest.skipUnless(shutil.which("git"), "braucht git")
    def test_git_decides_whether_the_service_account_is_ignored(self):
        # Bis 11.09.2026 verglich der Check Pfadpräfixe und ließ jeden Pfad mit
        # ".." aus: ein nicht ignorierter Key unter keys/../keys/sa.json ergab gar
        # keine Zeile. Jetzt fragt er git, und git löst ".." selbst auf.
        ws = self.workspace("git")
        (ws / ".gitignore").write_text("secrets/\n", encoding="utf-8")
        (ws / "keys").mkdir()
        (ws / "keys" / "sa.json").write_text("{}", encoding="utf-8")
        self.git_repo(ws)
        central = self.central()
        cases = (
            ("secrets/google-sa.json", "google-sa.json ist gitignored"),
            ("secrets/../secrets/google-sa.json", "google-sa.json ist gitignored"),
            ("keys/../keys/sa.json", "sa.json liegt im Git-Repo, ist aber NICHT gitignored"),
        )
        for creds, expected in cases:
            with self.subTest(creds=creds):
                (ws / ".env").write_text(f"PTAI_GOOGLE_CREDENTIALS={creds}\n",
                                         encoding="utf-8")
                _, out = self.run_check(ws, central)
                self.assertTrue(any("Google-Dienstkonto für GA4 und Search Console:" in l
                                    and expected in l for l in out.splitlines()), out)

    @unittest.skipUnless(shutil.which("git"), "braucht git")
    def test_versioned_files_are_named_as_versioned(self):
        # git check-ignore antwortet für eine versionierte Datei mit Exit 1, auch
        # wenn die .gitignore sie trifft. Der Check riet dann, 'secrets/' in die
        # .gitignore aufzunehmen, obwohl die Zeile dort schon stand, und der
        # Schlüssel lag weiter im Repo.
        ws = self.workspace("tracked")
        (ws / ".gitignore").write_text("secrets/\n.env\n", encoding="utf-8")
        self.git_repo(ws)
        self.git(ws, "add", "-f", "secrets/google-sa.json", ".env")
        self.git(ws, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                 "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={self.root / 'no-hooks'}",
                 "commit", "-q", "-m", "x")
        _, out = self.run_check(ws, self.central())
        lines = out.splitlines()
        creds = [l for l in lines if "Google-Dienstkonto für GA4 und Search Console:" in l]
        self.assertTrue(any("ist im Git-Repo bereits versioniert" in l for l in creds), out)
        self.assertFalse(any("gitignored" in l for l in creds), out)
        self.assertTrue(any("Secrets: .env ist im Git-Repo bereits versioniert" in l
                            for l in lines), out)
        for path in (".env", "secrets/google-sa.json"):
            with self.subTest(path=path):
                self.assertIn(f"Versionierung: {path} ist bereits versioniert", out)
                self.assertNotIn(f"Versionierung: {path} ist ignoriert", out)

    def test_empty_env_file_variable_means_no_central_file(self):
        # env.py macht aus PTAI_ENV_FILE="" Path("") und findet dort nichts. Der
        # Check fiel bis 11.09.2026 auf die Standarddatei unter HOME zurück und
        # meldete ein Paar, das die Pulls nicht sehen. Das HOME des Tests hält
        # genau dort ein Paar. Der Lauf ohne PTAI_ENV_FILE belegt, dass der Check
        # es findet; ohne ihn bliebe der Lauf mit leerem Wert auch mit dem Fehler
        # grün, sobald sich der Standardpfad ändert.
        home = self.root / "home"
        default = home / ".config" / "ptai-ecom" / ".env"
        default.parent.mkdir(parents=True)
        default.write_text("PTAI_DFS_LOGIN=betreiber@example.com\nPTAI_DFS_PASSWORD=x\n",
                           encoding="utf-8")
        ws = self.workspace()
        _, out_unset = self.run_check(ws, None, home=home)
        self.assertIn("DataForSEO: PTAI_DFS_LOGIN und PTAI_DFS_PASSWORD gefunden (zentral)",
                      out_unset)
        _, out = self.run_check(ws, "", home=home)
        self.assertNotIn("PTAI_DFS_LOGIN und PTAI_DFS_PASSWORD gefunden", out)
        self.assertIn("DataForSEO: PTAI_DFS_LOGIN und PTAI_DFS_PASSWORD nicht gefunden", out)
        self.assertNotIn("betreiber@example.com", out_unset + out)


GROUP = re.compile(r"^\[(?:ok|\d+ offen)\] (.+?)(?: \(\d+ geprüft\))?$")


class TestTiers(CheckEnvCase):
    def groups(self, out):
        return [m.group(1) for m in map(GROUP.match, out.splitlines()) if m]

    def closing(self, out, prefix):
        return next((l for l in out.splitlines() if l.startswith(prefix)), "")

    def test_groups_follow_the_tier_order(self):
        _, out = self.run_check(self.workspace(), self.central())
        order = ["Rechner", "Pflicht", "Empfohlen", "Optional", "Workspace"]
        seen = [g for g in self.groups(out) if g in order]
        self.assertEqual(seen, [g for g in order if g in seen], out)
        self.assertIn("Pflicht", seen)

    def test_required_complete_when_nothing_required_is_open(self):
        _, out = self.run_check(self.workspace(), self.central(),
                                path_prefix=self.shopify_stub())
        self.assertIn("Pflicht vollständig.", out)

    def test_missing_dataforseo_does_not_change_the_exit_code(self):
        ws = self.workspace()
        rc_with, _ = self.run_check(ws, self.central("mit.env", PTAI_DFS_LOGIN="a",
                                                     PTAI_DFS_PASSWORD="b"))
        rc_without, out = self.run_check(ws, self.central("ohne.env"))
        self.assertEqual(rc_with, rc_without, out)
        self.assertIn("DataForSEO", self.closing(out, "Offen, empfohlen:"), out)

    def test_ga4_switched_off_adds_one_open_point(self):
        rc_on, _ = self.run_check(self.workspace("on"), self.central())
        ws_off = self.workspace("off", sources={"ga4": False}, drop=("ga4_property_id",))
        rc_off, out = self.run_check(ws_off, self.central())
        self.assertEqual(rc_off, rc_on + 1, out)
        self.assertIn("in der Config abgeschaltet", out)
        self.assertIn("Google Analytics 4", self.closing(out, "Pflicht offen:"), out)

    def test_missing_google_credentials_counts_once(self):
        # Bis 11.09.2026 zählte eine fehlende PTAI_GOOGLE_CREDENTIALS dreifach:
        # die Dienstkonto-Zeile, dann "GA4-Test-Call: nicht möglich", dann
        # "GSC-Test-Call: nicht möglich". Der Grund steht nur einmal oben, wie
        # bei Shopify ohne CLI.
        rc_ready, _ = self.run_check(self.workspace("ready"), self.central())
        ws_missing = self.workspace("missing", env_lines=[])
        rc_missing, out = self.run_check(ws_missing, self.central())
        self.assertEqual(rc_missing, rc_ready + 1, out)
        pflicht_offen = next((l for l in out.splitlines()
                              if l.startswith("Pflicht offen:")), "")
        self.assertIn("Google Analytics 4", pflicht_offen, out)
        self.assertIn("Google Search Console", pflicht_offen, out)
        self.assertEqual(out.count("Ohne Google Analytics 4 fehlt:"), 1, out)
        self.assertEqual(out.count("Ohne Google Search Console fehlt:"), 1, out)

    def test_no_verbose_tip_when_already_verbose(self):
        # run_check setzt CHECK_ENV_VERBOSE=1 für jeden Lauf. Der Tipp, ihn zu
        # setzen, ist unter diesem Modus sinnlos und muss verschwinden, sobald
        # überhaupt ein offener Punkt den Hinweis auslösen würde.
        ws_off = self.workspace("verbose-tip", sources={"ga4": False},
                                drop=("ga4_property_id",))
        _, out = self.run_check(ws_off, self.central())
        self.assertNotIn("CHECK_ENV_VERBOSE=1 vor den Aufruf setzen", out)

    def test_shopify_all_off_gives_a_single_line(self):
        ws = self.workspace(sources={"shopify": False, "catalogue": False, "shop_tech": False},
                            drop=("shopify_store",))
        _, out = self.run_check(ws, self.central())
        hits = [l for l in out.splitlines() if "Shopify" in l and "abgeschaltet" in l]
        self.assertEqual(len(hits), 1, out)

    def test_no_geo_key_anywhere_is_open_but_not_counted(self):
        ws = self.workspace()
        rc_key, _ = self.run_check(ws, self.central("key.env", PTAI_GEMINI_KEY="g"))
        rc_none, out = self.run_check(ws, self.central("none.env"))
        self.assertEqual(rc_key, rc_none, out)
        self.assertIn("GEO-Keys", self.closing(out, "Offen, empfohlen:"), out)


class TestBrowser(CheckEnvCase):
    """Die Zeile zum Browser für PDFs und Screenshots (scripts/lib/find_chrome.sh).

    Das HOME des Tests hält höchstens die Attrappe einer Headless Shell. Der
    Check startet sie nie, er fragt nur, ob es sie gibt.
    """

    def test_the_found_binary_is_named(self):
        home = self.root / "home"
        shell = (home / "Library" / "Caches" / "ms-playwright" / "chromium_headless_shell-1234"
                 / "chrome-headless-shell-mac-arm64" / "chrome-headless-shell")
        shell.parent.mkdir(parents=True)
        shell.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        shell.chmod(0o755)
        _, out = self.run_check(self.workspace(), self.central(), home=home,
                                extra_env={"PLAYWRIGHT_BROWSERS_PATH": ""})
        self.assertIn(f"Browser: Headless Shell von Playwright gefunden ({shell})", out)

    @unittest.skipIf(any(shutil.which(n) for n in ("google-chrome", "chromium", "chromium-browser")),
                     "ein Chrome oder Chromium im PATH des Rechners")
    def test_nothing_found_names_both_options(self):
        home = self.root / "empty-home"
        system = self.root / "empty-system"
        home.mkdir()
        system.mkdir()
        _, out = self.run_check(self.workspace(), self.central(), home=home,
                                extra_env={"PLAYWRIGHT_BROWSERS_PATH": "",
                                           "FIND_CHROME_SYSTEM_ROOT": str(system)})
        line = next((l for l in out.splitlines() if "Browser:" in l), "")
        self.assertIn("weder die Headless Shell von Playwright noch Google Chrome oder Chromium", line, out)
        self.assertIn("npx playwright install chromium-headless-shell", line, out)


class TestCustomerFolder(CheckEnvCase):
    """Kundenordner und Einstellungen des Betreibers (Spec 2026-09-11 public release, A1)."""

    def test_an_unset_accounts_root_is_a_hint_with_the_default(self):
        _, out = self.run_check(self.workspace(), self.central())
        line = next((l for l in out.splitlines() if "PTAI_ACCOUNTS_ROOT nicht gesetzt" in l), "")
        self.assertIn("Hinweis:", line, out)
        self.assertIn("~/ptai-ecom/accounts", line, out)

    def test_the_accounts_root_never_changes_the_exit_code(self):
        ws = self.workspace()
        existing = self.root / "kunden"
        existing.mkdir()
        rc_unset, _ = self.run_check(ws, self.central("leer.env"))
        rc_set, out_set = self.run_check(ws, self.central("da.env", PTAI_ACCOUNTS_ROOT=existing))
        rc_missing, out_missing = self.run_check(
            ws, self.central("fehlt.env", PTAI_ACCOUNTS_ROOT=self.root / "nicht-eingebunden"))
        self.assertEqual((rc_set, rc_missing), (rc_unset, rc_unset), out_missing)
        self.assertIn("PTAI_ACCOUNTS_ROOT gesetzt (zentral)", out_set)
        self.assertIn("den Ordner gibt es nicht", out_missing)

    def test_the_operator_name_is_a_hint_and_its_value_never_shows(self):
        ws = self.workspace()
        rc_unset, out_unset = self.run_check(ws, self.central("leer.env"))
        rc_set, out_set = self.run_check(
            ws, self.central("name.env", PTAI_OPERATOR_NAME="Beispiel Beratung"))
        self.assertEqual(rc_unset, rc_set, out_set)
        self.assertIn("PTAI_OPERATOR_NAME nicht gesetzt", out_unset)
        self.assertIn("PTAI_OPERATOR_NAME gesetzt (zentral)", out_set)
        self.assertNotIn("Beispiel Beratung", out_set)

    def test_a_missing_account_slug_names_no_workos_folder(self):
        _, out = self.run_check(self.workspace(drop=("account_slug",)), self.central())
        self.assertIn("Name des Kundenordners unter PTAI_ACCOUNTS_ROOT", out)
        self.assertNotIn("02-accounts", out)

    def test_a_relative_drive_path_names_the_customer_folder(self):
        _, out = self.run_check(self.workspace(drive_path="kunden/beispielshop"), self.central())
        self.assertIn("muss der volle Pfad zum Kundenordner sein", out)
        self.assertNotIn("Drive-Wurzel", out)


if __name__ == "__main__":
    unittest.main()
