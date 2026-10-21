"""Layout: da uno `Snapshot` agli elementi TikZ da disegnare."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .model import Cell, HeapBlock, IOBuffer, Snapshot
from .tikz import Element, Node, Path, Point, code, num, small, tex_escape


class Show(enum.Flag):
    """Cosa visualizzare."""

    CODE = enum.auto()
    STACK = enum.auto()
    HEAP = enum.auto()
    STDIN = enum.auto()
    STDOUT = enum.auto()
    IO = STDIN | STDOUT
    ALL = CODE | STACK | HEAP | STDIN | STDOUT

    @classmethod
    def parse(cls, spec: "Show | str | Iterable[str | Show]") -> "Show":
        """Accetta un `Show`, una stringa ("code,stack") o un elenco di nomi."""
        if isinstance(spec, Show):
            return spec
        if isinstance(spec, str):
            spec = spec.replace(",", " ").split()
        result = Show(0)
        for item in spec:
            if isinstance(item, Show):
                result |= item
                continue
            try:
                result |= cls[item.strip().upper()]
            except KeyError:
                names = ", ".join(n.lower() for n in cls.__members__)
                raise ValueError(
                    f"elemento da visualizzare sconosciuto: {item!r} (validi: {names})"
                ) from None
        return result


@dataclass(frozen=True)
class Layout:
    """Posizioni e dimensioni (in cm) dei vari pannelli."""

    # Codice sorgente.
    code_x: float = 0.35
    code_y: float = 0.0
    code_width: float = 8.0
    code_line_height: float = 0.3348
    code_top_margin: float = 0.35
    listing_options: tuple[str, ...] = (
        "language=C",
        "basicstyle=\\ttfamily\\scriptsize",
        "numbers=left",
        "numberstyle=\\scriptsize",
        "breakatwhitespace=false",
        "breaklines=false",
        "showstringspaces=false",
        "commentstyle=\\color{purple}\\ttfamily",
    )
    # Stack.
    stack_x: float = 14.0
    stack_y: float = 0.0
    cell_width: float = 1.5
    cell_height: float = 1.0
    rotate_function_names: bool = True
    hide_addresses: bool = False
    # Heap: i blocchi sono disposti su una griglia, in ordine di allocazione.
    # `heap_x` è il bordo sinistro del blocco.
    heap_x: float = 9.0
    heap_y: float = -0.5
    heap_dx: float = 2.0
    heap_dy: float = -1.6
    heap_columns: int = 1
    # Buffer di stdin/stdout. Se `io_y` è None si piazza sotto il codice.
    io_x: float = 0.5
    io_y: float | None = None
    io_cell: float = 0.5
    io_length: int = 30
    io_spacing: float = 2.0
    io_gap: float = 1.0


def out_in_angles(src: Point, dst: Point) -> tuple[int, int]:
    """Angoli di uscita e di ingresso per una freccia da `src` a `dst`."""
    dx, dy = dst.x - src.x, dst.y - src.y
    if dx == 0:
        out = 45 if dy >= 0 else 225
    elif dx > 0:
        out = 45 if dy >= 0 else 315
    else:
        out = 135 if dy >= 0 else 225
    if dx == 0:
        in_ = 315 if dy > 0 else 135
    elif dx > 0 and abs(dx) >= 2 * abs(dy):
        in_ = 180
    elif dx < 0 and abs(dx) >= 2 * abs(dy):
        in_ = 0
    elif dy > 0:
        in_ = 270
    else:
        in_ = 90
    return out, in_


_POINTER_FIELD_INSET = 0.15


@dataclass
class _Pass:
    """Stato di lavoro per la generazione degli elementi di uno snapshot."""

    elements: list[Element] = field(default_factory=list)
    positions: dict[str, Point] = field(default_factory=dict)
    targets: dict[int, str] = field(default_factory=dict)
    # (id della cella sorgente, indirizzo puntato, stringa puntata)
    pointers: list[tuple[str, int, str | None]] = field(default_factory=list)
    used_ids: set[str] = field(default_factory=set)


class Scene:
    """Trasforma snapshot in elementi TikZ.

    Un'unica istanza va usata per tutti gli snapshot di una animazione, perché
    ricorda la posizione assegnata a ogni blocco dell'heap.
    """

    def __init__(self, layout: Layout, show: Show,
                 listing_path: Callable[[str], str] = lambda f: f,
                 code_lines: int = 0) -> None:
        self.layout = layout
        self.show = show
        self.listing_path = listing_path
        self.code_lines = code_lines
        self._heap_slots: dict[int, int] = {}

    # -- API -----------------------------------------------------------

    def elements(self, snap: Snapshot) -> list[Element]:
        p = _Pass()
        if Show.CODE in self.show:
            self._code(snap, p)
        if Show.STDIN in self.show:
            self._io(snap.stdin, "stdin", self._stdin_y(), reading=True, p=p)
        if Show.STDOUT in self.show:
            self._io(snap.stdout, "stdout", self._stdout_y(), reading=False, p=p)
        if Show.STACK in self.show:
            self._stack(snap, p)
        if Show.HEAP in self.show:
            self._heap(snap, p)
        self._pointers(p)
        return p.elements

    # -- codice --------------------------------------------------------

    def _code(self, snap: Snapshot, p: _Pass) -> None:
        L = self.layout
        options = ",".join(L.listing_options)
        content = (f"\\begin{{minipage}}{{{num(L.code_width)}cm}}"
                   f"\\lstinputlisting[{options}]{{{self.listing_path(snap.file)}}}"
                   f"\\end{{minipage}}")
        y = round(L.code_y - L.code_top_margin
                  - (snap.line - 0.5) * L.code_line_height, 3)
        p.elements.append(Node(content, Point(L.code_x, L.code_y), ("below right",)))
        p.elements.append(Node("", Point(L.code_x - 0.15, y),
                               ("draw", "minimum width=0.4cm",
                                "minimum height=0.35cm", "left")))

    def _code_bottom(self) -> float:
        L = self.layout
        if Show.CODE not in self.show:
            return L.code_y
        return L.code_y - L.code_top_margin - self.code_lines * L.code_line_height

    # -- stack ---------------------------------------------------------

    def _stack(self, snap: Snapshot, p: _Pass) -> None:
        L = self.layout
        y = L.stack_y
        for frame in snap.frames:
            top = y
            for var in frame.variables:
                cells = tuple(reversed(var.cells)) if var.aggregate else var.cells
                for cell in cells:
                    if self._stack_cell(cell, y, p):
                        y -= L.cell_height
            if y == top:
                continue
            x = L.stack_x + L.cell_width / 2 + 0.2
            y_start = top + L.cell_height / 2 - 0.1
            y_end = y + L.cell_height / 2 + 0.1
            p.elements.append(Path((Point(x, y_start), Point(x, y_end))))
            p.elements.append(Node(
                f"{tex_escape(frame.function)} ({frame.line})",
                Point(x, (y_start + y_end) / 2),
                ("above", "rotate=-90") if L.rotate_function_names else ("right",)))

    def _stack_cell(self, cell: Cell, y: float, p: _Pass) -> bool:
        L = self.layout
        ident = str(cell.address)
        if ident in p.used_ids:
            return False
        p.used_ids.add(ident)
        pos = Point(L.stack_x, y)
        p.positions[ident] = pos
        p.targets.setdefault(cell.address, ident)
        p.elements.append(Node("", pos, ("draw", f"minimum width={num(L.cell_width)}cm",
                                         f"minimum height = {num(L.cell_height)}cm"), ident))
        p.elements.append(Node(code(cell.name), None, (f"left=0.0cm of {ident}",)))
        if not L.hide_addresses:
            p.elements.append(Node(small(str(cell.address)), f"{ident}.north east",
                                   ("below left",)))
        self._cell_value(cell, ident, f"{ident}.south", p)
        return True

    def _cell_value(self, cell: Cell, ident: str, anchor: str, p: _Pass) -> None:
        """Valore scritto in una cella; per i puntatori, un'annotazione differita."""
        if cell.pointee is None:
            p.elements.append(Node(code(cell.text), anchor, ("above",)))
        elif cell.pointee == 0:
            p.elements.append(Node(code("0"), anchor, ("above",)))
        else:
            p.pointers.append((ident, cell.pointee, cell.summary))

    # -- heap ----------------------------------------------------------

    def _slot(self, address: int) -> Point:
        L = self.layout
        if address not in self._heap_slots:
            self._heap_slots[address] = len(self._heap_slots)
        n = self._heap_slots[address]
        col, row = n % max(L.heap_columns, 1), n // max(L.heap_columns, 1)
        return Point(L.heap_x + col * L.heap_dx, L.heap_y + row * L.heap_dy)

    def _field_width(self, cell: Cell) -> float:
        return self.layout.cell_width / (3 if cell.pointee is not None else 1.5)

    def _heap(self, snap: Snapshot, p: _Pass) -> None:
        L = self.layout
        placed: list[tuple[HeapBlock, Point, list[float]]] = []
        for block in snap.heap:
            ident = str(block.address)
            if ident in p.used_ids:
                continue
            p.used_ids.add(ident)
            slot = self._slot(block.address)
            widths = [self._field_width(f) for f in block.fields] or [L.cell_width]
            total = sum(widths)
            center = Point(slot.x + total / 2, slot.y)
            p.positions[ident] = center
            p.targets.setdefault(block.address, ident)
            p.elements.append(Node("", center, (
                "draw", f"minimum width={num(total)}cm",
                f"minimum height = {num(L.cell_height)}cm"), ident))
            if not L.hide_addresses:
                p.elements.append(Node(small(str(block.address)), f"{ident}.north west",
                                       ("above right",)))
            placed.append((block, slot, widths))

        # Dopo i contenitori, così che gli indirizzi dei blocchi abbiano la precedenza.
        for block, slot, widths in placed:
            x = slot.x
            for i, (cell, width) in enumerate(zip(block.fields, widths)):
                self._heap_field(block, i, cell, Point(x + width / 2, slot.y), width, p)
                x += width

    def _heap_field(self, block: HeapBlock, index: int, cell: Cell, pos: Point,
                    width: float, p: _Pass) -> None:
        L = self.layout
        ident = f"{block.address}_{index}"
        p.used_ids.add(ident)
        p.positions[ident] = pos
        p.targets.setdefault(cell.address, ident)
        if cell.pointee is None:
            p.elements.append(Node(code(cell.text), pos, (
                "draw", f"minimum width={num(width)}cm",
                f"minimum height = {num(L.cell_height)}cm"), ident))
            return
        w = width - _POINTER_FIELD_INSET
        h = L.cell_height - 2 * _POINTER_FIELD_INSET
        box = (f"minimum width={num(w)}cm", f"minimum height = {num(h)}cm")
        p.elements.append(Node("", pos, ("draw",) + box, ident))
        if cell.pointee == 0:
            p.elements.append(Node(code("0"), pos, box))
        else:
            p.pointers.append((ident, cell.pointee, cell.summary))

    # -- frecce --------------------------------------------------------

    def _pointers(self, p: _Pass) -> None:
        for source, address, summary in p.pointers:
            target = p.targets.get(address)
            if target is not None:
                p.elements.append(Path(
                    (f"{source}.center", target), ("*->",),
                    out_in_angles(p.positions[source], p.positions[target])))
            elif summary:
                p.elements.append(Node(small(summary), f"{source}.south", ("above",)))

    # -- I/O -----------------------------------------------------------

    def _stdin_y(self) -> float:
        L = self.layout
        return L.io_y if L.io_y is not None else self._code_bottom() - L.io_gap

    def _stdout_y(self) -> float:
        return self._stdin_y() - self.layout.io_spacing

    @staticmethod
    def _char(b: int) -> str:
        special = {10: "n", 9: "t", 13: "r", 0: "0"}
        if b in special:
            return "\\textbackslash{}" + special[b]
        if b == 32:
            return "\\textvisiblespace{}"
        if 33 <= b < 127:
            return tex_escape(chr(b))
        return "?"

    def _io(self, buf: IOBuffer | None, name: str, y: float, reading: bool,
            p: _Pass) -> None:
        L = self.layout
        w = L.io_cell
        data = buf.data if buf is not None else b""
        # I riquadri ci sono sempre; i caratteri solo quando il buffer li contiene.
        for i in range(L.io_length):
            at = Point(L.io_x + i * w, y)
            p.elements.append(Node("", at, ("draw", f"minimum width={num(w)}cm",
                                            f"minimum height={num(w)}cm", "inner sep=0pt")))
            if i < len(data):
                p.elements.append(Node(f"\\texttt{{\\tiny{{{self._char(data[i])}}}}}", at,
                                       ("inner sep=0pt",)))
        if buf is not None and buf.pointer < L.io_length:
            glyph, dy = ("$\\uparrow$", -w) if reading else ("$\\downarrow$", w)
            p.elements.append(Node(glyph, Point(L.io_x + w * buf.pointer, y + dy)))
        p.elements.append(Node(name, Point(L.io_x + w * (L.io_length - 1) / 2,
                                           y + (w if reading else -w))))
