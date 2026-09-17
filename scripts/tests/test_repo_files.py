"""Welche Dateien zum Plugin gehören, mit und ohne git (scripts/tests/repo_files.py)."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import repo_files

ROOT = Path(__file__).resolve().parents[2]


class TestRepoFiles(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def write(self, name, content="x\n"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")

    def test_without_git_every_file_counts_except_caches(self):
        for name in ("a.md", "sub/b.py", "__pycache__/c.pyc", "node_modules/d.js", ".claude/e.md"):
            self.write(name)
        self.assertEqual(repo_files.tracked(self.root), ["a.md", "sub/b.py"])

    @unittest.skipUnless(shutil.which("git"), "braucht git")
    def test_with_git_only_tracked_files_count(self):
        self.write("a.md")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.root), "add", "a.md"], check=True, capture_output=True)
        self.write("b.md")
        self.assertEqual(repo_files.tracked(self.root), ["a.md"])

    def test_text_files_skip_other_suffixes_undecodable_and_exempt(self):
        self.write("a.md", "Text\n")
        self.write("b.bin", "Text\n")
        self.write("c.json", b"\xff\xfe\x00")
        self.write("d.md", "ausgenommen\n")
        found = list(repo_files.text_files(self.root, (".md", ".json"), exempt={"d.md"}))
        self.assertEqual(found, [("a.md", "Text\n")])

    def test_this_repo_lists_its_test_runner(self):
        self.assertIn("scripts/run_tests.sh", repo_files.tracked(ROOT))


if __name__ == "__main__":
    unittest.main()
