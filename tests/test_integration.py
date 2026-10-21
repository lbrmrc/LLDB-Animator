"""Test di integrazione: richiedono LLDB e un compilatore C."""

import shutil

import pytest

pytest.importorskip("lldb_animator.collector", reason="modulo lldb non disponibile")

from lldb_animator import animate  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("cc") is None, reason="compilatore C assente")

SOURCE = """\
#include <stdio.h>
#include <stdlib.h>
struct nodo { int dato; struct nodo *next; };
int main() {
  int a;
  scanf("%d", &a);
  struct nodo *p = malloc(sizeof(struct nodo));
  p->dato = a;
  p->next = NULL;
  printf("%d\\n", p->dato);
  free(p);
  return 0;
}
"""


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "prog.c"
    path.write_text(SOURCE)
    return path


def test_stack_heap_and_io(source, tmp_path):
    out = tmp_path / "out.tex"
    result = animate(source, [9, 11, "main"], "all", stdin_text="42\n", output=out)
    assert not result.warnings
    assert result.exit_code == 0
    assert result.stdout == "42\n"
    assert out.read_text() == result.tikz
    assert len(result) == 3

    by_line = {s.line: s for s in result.snapshots}
    at_9, at_11 = by_line[9], by_line[11]
    by_name = {v.name: v for v in at_9.frames[0].variables}
    assert by_name["a"].cells[0].text == "42"
    block = at_9.heap[0]
    assert [f.name for f in block.fields] == ["dato", "next"]
    assert block.fields[0].text == "42" and block.fields[1].pointee == 0
    assert at_9.stdout is None  # il buffer di stdout non esiste ancora
    assert at_11.stdout.data == b"42\n"
    assert len(at_11.heap) == 1  # il breakpoint scatta prima di free(p)
    assert "\\uncover" in result.tikz


def test_unreachable_breakpoint_is_reported(source):
    result = animate(source, [9, 999], "stack", stdin_text="1\n")
    assert len(result) == 1
    assert any("999" in w for w in result.warnings)


def test_compilation_error(tmp_path):
    from lldb_animator import CompilationError
    bad = tmp_path / "bad.c"
    bad.write_text("int main( { }")
    with pytest.raises(CompilationError):
        animate(bad, [1], "stack")
