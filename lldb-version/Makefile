CC = gcc
CFLAGS = -g -m32 -O0 -std=gnu89 -Wno-implicit-int

all: quoziente-resto-due-var-tikz.tex

quoziente-resto-due-var-tikz.tex: quoziente-resto-due-var quoziente-resto-due-var.py quoziente-resto-due-var.in animator.py
	python3 quoziente-resto-due-var.py

quoziente-resto-due-var: quoziente-resto-due-var.c
	$(CC) $(CFLAGS) -o $@ $<

quoziente-resto-due-var.pdf: quoziente-resto-due-var.tex quoziente-resto-due-var-tikz.tex
	latexmk -pdf quoziente-resto-due-var

clean:
	rm -f quoziente-resto-due-var quoziente-resto-due-var-tikz.tex stdout.txt
	latexmk -C quoziente-resto-due-var 2>/dev/null || true

.PHONY: all clean
