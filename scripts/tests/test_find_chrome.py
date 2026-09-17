"""scripts/lib/find_chrome.sh: welcher Browser PDFs und Screenshots rendert.

Die Headless Shell von Playwright kommt vor Google Chrome und Chromium. Ein
headless gestartetes Google Chrome öffnet auf macOS den Dialog
"Schlüsselbund nicht gefunden" und hängt, bis jemand klickt; die Shell braucht
keinen Schlüsselbund und beendet sich sauber. Wer nur Chrome oder Chromium hat,
rendert weiter damit.

Kein Test startet einen echten Browser. Die Attrappen für die Suche schreiben
beim Aufruf eine Markierung, und die Suche prüft, dass sie fehlt. HOME, PATH und
FIND_CHROME_SYSTEM_ROOT zeigen in ein Wegwerf-Verzeichnis, damit ein Chrome
unter /Applications des Rechners nie mitspielt.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "lib" / "find_chrome.sh"
RENDER_PDF = ROOT / "skills" / "report" / "scripts" / "render_pdf.sh"
SHOOT = ROOT / "skills" / "capture-screens" / "scripts" / "shoot.sh"
CHECK_ENV = ROOT / "scripts" / "check_env.sh"

# Das bash des Systems: auf macOS 3.2, und genau dort soll ein Rückfall auffallen.
BASH = "/bin/bash" if Path("/bin/bash").exists() else "bash"

CHROME_APP = Path("Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
CHROMIUM_APP = Path("Applications/Chromium.app/Contents/MacOS/Chromium")
PLAYWRIGHT_CACHE = Path("Library/Caches/ms-playwright")

# Eine Attrappe für shoot.sh: lädt keine Seite, schreibt das Bild, das
# --screenshot verlangt, und druckt als DOM, was FAKE_DOM vorgibt.
FAKE_BROWSER = """#!/bin/sh
for arg in "$@"; do
  case "$arg" in
    --screenshot=*) printf png > "${arg#--screenshot=}" ;;
  esac
done
printf '%s\\n' "$FAKE_DOM"
"""


def browser_on_path():
    return any(shutil.which(name) for name in ("google-chrome", "chromium", "chromium-browser"))


class FindChromeCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        self.system = self.root / "system"
        self.bin = self.root / "bin"
        self.marker = self.root / "executed"
        for directory in (self.home, self.system, self.bin):
            directory.mkdir()

    def fake(self, path, content=None):
        # Ohne content eine Attrappe, die beim Aufruf die Markierung schreibt.
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content or f"#!/bin/sh\ntouch '{self.marker}'\n", encoding="utf-8")
        path.chmod(0o755)
        return path

    def shell_path(self, number, platform="mac-arm64", base=None):
        base = self.home / PLAYWRIGHT_CACHE if base is None else base
        return (base / f"chromium_headless_shell-{number}"
                / f"chrome-headless-shell-{platform}" / "chrome-headless-shell")

    def shell(self, number, platform="mac-arm64", base=None):
        return self.fake(self.shell_path(number, platform, base))

    def env(self, **extra):
        env = {"HOME": str(self.home), "PATH": str(self.bin),
               "FIND_CHROME_SYSTEM_ROOT": str(self.system)}
        env.update(extra)
        return env

    def helper(self, script, *args, **extra):
        # Dieselben Optionen wie in den drei Aufrufern.
        result = subprocess.run(
            [BASH, "-c", f'set -euo pipefail; . "$0"; {script}', str(HELPER), *args],
            env=self.env(**extra), capture_output=True, text=True, timeout=30)
        self.assertFalse(self.marker.exists(), "die Suche hat eine Attrappe gestartet")
        return result

    def find(self, **extra):
        return self.helper("find_chrome", **extra)


class TestShellFirst(FindChromeCase):
    def test_the_highest_number_wins_even_when_it_sorts_lower_as_text(self):
        # Als Text steht "999" hinter "1000", der Zahl nach davor. Wer als Text
        # sortiert, nimmt die ältere Shell.
        self.shell(999)
        newer = self.shell(1000)
        result = self.find()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, str(newer))

    def test_every_platform_folder_counts(self):
        for platform in ("mac-arm64", "mac-x64", "linux64"):
            with self.subTest(platform=platform):
                shutil.rmtree(self.home / "Library", ignore_errors=True)
                shell = self.shell(1234, platform)
                result = self.find()
                self.assertEqual(result.stdout, str(shell), result.stderr)

    def test_the_linux_cache_and_playwright_browsers_path_are_searched(self):
        linux = self.shell(1223, "linux64", base=self.home / ".cache" / "ms-playwright")
        self.assertEqual(self.find().stdout, str(linux))
        browsers = self.root / "browsers"
        custom = self.shell(1234, base=browsers)
        self.assertEqual(self.find(PLAYWRIGHT_BROWSERS_PATH=str(browsers)).stdout, str(custom))

    def test_a_half_installed_shell_is_skipped(self):
        # Ein abgebrochener Download hinterlässt den Ordner ohne ausführbare Datei.
        shell = self.shell(1234)
        (self.home / PLAYWRIGHT_CACHE / "chromium_headless_shell-1300").mkdir()
        not_executable = self.shell(1301)
        not_executable.chmod(0o644)
        self.assertEqual(self.find().stdout, str(shell))

    def test_the_shell_wins_over_chrome_and_chromium(self):
        shell = self.shell(1208)
        self.fake(self.system / CHROME_APP)
        self.fake(self.home / CHROME_APP)
        self.fake(self.system / CHROMIUM_APP)
        self.fake(self.bin / "chromium")
        result = self.find()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, str(shell))


class TestChromeFallback(FindChromeCase):
    def test_without_a_shell_the_chrome_candidates_keep_their_order(self):
        # Die Reihenfolge von vor der Shell. Jeder Gewinner wird danach entfernt,
        # dann muss der nächste gewinnen.
        candidates = [self.system / CHROME_APP, self.home / CHROME_APP,
                      self.system / CHROMIUM_APP, self.bin / "google-chrome",
                      self.bin / "chromium", self.bin / "chromium-browser"]
        for path in candidates:
            self.fake(path)
        for expected in candidates:
            with self.subTest(expected=str(expected.relative_to(self.root))):
                result = self.find()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, str(expected))
            expected.unlink()

    def test_nothing_found_is_an_error(self):
        result = self.find()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")

    def test_the_name_says_which_binary_it_is(self):
        cases = {
            self.shell(1234): "Headless Shell von Playwright",
            self.fake(self.system / CHROME_APP): "Google Chrome",
            self.fake(self.system / CHROMIUM_APP): "Chromium",
            self.fake(self.bin / "google-chrome"): "Google Chrome",
            self.fake(self.bin / "chromium-browser"): "Chromium",
        }
        for path, name in cases.items():
            with self.subTest(name=name, path=path.name):
                result = self.helper('browser_name "$1"', str(path))
                self.assertEqual(result.stdout, name, result.stderr)

    def test_sourcing_leaves_the_shell_options_alone(self):
        # Die Aufrufer laufen unter set -euo pipefail. Ein Helfer, der eine Option
        # an- oder abschaltet, ändert still ihr Verhalten bei Fehlern.
        options = 'shopt -po errexit nounset pipefail || true'
        for preamble in ("set -euo pipefail", "set +euo pipefail"):
            with self.subTest(preamble=preamble):
                script = (f'{preamble}; before="$({options})"; . "$0"; '
                          f'find_chrome >/dev/null || true; after="$({options})"; '
                          f'[ "$before" = "$after" ] || {{ echo "$before" "$after"; exit 3; }}')
                result = subprocess.run([BASH, "-c", script, str(HELPER)], env=self.env(),
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class TestOneLookup(unittest.TestCase):
    def test_no_script_carries_its_own_candidate_list(self):
        for path in (RENDER_PDF, SHOOT, CHECK_ENV):
            text = path.read_text(encoding="utf-8")
            with self.subTest(script=path.name):
                self.assertNotIn("Google Chrome.app", text)
                self.assertIn("lib/find_chrome.sh", text)


@unittest.skipIf(browser_on_path(), "ein Chrome oder Chromium im PATH des Rechners")
class TestCallersWithoutBrowser(FindChromeCase):
    """Die Aufrufer brechen ohne Browser ab und nennen beide Wege.

    PATH ist hier der des Rechners, weil die Skripte dirname und jq brauchen.
    Deshalb nur ohne Chrome oder Chromium im PATH.
    """

    def run_caller(self, *args):
        return subprocess.run([BASH, *args], env=self.env(PATH=os.environ.get("PATH", "")),
                              capture_output=True, text=True, timeout=60)

    def assert_names_both_options(self, text):
        self.assertIn("npx playwright install chromium-headless-shell", text)
        self.assertIn("Google Chrome oder Chromium", text)

    def test_render_pdf_names_both_options(self):
        html = self.root / "in.html"
        html.write_text("<p>x</p>\n", encoding="utf-8")
        pdf = self.root / "out.pdf"
        result = self.run_caller(str(RENDER_PDF), str(html), str(pdf))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assert_names_both_options(result.stderr)
        self.assertFalse(pdf.exists())

    @unittest.skipUnless(shutil.which("jq"), "shoot.sh bricht ohne jq vorher ab")
    def test_shoot_names_both_options(self):
        target = self.root / "shots"
        result = self.run_caller(str(SHOOT), "--url", "http://127.0.0.1:9/",
                                 "--name", "start", "--target", str(target))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assert_names_both_options(result.stderr)
        self.assertEqual(list(target.glob("*.png")), [])


@unittest.skipUnless(shutil.which("jq"), "shoot.sh bricht ohne jq vorher ab")
class TestShootIndex(FindChromeCase):
    """Was shoot.sh je Browser über Breite und leere Seiten in den Index schreibt.

    Die Attrappe lädt nichts, die URL geht nirgends hin. Eine falsche Breite im
    Index ist die Sorte Fehler, die im Report niemandem auffällt: eine Linse
    hielte einen beschnittenen 500er für eine Handy-Ansicht oder umgekehrt.
    """

    PAGE = "<!DOCTYPE html>\n<html><head><title>x</title></head><body><p>Shop</p></body></html>"

    def shoot(self, dom=PAGE):
        target = self.root / "shots"
        result = subprocess.run(
            [BASH, str(SHOOT), "--url", "http://127.0.0.1:9/", "--name", "start",
             "--target", str(target)],
            env=self.env(PATH=os.environ.get("PATH", ""), FAKE_DOM=dom, SHOOT_TIMEOUT="20"),
            capture_output=True, text=True, timeout=60)
        images = []
        for line in result.stdout.splitlines():
            if line.startswith("IMAGES_JSON: "):
                images = json.loads(line[len("IMAGES_JSON: "):])
        return result, {image["device"]: image for image in images}, target

    def test_the_shell_records_the_requested_mobile_width(self):
        self.fake(self.shell_path(1234), FAKE_BROWSER)
        result, images, _ = self.shoot()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((images["mobil"]["viewport_width"], images["mobil"]["viewport_clamped"]),
                         (390, False))
        self.assertNotIn("500px", result.stderr)

    def test_chrome_stays_clamped_at_500(self):
        self.fake(self.system / CHROME_APP, FAKE_BROWSER)
        result, images, _ = self.shoot()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((images["mobil"]["viewport_width"], images["mobil"]["viewport_clamped"]),
                         (500, True))
        self.assertEqual((images["desktop"]["viewport_width"], images["desktop"]["viewport_clamped"]),
                         (1440, False))
        self.assertIn("500px", result.stderr)

    def test_the_empty_page_of_a_failed_load_is_discarded(self):
        self.fake(self.shell_path(1234), FAKE_BROWSER)
        result, images, target = self.shoot(dom="<html><head></head><body></body></html>")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(images, {})
        self.assertEqual(list(target.glob("*.png")), [])
        self.assertIn("nicht erreichbar oder leer", result.stderr)


if __name__ == "__main__":
    unittest.main()
