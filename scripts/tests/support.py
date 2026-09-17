"""Hilfen für Tests mit Kundenordnern. Kein Test.

Jeder Test, der `account.accounts_root()` erreicht, braucht eine eigene Wurzel.
Ohne sie läse er auf dem Rechner eines Betreibers dessen Einstellung und legte
im schlimmsten Fall einen Kunden in dessen echtem Kundenordner an.
"""
import os
import tempfile
from pathlib import Path

from audit import env


def temp_accounts_root(case) -> Path:
    """Richtet einen Test auf eine Wurzel im Temp-Ordner aus und gibt sie zurück.

    Setzt `PTAI_ACCOUNTS_ROOT` auf `<tmp>/accounts` und `HOME` auf `<tmp>/home`,
    beide angelegt, damit auch die Vorgabe `~/ptai-ecom/accounts` im Temp-Ordner
    landet. `env.CENTRAL` zeigt auf `<tmp>/keine-zentrale.env`, die es nicht
    gibt. Alles wird über `case.addCleanup` zurückgesetzt.
    """
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    base = Path(tmp.name)
    root = base / "accounts"
    root.mkdir()
    (base / "home").mkdir()
    _set_env(case, "PTAI_ACCOUNTS_ROOT", str(root))
    _set_env(case, "HOME", str(base / "home"))
    old_central = env.CENTRAL
    env.CENTRAL = base / "keine-zentrale.env"
    case.addCleanup(setattr, env, "CENTRAL", old_central)
    return root


def _set_env(case, name: str, value: str) -> None:
    old = os.environ.get(name)
    os.environ[name] = value
    if old is None:
        case.addCleanup(os.environ.pop, name, None)
    else:
        case.addCleanup(os.environ.__setitem__, name, old)
