"""API pubblica: `animate()`."""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .layout import Layout, Scene, Show
from .model import Snapshot
from .timeline import build_tikz

PathLike = str | os.PathLike


class CompilationError(RuntimeError):
    pass


@dataclass
class Animation:
    """Risultato di `animate()`."""

    tikz: str
    snapshots: list[Snapshot]
    stdout: str = ""
    exit_code: int | None = None
    warnings: list[str] = field(default_factory=list)
    output: Path | None = None

    def __len__(self) -> int:
        return len(self.snapshots)


def compile_sources(sources: Sequence[Path], destination: Path, compiler: str,
                    cflags: Sequence[str]) -> None:
    cmd = [compiler, *cflags, "-o", str(destination), *map(str, sources)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise CompilationError(f"compilatore non trovato: {compiler}") from None
    if result.returncode != 0:
        raise CompilationError(f"compilazione fallita ({' '.join(cmd)}):\n{result.stderr}")


def _count_lines(path: Path) -> int:
    with open(path, errors="replace") as f:
        return sum(1 for _ in f)


def animate(sources: PathLike | Sequence[PathLike],
            breakpoints: Sequence[int | str | tuple[str, int]],
            show: "Show | str | Sequence[str | Show]" = Show.CODE | Show.STACK | Show.HEAP,
            *,
            output: PathLike | None = None,
            stdin_file: PathLike | None = None,
            stdin_text: str | None = None,
            args: Sequence[str] = (),
            executable: PathLike | None = None,
            compiler: str = "cc",
            cflags: Sequence[str] = ("-g", "-O0"),
            layout: Layout | None = None,
            timeout: float | None = 30.0) -> Animation:
    """Esegue un programma C sotto LLDB e ne genera l'animazione TikZ.

    Args:
        sources: file C da compilare (e da mostrare). Il primo è quello a cui
            si riferiscono i breakpoint espressi solo come numero di riga.
        breakpoints: dove fermarsi per scattare uno snapshot. Ogni elemento è
            una riga (`12` o `"12"`), `"file.c:12"`, `("file.c", 12)` oppure il
            nome di una funzione (`"main"`).
        show: cosa visualizzare: un `Show` (es. `Show.CODE | Show.STACK`), una
            stringa (`"code,stack,heap"`) o un elenco di nomi.
        output: file `.tex` da scrivere (da includere in una `tikzpicture`
            Beamer). Se omesso, il TikZ è solo nel valore restituito.
        stdin_file: file da cui il programma legge lo standard input.
        stdin_text: alternativa a `stdin_file`: il testo dello standard input.
        args: argomenti da riga di comando del programma.
        executable: eseguibile già compilato con `-g`; se omesso si compila.
        compiler, cflags: compilatore e opzioni (servono informazioni di debug).
        layout: posizioni e dimensioni dei pannelli.
        timeout: secondi massimi di esecuzione (None per nessun limite).
    """
    # Import qui per poter usare gli altri moduli senza avere LLDB installato.
    from .collector import Tracer, parse_breakpoint

    if isinstance(sources, (str, os.PathLike)):
        sources = [sources]
    source_paths = [Path(s).resolve() for s in sources]
    for s in source_paths:
        if not s.is_file():
            raise FileNotFoundError(s)
    if not source_paths:
        raise ValueError("serve almeno un file sorgente")
    if stdin_file is not None and stdin_text is not None:
        raise ValueError("usare solo uno fra stdin_file e stdin_text")

    show = Show.parse(show)
    layout = layout or Layout()
    specs = [parse_breakpoint(b, source_paths[0].name) for b in breakpoints]
    output_path = Path(output).resolve() if output is not None else None

    with tempfile.TemporaryDirectory(prefix="lldb-animator-") as tmp:
        if executable is None:
            exe = Path(tmp) / source_paths[0].stem
            compile_sources(source_paths, exe, compiler, cflags)
        else:
            exe = Path(executable).resolve()

        if stdin_text is not None:
            stdin_path = Path(tmp) / "stdin.txt"
            stdin_path.write_text(stdin_text)
        else:
            stdin_path = Path(stdin_file).resolve() if stdin_file is not None else None

        trace = Tracer(
            str(exe), [str(s) for s in source_paths], specs,
            track_heap=Show.HEAP in show,
            track_stdin=Show.STDIN in show,
            track_stdout=Show.STDOUT in show,
            args=args, stdin_file=str(stdin_path) if stdin_path else None,
            timeout=timeout).run()

    base = output_path.parent if output_path is not None else None

    def listing_path(file: str) -> str:
        return os.path.relpath(file, base) if base is not None else file

    scene = Scene(layout, show, listing_path,
                  code_lines=max(_count_lines(s) for s in source_paths))
    tikz = build_tikz([scene.elements(snap) for snap in trace.snapshots])

    if output_path is not None:
        output_path.write_text(tikz)
    return Animation(tikz=tikz, snapshots=trace.snapshots, stdout=trace.stdout,
                     exit_code=trace.exit_code, warnings=trace.warnings,
                     output=output_path)
