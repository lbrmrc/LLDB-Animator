"""Dalla sequenza di snapshot al file TikZ con i comandi `\\uncover`."""

from __future__ import annotations

from typing import Sequence

from .tikz import Element, mark_changed, render


def intervals(numbers: Sequence[int]) -> list[tuple[int, int]]:
    """Raggruppa numeri in intervalli consecutivi: [1,2,3,5] -> [(1,3),(5,5)]."""
    result: list[tuple[int, int]] = []
    for n in sorted(set(numbers)):
        if result and result[-1][1] == n - 1:
            result[-1] = (result[-1][0], n)
        else:
            result.append((n, n))
    return result


def render_uncover(numbers: Sequence[int]) -> str:
    parts = [str(a) if a == b else f"{a}-{b}" for a, b in intervals(numbers)]
    return "\\uncover<" + ",".join(parts) + ">"


def build_tikz(snapshots: Sequence[Sequence[Element]]) -> str:
    """Genera il TikZ per una sequenza di snapshot (elementi per snapshot).

    Ogni elemento compare una sola volta, con `\\uncover` sugli snapshot in cui
    è presente. Un elemento che non era presente nello snapshot precedente
    riceve lo stile `changed`.
    """
    groups: dict[Element, list[int]] = {}
    previous: frozenset[Element] = frozenset()
    for number, elements in enumerate(snapshots, start=1):
        for element in elements:
            if number > 1 and element not in previous:
                element = mark_changed(element)
            numbers = groups.setdefault(element, [])
            if not numbers or numbers[-1] != number:
                numbers.append(number)
        previous = frozenset(elements)
    return "".join(f"{render_uncover(numbers)}{{{render(element)};}}\n"
                   for element, numbers in groups.items())
