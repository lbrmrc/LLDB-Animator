import sys
import gdb
sys.path.append('../animator')
import animator


an = animator.Animator("quoziente-resto-due-var",
                       "quoziente-resto-due-var.in",
                       ["5",
                        "6",
                        "7",
                        "8"],
                       [animator.IORenderer(0.5, 0.5, 0.5, -4.5, True, False, 30, "stdin"),
                        animator.IORenderer(
                            0.5, 0.5, 0.5, -6, False, True, 30, "stdout"),
                        animator.SourceRenderer(),
                        animator.MemoryRenderer(14.0, 0.0, 1.0)])
an.movie("quoziente-resto-due-var-tikz.tex")
