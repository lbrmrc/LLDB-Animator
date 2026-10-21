"""Interfaccia a riga di comando."""

from __future__ import annotations

import argparse
import shlex
import sys
from typing import Sequence

from .api import CompilationError, animate
from .layout import Show


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lldb-animator",
        description="Genera un'animazione TikZ/Beamer dell'esecuzione di un programma C.")
    p.add_argument("sources", nargs="+", metavar="SORGENTE.c",
                   help="file C; il primo è quello dei breakpoint dati come sola riga")
    p.add_argument("-b", "--breakpoint", action="append", required=True, metavar="BP",
                   dest="breakpoints",
                   help="riga (12), file:riga (prog.c:12) o funzione (main); ripetibile")
    p.add_argument("-s", "--show", default="code,stack,heap", metavar="LISTA",
                   help="elementi da mostrare, separati da virgola: "
                        "code, stack, heap, stdin, stdout, all (default: code,stack,heap)")
    p.add_argument("-o", "--output", required=True, metavar="FILE.tex",
                   help="file TikZ da scrivere")
    p.add_argument("--stdin", metavar="FILE", dest="stdin_file",
                   help="file da usare come standard input")
    p.add_argument("--stdin-text", metavar="TESTO",
                   help="testo da usare come standard input (alternativo a --stdin)")
    p.add_argument("--executable", metavar="FILE",
                   help="eseguibile già compilato con -g (default: compila i sorgenti)")
    p.add_argument("--cc", default="cc", metavar="CMD", help="compilatore (default: cc)")
    p.add_argument("--cflags", default="-g -O0", metavar="FLAG",
                   help="opzioni di compilazione (default: '-g -O0')")
    p.add_argument("--timeout", type=float, default=30.0, metavar="SEC",
                   help="tempo massimo di esecuzione (0 = illimitato, default: 30)")
    p.add_argument("--args", nargs=argparse.REMAINDER, default=[], metavar="ARG",
                   help="argomenti del programma (tutto quello che segue)")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    opts = build_parser().parse_args(argv)
    try:
        show = Show.parse(opts.show)
        result = animate(
            opts.sources, opts.breakpoints, show,
            output=opts.output, stdin_file=opts.stdin_file, stdin_text=opts.stdin_text,
            args=opts.args, executable=opts.executable, compiler=opts.cc,
            cflags=shlex.split(opts.cflags), timeout=opts.timeout or None)
    except (CompilationError, FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"errore: {e}", file=sys.stderr)
        return 1
    for w in result.warnings:
        print(f"attenzione: {w}", file=sys.stderr)
    print(f"{len(result)} snapshot scritti in {result.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
