include ../preamble.mk

name = 040_variabili

all: slides script

script: $(name)-script.tex $(name)-content.tex
	touch $(name)-script.tex; latexmk -pdf -synctex=1 $(name)-script

slides: $(name).tex $(name)-content.tex quoziente-resto-variabile.pdf quoziente-resto-input.pdf quoziente-resto-due-var.pdf
	touch $(name).tex; latexmk -pdf -synctex=1 $(name)

quoziente-resto-variabile.pdf: quoziente-resto-variabile.tex
	latexmk -pdf quoziente-resto-variabile

quoziente-resto-variabile.tex: quoziente-resto-variabile quoziente-resto-variabile.py ../animator/animator.py
	../build-animation.sh quoziente-resto-variabile "Quoziente e resto con variabile"

quoziente-resto-variabile: $(PREFIX)/quoziente-resto-variabile.c
	$(CC) -o quoziente-resto-variabile $(PREFIX)/quoziente-resto-variabile.c

quoziente-resto-input.pdf: quoziente-resto-input.tex
	latexmk -pdf quoziente-resto-input

quoziente-resto-input.tex: quoziente-resto-input quoziente-resto-input.py quoziente-resto-input.in ../animator/animator.py
	../build-animation.sh quoziente-resto-input "Quoziente e resto con input"

quoziente-resto-input: $(PREFIX)/quoziente-resto-input.c
	$(CC) -o quoziente-resto-input $(PREFIX)/quoziente-resto-input.c

quoziente-resto-due-var.pdf: quoziente-resto-due-var.tex
	latexmk -pdf quoziente-resto-due-var

quoziente-resto-due-var.tex: quoziente-resto-due-var quoziente-resto-due-var.py quoziente-resto-due-var.in ../animator/animator.py
	../build-animation.sh quoziente-resto-due-var "Quoziente e resto, due variabili"

quoziente-resto-due-var: $(PREFIX)/quoziente-resto-due-var.c
	$(CC) -o quoziente-resto-due-var $(PREFIX)/quoziente-resto-due-var.c
