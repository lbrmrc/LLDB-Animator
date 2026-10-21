"""Test delle parti che non richiedono LLDB."""

import pytest

from lldb_animator.collector import BreakpointSpec, parse_breakpoint
from lldb_animator.layout import Layout, Scene, Show, out_in_angles
from lldb_animator.model import Cell, FrameData, HeapBlock, IOBuffer, Snapshot, Variable
from lldb_animator.tikz import Node, Path, Point, render, tex_escape
from lldb_animator.timeline import build_tikz, intervals, render_uncover


def test_intervals():
    assert intervals([1, 2, 3, 5, 7, 8]) == [(1, 3), (5, 5), (7, 8)]
    assert render_uncover([1, 2, 3, 5]) == "\\uncover<1-3,5>"
    assert intervals([]) == []


def test_render_node_and_path():
    assert render(Node("x", Point(1.0, -0.5), ("above",), "a")) == \
        "\\node [above] at (1,-0.5) (a) {x}"
    assert render(Path(("a.center", "b"), ("*->",), (45, 180))) == \
        "\\draw [*->] (a.center) to[out=45,in=180] (b)"


def test_tex_escape():
    assert tex_escape("a_b%") == "a\\_b\\%"


def test_timeline_marks_changed_and_groups():
    a, b, c = Node("a", Point(0, 0)), Node("b", Point(1, 0)), Node("c", Point(2, 0))
    out = build_tikz([[a, b], [a, c], [a, c]]).splitlines()
    assert out[0].startswith("\\uncover<1-3>{\\node [] at (0,0)  {a}")
    assert any(l.startswith("\\uncover<1>") and "{b}" in l and "changed" not in l for l in out)
    assert any(l.startswith("\\uncover<2>") and "{c}" in l and "changed" in l for l in out)
    assert any(l.startswith("\\uncover<3>") and "{c}" in l and "changed" not in l for l in out)


@pytest.mark.parametrize("spec,expected", [
    (12, BreakpointSpec(file="a.c", line=12)),
    ("12", BreakpointSpec(file="a.c", line=12)),
    ("src/b.c:7", BreakpointSpec(file="b.c", line=7)),
    (("src/b.c", 7), BreakpointSpec(file="b.c", line=7)),
    ("main", BreakpointSpec(function="main")),
])
def test_parse_breakpoint(spec, expected):
    assert parse_breakpoint(spec, "a.c") == expected


def test_parse_breakpoint_invalid():
    with pytest.raises(ValueError):
        parse_breakpoint("12 + 3", "a.c")


def test_show_parse():
    assert Show.parse("code, stack") == Show.CODE | Show.STACK
    assert Show.parse(["heap", Show.STDIN]) == Show.HEAP | Show.STDIN
    assert Show.parse("io") == Show.STDIN | Show.STDOUT
    with pytest.raises(ValueError, match="sconosciuto"):
        Show.parse("stak")


def test_out_in_angles():
    assert out_in_angles(Point(0, 0), Point(10, 0)) == (45, 180)
    assert out_in_angles(Point(0, 0), Point(0, -1)) == (225, 135)


def _snapshot(value: str, line: int = 5) -> Snapshot:
    frame = FrameData("main", line, (
        Variable("x", (Cell("x", 100, value),)),
        Variable("p", (Cell("p", 104, pointee=200),)),
    ))
    heap = (HeapBlock(200, 8, (Cell("dato", 200, "1"), Cell("next", 204, pointee=0))),)
    return Snapshot(1, "a.c", line, "main", (frame,), heap)


def test_scene_stack_and_heap():
    scene = Scene(Layout(), Show.STACK | Show.HEAP)
    text = [render(e) for e in scene.elements(_snapshot("3"))]
    assert any("(100)" in t for t in text)               # cella dello stack
    assert any("\\draw [*->] (104.center) to" in t and t.endswith("(200)") for t in text)
    assert any("(200_0)" in t for t in text)             # campo del blocco heap
    assert any("{\\texttt{0}}" in t for t in text)       # next == NULL


def test_scene_heap_positions_are_stable():
    scene = Scene(Layout(), Show.HEAP)
    first = [render(e) for e in scene.elements(_snapshot("1"))]
    second = [render(e) for e in scene.elements(_snapshot("2"))]
    assert first == second


def test_scene_code_marker_follows_line():
    scene = Scene(Layout(), Show.CODE, code_lines=10)
    marker = lambda line: render(scene.elements(_snapshot("1", line))[1])  # noqa: E731
    assert marker(5) != marker(6)


def test_scene_io_without_buffer_keeps_boxes():
    scene = Scene(Layout(io_y=-4.5, io_length=3), Show.STDIN)
    assert len(scene.elements(_snapshot("1"))) == 3 + 1  # riquadri + etichetta
    with_data = Snapshot(1, "a.c", 1, "main", stdin=IOBuffer(b"2\n", 1))
    assert len(scene.elements(with_data)) == 3 + 2 + 1 + 1  # + caratteri + freccia
