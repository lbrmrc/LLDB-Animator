"""Esecuzione del programma sotto LLDB e raccolta degli snapshot."""

from __future__ import annotations

import os
import struct
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Sequence

from ._lldb import import_lldb
from .model import (Cell, FrameData, HeapBlock, IOBuffer, Snapshot, Variable)

lldb = import_lldb()

# Segnali che indicano un errore del programma (SIGILL, SIGABRT, SIGBUS, SIGFPE, SIGSEGV).
_FATAL_SIGNALS = {4, 6, 7, 8, 11}

_ALLOCATORS = ("malloc", "calloc", "realloc")
_HEAP_FUNCTIONS = _ALLOCATORS + ("free",)

# Offset (in unità di puntatore) dei campi di `struct _IO_FILE` della glibc,
# dopo il campo `_flags`.
_IO_READ_PTR, _IO_READ_END, _IO_WRITE_BASE, _IO_WRITE_PTR, _IO_BUF_BASE = 0, 1, 3, 4, 6
_IO_FIELDS = 8


class TraceError(RuntimeError):
    pass


@dataclass(frozen=True)
class BreakpointSpec:
    """Un breakpoint su una riga di un file oppure su una funzione."""

    file: str | None = None
    line: int | None = None
    function: str | None = None

    def __str__(self) -> str:
        return self.function if self.function else f"{self.file}:{self.line}"


def parse_breakpoint(spec: "int | str | tuple[str, int] | BreakpointSpec",
                     default_file: str) -> BreakpointSpec:
    """Interpreta un breakpoint.

    Forme accettate: `12` o `"12"` (riga nel file di default), `"file.c:12"`,
    `("file.c", 12)`, `"funzione"`.
    """
    if isinstance(spec, BreakpointSpec):
        return spec
    if isinstance(spec, tuple):
        file, line = spec
        return BreakpointSpec(file=os.path.basename(file), line=int(line))
    if isinstance(spec, int):
        return BreakpointSpec(file=default_file, line=spec)
    text = spec.strip()
    if text.isdigit():
        return BreakpointSpec(file=default_file, line=int(text))
    file, sep, line = text.rpartition(":")
    if sep and line.isdigit():
        return BreakpointSpec(file=os.path.basename(file), line=int(line))
    if text.isidentifier():
        return BreakpointSpec(function=text)
    raise ValueError(f"breakpoint non valido: {spec!r}")


@dataclass
class Trace:
    snapshots: list[Snapshot] = field(default_factory=list)
    exit_code: int | None = None
    stdout: str = ""
    warnings: list[str] = field(default_factory=list)


class _Abi:
    """Convenzioni di chiamata necessarie per intercettare malloc e free."""

    def __init__(self, triple: str) -> None:
        arch = triple.split("-")[0]
        if arch in ("i386", "i486", "i586", "i686"):
            self.kind = "x86"
        elif arch in ("x86_64", "amd64"):
            self.kind = "x86_64"
        elif arch in ("aarch64", "arm64"):
            self.kind = "aarch64"
        else:
            raise TraceError(f"architettura non supportata per tracciare l'heap: {arch}")

    def arg(self, frame, index: int, pointer_size: int, process) -> int:
        """Argomento intero numero `index`, a una breakpoint sull'ingresso della funzione."""
        if self.kind == "x86_64":
            return frame.FindRegister(("rdi", "rsi", "rdx")[index]).GetValueAsUnsigned()
        if self.kind == "aarch64":
            return frame.FindRegister(f"x{index}").GetValueAsUnsigned()
        # x86 a 32 bit: argomenti sullo stack, sopra l'indirizzo di ritorno.
        sp = frame.FindRegister("esp").GetValueAsUnsigned()
        err = lldb.SBError()
        return process.ReadUnsignedFromMemory(sp + 4 * (index + 1), pointer_size, err)

    def result(self, frame) -> int:
        reg = {"x86": "eax", "x86_64": "rax", "aarch64": "x0"}[self.kind]
        return frame.FindRegister(reg).GetValueAsUnsigned()


class Tracer:
    """Esegue `executable` sotto LLDB e raccoglie uno snapshot a ogni breakpoint."""

    def __init__(self, executable: str, sources: Sequence[str],
                 breakpoints: Sequence[BreakpointSpec], *,
                 track_heap: bool = False, track_stdin: bool = False,
                 track_stdout: bool = False, args: Sequence[str] = (),
                 stdin_file: str | None = None, timeout: float | None = 30.0,
                 max_elements: int = 64, io_window: int = 64) -> None:
        self.executable = executable
        self.source_names = {os.path.basename(s) for s in sources}
        self.breakpoints = list(breakpoints)
        self.track_heap = track_heap
        self.track_stdin = track_stdin
        self.track_stdout = track_stdout
        self.args = list(args)
        self.stdin_file = stdin_file
        self.timeout = timeout
        self.max_elements = max_elements
        self.io_window = io_window

        self._trace = Trace()
        self._heap: dict[int, int] = {}
        self._pointer_types: dict[int, list] = {}
        self._io_addresses: dict[str, int | None] = {}
        self._timed_out = False

    # -- esecuzione ----------------------------------------------------

    def run(self) -> Trace:
        debugger = lldb.SBDebugger.Create(False)
        debugger.SetAsync(False)
        out_fd, out_path = tempfile.mkstemp(prefix="lldb-animator-", suffix=".out")
        os.close(out_fd)
        try:
            self._run(debugger, out_path)
            with open(out_path, errors="replace") as f:
                self._trace.stdout = f.read()
        finally:
            os.remove(out_path)
            lldb.SBDebugger.Destroy(debugger)
        return self._trace

    def _run(self, debugger, out_path: str) -> None:
        target = debugger.CreateTarget(self.executable)
        if not target.IsValid():
            raise TraceError(f"impossibile aprire l'eseguibile {self.executable!r}")
        self._target = target

        user_ids: set[int] = set()
        for spec in self.breakpoints:
            if spec.function:
                bp = target.BreakpointCreateByName(spec.function)
            else:
                bp = target.BreakpointCreateByLocation(spec.file, spec.line)
            if not bp.IsValid() or bp.GetNumLocations() == 0:
                self._trace.warnings.append(
                    f"il breakpoint {spec} non corrisponde a nessun codice eseguibile")
                continue
            user_ids.add(bp.GetID())

        heap_ids: dict[int, str] = {}
        if self.track_heap:
            self._abi = _Abi(target.GetTriple())
            for name in _HEAP_FUNCTIONS:
                heap_ids[target.BreakpointCreateByName(name).GetID()] = name

        info = lldb.SBLaunchInfo(self.args or None)
        info.SetLaunchFlags(info.GetLaunchFlags() | lldb.eLaunchFlagDisableASLR)
        # Senza un input esplicito si legge EOF, invece di bloccarsi sul terminale.
        info.AddOpenFileAction(0, self.stdin_file or os.devnull, True, False)
        info.AddOpenFileAction(1, out_path, False, True)
        info.SetWorkingDirectory(os.getcwd())

        error = lldb.SBError()
        process = target.Launch(info, error)
        if not process.IsValid() or error.Fail():
            raise TraceError(f"impossibile avviare il programma: {error.GetCString()}")
        self._process = process

        timer = None
        if self.timeout:
            timer = threading.Timer(self.timeout, self._on_timeout)
            timer.daemon = True
            timer.start()
        try:
            self._loop(process, user_ids, heap_ids)
        finally:
            if timer:
                timer.cancel()
            if process.IsValid() and process.GetState() not in (
                    lldb.eStateExited, lldb.eStateDetached):
                process.Kill()
        if process.GetState() == lldb.eStateExited:
            self._trace.exit_code = process.GetExitStatus()

    def _on_timeout(self) -> None:
        self._timed_out = True
        self._process.SendAsyncInterrupt()

    def _loop(self, process, user_ids: set[int], heap_ids: dict[int, str]) -> None:
        while process.GetState() == lldb.eStateStopped:
            if self._timed_out:
                self._trace.warnings.append(
                    f"il programma non è terminato entro {self.timeout} secondi")
                return
            thread = process.GetSelectedThread()
            reason = thread.GetStopReason()
            if reason == lldb.eStopReasonBreakpoint:
                # I dati sono coppie (id breakpoint, id location).
                ids = [thread.GetStopReasonDataAtIndex(i)
                       for i in range(0, thread.GetStopReasonDataCount(), 2)]
                for bp_id in ids:
                    if bp_id in heap_ids:
                        self._on_heap_call(thread, heap_ids[bp_id])
                if any(bp_id in user_ids for bp_id in ids):
                    self._take_snapshot(thread)
            elif reason in (lldb.eStopReasonSignal, lldb.eStopReasonException):
                signo = thread.GetStopReasonDataAtIndex(0)
                if reason == lldb.eStopReasonException or signo in _FATAL_SIGNALS:
                    self._trace.warnings.append(
                        "il programma si è fermato: " + thread.GetStopDescription(256))
                    self._take_snapshot(thread)
                    return
            process.Continue()

    # -- heap ----------------------------------------------------------

    def _is_user_frame(self, frame) -> bool:
        entry = frame.GetLineEntry()
        return entry.IsValid() and os.path.basename(
            entry.GetFileSpec().GetFilename() or "") in self.source_names

    def _on_heap_call(self, thread, name: str) -> None:
        # Si ignorano le chiamate interne alla libc (es. buffer di stdio).
        if not self._is_user_frame(thread.GetFrameAtIndex(1)):
            return
        process = self._process
        size = self._target.GetAddressByteSize()
        frame = thread.GetFrameAtIndex(0)
        arg = lambda i: self._abi.arg(frame, i, size, process)  # noqa: E731
        if name == "free":
            self._heap.pop(arg(0), None)
            return
        old = arg(0) if name == "realloc" else 0
        requested = {"malloc": lambda: arg(0),
                     "calloc": lambda: arg(0) * arg(1),
                     "realloc": lambda: arg(1)}[name]()
        error = lldb.SBError()
        thread.StepOutOfFrame(frame, error)
        if error.Fail():
            return
        address = self._abi.result(thread.GetFrameAtIndex(0))
        if name == "realloc" and address:
            self._heap.pop(old, None)
        if address:
            self._heap[address] = requested

    # -- snapshot ------------------------------------------------------

    def _take_snapshot(self, thread) -> None:
        self._pointer_types.clear()
        frame = thread.GetFrameAtIndex(0)
        entry = frame.GetLineEntry()
        user_frames = []
        for i in range(thread.GetNumFrames()):
            f = thread.GetFrameAtIndex(i)
            if f.GetFunction().IsValid() and self._is_user_frame(f):
                user_frames.append(f)
        frames = tuple(self._frame(f) for f in reversed(user_frames))
        heap = self._heap_blocks() if self.track_heap else ()
        self._trace.snapshots.append(Snapshot(
            index=len(self._trace.snapshots) + 1,
            file=entry.GetFileSpec().fullpath or "",
            line=entry.GetLine(),
            function=frame.GetFunctionName() or "",
            frames=frames,
            heap=heap,
            stdin=self._io("stdin") if self.track_stdin else None,
            stdout=self._io("stdout") if self.track_stdout else None,
        ))

    def _frame(self, frame) -> FrameData:
        values = []
        for args, local in ((True, False), (False, True)):
            lst = frame.GetVariables(args, local, False, True)
            values.extend(lst.GetValueAtIndex(i) for i in range(lst.GetSize()))
        variables = []
        for value in values:
            cells: list[Cell] = []
            aggregate = self._leaves(value, value.GetName() or "", cells)
            if cells:
                variables.append(Variable(value.GetName() or "", tuple(cells), aggregate))
        line = frame.GetLineEntry().GetLine()
        return FrameData(frame.GetFunctionName() or "", line, tuple(variables))

    def _leaves(self, value, name: str, out: list[Cell]) -> bool:
        """Appiattisce `value` in celle scalari. Restituisce True se è un aggregato."""
        cls = value.GetType().GetCanonicalType().GetTypeClass()
        if cls == lldb.eTypeClassArray:
            for i in range(min(value.GetNumChildren(), self.max_elements)):
                self._leaves(value.GetChildAtIndex(i), f"{name}[{i}]", out)
            return True
        if cls in (lldb.eTypeClassStruct, lldb.eTypeClassUnion, lldb.eTypeClassClass):
            for i in range(value.GetNumChildren()):
                child = value.GetChildAtIndex(i)
                child_name = child.GetName() or ""
                self._leaves(child, f"{name}.{child_name}" if name else child_name, out)
            return True
        cell = self._cell(value, name)
        if cell is not None:
            out.append(cell)
        return False

    def _cell(self, value, name: str) -> Cell | None:
        address = value.GetLoadAddress()
        if address in (0, lldb.LLDB_INVALID_ADDRESS):
            return None  # variabile in registro o ottimizzata
        vtype = value.GetType().GetCanonicalType()
        if vtype.GetTypeClass() == lldb.eTypeClassPointer:
            pointee = value.GetValueAsUnsigned()
            if pointee in self._heap:
                self._pointer_types.setdefault(pointee, []).append(vtype.GetPointeeType())
            return Cell(name, address, pointee=pointee, summary=value.GetSummary())
        return Cell(name, address, text=value.GetValue() or "?")

    def _heap_blocks(self) -> tuple[HeapBlock, ...]:
        """Blocchi vivi, con il contenuto decodificato quando il tipo è deducibile.

        Il tipo di un blocco si deduce dai puntatori (variabili o campi di altri
        blocchi) che lo puntano: se il tipo puntato ha dimensione compatibile
        con quella allocata, il blocco è un'istanza (o un array) di quel tipo.
        """
        typed: dict[int, HeapBlock] = {}
        progress = True
        while progress:
            progress = False
            for address, size in self._heap.items():
                if address in typed:
                    continue
                block = self._decode_block(address, size)
                if block is not None:
                    typed[address] = block
                    progress = True
        return tuple(typed.get(a) or HeapBlock(a, s) for a, s in self._heap.items())

    def _decode_block(self, address: int, size: int) -> HeapBlock | None:
        for ptype in self._pointer_types.get(address, ()):
            item_size = ptype.GetByteSize()
            if not 0 < item_size <= size:
                continue
            count = size // item_size
            vtype = ptype if count == 1 else ptype.GetArrayType(count)
            value = self._target.CreateValueFromAddress(
                "block", lldb.SBAddress(address, self._target), vtype)
            if not value.IsValid():
                continue
            cells: list[Cell] = []
            self._leaves(value, "", cells)
            if cells:
                return HeapBlock(address, size, tuple(cells))
        return None

    # -- I/O -----------------------------------------------------------

    def _io(self, stream: str) -> IOBuffer | None:
        """Buffer di stdin/stdout della glibc, letto dalla memoria del processo.

        Si leggono direttamente i campi di `_IO_2_1_std*_` perché la libc non ha
        informazioni di debug.
        """
        if stream not in self._io_addresses:
            symbols = self._target.FindSymbols(f"_IO_2_1_{stream}_")
            self._io_addresses[stream] = (
                symbols.GetContextAtIndex(0).GetSymbol().GetStartAddress()
                .GetLoadAddress(self._target) if symbols.GetSize() else None)
        base = self._io_addresses[stream]
        if base is None or base == lldb.LLDB_INVALID_ADDRESS:
            return None
        size = self._target.GetAddressByteSize()
        error = lldb.SBError()
        raw = self._process.ReadMemory(base + size, size * _IO_FIELDS, error)
        if error.Fail() or raw is None:
            return None
        fmt = "<" + ("I" if size == 4 else "Q") * _IO_FIELDS
        fields = struct.unpack(fmt, raw)
        buf_base = fields[_IO_BUF_BASE]
        if buf_base == 0:
            return None
        if stream == "stdin":
            start, end, pointer = buf_base, fields[_IO_READ_END], fields[_IO_READ_PTR]
        else:
            start, end = fields[_IO_WRITE_BASE], fields[_IO_WRITE_PTR]
            pointer = end
        length = min(end - start, self.io_window)
        if length <= 0:
            return None
        data = self._process.ReadMemory(start, length, error)
        if error.Fail() or data is None:
            return None
        return IOBuffer(bytes(data), max(pointer - start, 0))
