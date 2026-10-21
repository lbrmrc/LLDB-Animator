all: quoziente-resto-due-var-tikz.tex

quoziente-resto-due-var-tikz.tex: quoziente-resto-due-var.py quoziente-resto-due-var.c quoziente-resto-due-var.in
	pipenv run python quoziente-resto-due-var.py

quoziente-resto-due-var.pdf: quoziente-resto-due-var.tex quoziente-resto-due-var-tikz.tex
	latexmk -pdf quoziente-resto-due-var

clean:
	rm -f quoziente-resto-due-var-tikz.tex
	latexmk -C quoziente-resto-due-var 2>/dev/null || true

.PHONY: all clean
