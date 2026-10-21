"""Import del modulo `lldb`, anche quando non è installato nel venv."""

from __future__ import annotations

import shutil
import subprocess
import sys
from types import ModuleType


def import_lldb() -> ModuleType:
    """Restituisce il modulo `lldb`.

    LLDB non è su PyPI: il modulo Python viene installato insieme al debugger.
    Se `import lldb` fallisce si chiede a `lldb -P` dove si trova e lo si
    aggiunge a `sys.path` (in coda, per non oscurare i pacchetti del venv).
    """
    try:
        import lldb
        return lldb
    except ImportError:
        pass

    exe = shutil.which("lldb")
    if exe is None:
        raise ImportError("modulo 'lldb' non trovato e comando 'lldb' non installato "
                          "(es. 'pacman -S lldb' o 'apt install lldb')")
    path = subprocess.run([exe, "-P"], capture_output=True, text=True).stdout.strip()
    if path and path not in sys.path:
        sys.path.append(path)
    try:
        import lldb
        return lldb
    except ImportError as e:
        raise ImportError(
            f"il modulo 'lldb' in {path or '?'} non è importabile da Python "
            f"{sys.version_info.major}.{sys.version_info.minor}: probabilmente è stato "
            f"compilato per un'altra versione di Python ({e})") from e
