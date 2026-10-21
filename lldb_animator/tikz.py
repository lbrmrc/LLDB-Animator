"""Elementi TikZ e loro rendering in testo."""

from __future__ import annotations

from dataclasses import dataclass, replace

_TEX_SPECIAL = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def tex_escape(s: str) -> str:
    return "".join(_TEX_SPECIAL.get(c, c) for c in s)


def num(x: float) -> str:
    """Formatta un numero con al massimo 3 decimali, senza zeri inutili."""
    s = f"{x:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class Node:
    content: str
    at: Point | str | None = None
    options: tuple[str, ...] = ()
    id: str | None = None


@dataclass(frozen=True)
class Path:
    """Un `\\draw` fra punti (o nomi di nodi)."""

    points: tuple[Point | str, ...]
    options: tuple[str, ...] = ()
    out_in: tuple[int, int] | None = None


Element = Node | Path


def mark_changed(element: Element) -> Element:
    return replace(element, options=element.options + ("changed",))


def _point(p: Point | str) -> str:
    if isinstance(p, Point):
        return f"({num(p.x)},{num(p.y)})"
    return f"({p})"


def render(element: Element) -> str:
    opts = ",".join(element.options)
    if isinstance(element, Node):
        at = "" if element.at is None else f"at {_point(element.at)}"
        ident = "" if element.id is None else f"({element.id})"
        return f"\\node [{opts}] {at} {ident} {{{element.content}}}"
    if element.out_in is None:
        joiner = " -- "
    else:
        out, in_ = element.out_in
        joiner = f" to[out={out},in={in_}] "
    return f"\\draw [{opts}] " + joiner.join(_point(p) for p in element.points)


def code(s: str) -> str:
    return f"\\texttt{{{tex_escape(s)}}}"


def small(s: str) -> str:
    return f"\\texttt{{\\tiny{{{tex_escape(s)}}}}}"
