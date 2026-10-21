all: lista-tikz.tex

lista-tikz.tex: lista.py lista.c lista.in
	pipenv run python lista.py

lista.pdf: lista.tex lista-tikz.tex
	latexmk -pdf lista

clean:
	rm -f lista-tikz.tex
	latexmk -C lista 2>/dev/null || true

.PHONY: all clean
