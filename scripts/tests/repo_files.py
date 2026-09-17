"""Welche Dateien zum Plugin gehören, mit und ohne git. Kein Test.

Im privaten Repo entscheidet `git ls-files`: ein Kunden-Workspace neben dem Repo
und eine unversionierte Skill einer anderen Sitzung gehören nicht dazu. Die
öffentliche Fassung entsteht aus `git archive` und läuft ihre Tests in einem
Ordner ohne `.git` (`release/build.sh`); wer sie als ZIP herunterlädt, hat
ebenfalls keins. Dort zählt jede Datei unter der Wurzel, außer Caches.

Bis Teil C riefen zwei Tests `git ls-files` mit `check=True` und brachen in
genau dieser Kopie ab (Spec 2026-09-11 public release, C3).
"""
import os
import subprocess
from pathlib import Path

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".claude"}


def tracked(root) -> list[str]:
    """Pfade relativ zur Wurzel, mit `/`, sortiert."""
    root = Path(root)
    if (root / ".git").exists():
        out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True,
                             text=True, check=True).stdout
        return sorted(name for name in out.split("\0") if name)
    names = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        names += [Path(dirpath, f).relative_to(root).as_posix() for f in filenames]
    return sorted(names)


def text_files(root, suffixes: tuple, exempt=()):
    """Name und Inhalt jeder Textdatei mit passender Endung, ohne die Ausnahmen."""
    for name in tracked(root):
        if name in exempt or not name.endswith(suffixes):
            continue
        try:
            yield name, (Path(root) / name).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
