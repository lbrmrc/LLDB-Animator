from lldb_animator import Layout, Show, animate

animate("lista.c",
        breakpoints=[19, 21, 24, 25, 26, "somma", 27, 29, 30],
        show=Show.CODE | Show.STACK | Show.HEAP,
        stdin_file="lista.in",
        output="lista-tikz.tex",
        cflags=["-g", "-m32", "-O0"],
        layout=Layout(heap_x=9.0, heap_y=-0.5))
