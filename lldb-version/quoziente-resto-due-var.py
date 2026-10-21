from lldb_animator import Layout, Show, animate

animate("quoziente-resto-due-var.c",
        breakpoints=[5, 6, 7, 8],
        show=Show.CODE | Show.STACK | Show.STDIN | Show.STDOUT,
        stdin_file="quoziente-resto-due-var.in",
        output="quoziente-resto-due-var-tikz.tex",
        cflags=["-g", "-m32", "-O0", "-std=gnu89", "-Wno-implicit-int"],
        layout=Layout(io_y=-4.5))
