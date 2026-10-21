"""Modello dei dati raccolti durante l'esecuzione.

Queste strutture non dipendono né da LLDB né da TikZ: il collector le produce,
il layout le consuma.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Cell:
    """Una cella di memoria scalare (intero, carattere, puntatore...)."""

    name: str
    address: int
    text: str = ""
    # Solo per i puntatori: indirizzo puntato (0 = NULL).
    pointee: int | None = None
    # Solo per i puntatori a char: la stringa puntata, già con le virgolette.
    summary: str | None = None


@dataclass(frozen=True)
class Variable:
    """Una variabile di un frame.

    Per array e struct `cells` contiene le celle foglia in ordine di indirizzo
    crescente e `aggregate` è True.
    """

    name: str
    cells: tuple[Cell, ...]
    aggregate: bool = False


@dataclass(frozen=True)
class FrameData:
    function: str
    line: int
    variables: tuple[Variable, ...]


@dataclass(frozen=True)
class HeapBlock:
    """Un blocco allocato con malloc/calloc/realloc e non ancora liberato.

    `fields` è vuoto se non è stato possibile dedurre il tipo del contenuto.
    """

    address: int
    size: int
    fields: tuple[Cell, ...] = ()


@dataclass(frozen=True)
class IOBuffer:
    """Contenuto del buffer di stdin/stdout della libc.

    `pointer` è l'offset in `data` del puntatore di lettura (stdin) o di
    scrittura (stdout).
    """

    data: bytes
    pointer: int


@dataclass(frozen=True)
class Snapshot:
    """Stato del programma a un breakpoint.

    `frames` è ordinato dal più esterno (main) al più interno.
    """

    index: int
    file: str
    line: int
    function: str
    frames: tuple[FrameData, ...] = ()
    heap: tuple[HeapBlock, ...] = ()
    stdin: IOBuffer | None = None
    stdout: IOBuffer | None = None
