# lldb-animator

Genera animazioni TikZ per Beamer che mostrano l'esecuzione di un programma C:
codice sorgente con la riga corrente, stack, heap e buffer di `stdin`/`stdout`.

Il programma viene eseguito sotto LLDB e a ogni breakpoint si scatta una
"fotografia" della memoria. Il risultato è un file `.tex` da includere in una
`tikzpicture`, in cui ogni elemento compare nelle sole slide (`\uncover`) in cui
è presente.

È il porting a LLDB di un progetto analogo basato su GDB (vedi `gdb-version/`).

## Installazione

Servono Python 3.10 o superiore, un compilatore C (`cc`) e LLDB con i binding
Python. Per compilare i listati serve LaTeX con Beamer, TikZ e `listings`.

```sh
pipenv install --dev      # installa lldb-animator (editable) e pytest
```

Il modulo Python `lldb` non è su PyPI: viene installato insieme al debugger
(es. `pacman -S lldb`, `apt install lldb python3-lldb`). Deve essere compilato per
la stessa versione di Python del virtualenv.

Non serve fare nulla nel virtualenv: se `import lldb` fallisce, il pacchetto
chiede a `lldb -P` dove si trova il modulo e lo aggiunge a `sys.path`. Se non lo
trova, l'errore dice quale delle due cose manca (debugger o versione di Python
compatibile).

## Uso da Python

```python
from lldb_animator import Layout, Show, animate

animate("prog.c",
        breakpoints=[26, "prog.c:31", "somma"],
        show=Show.CODE | Show.STACK | Show.HEAP | Show.STDIN | Show.STDOUT,
        stdin_file="prog.in",
        output="prog-tikz.tex")
```

`animate()` compila i sorgenti, esegue il programma, raccoglie gli snapshot,
genera il TikZ e lo scrive in `output`. Restituisce un oggetto `Animation` con:

| Attributo   | Contenuto                                              |
| ----------- | ------------------------------------------------------ |
| `tikz`      | il testo TikZ generato                                 |
| `snapshots` | gli snapshot raccolti (`lldb_animator.model.Snapshot`) |
| `stdout`    | tutto l'output del programma                           |
| `exit_code` | codice di uscita (`None` se non è terminato)           |
| `warnings`  | avvisi (breakpoint senza codice, crash, timeout...)    |
| `output`    | percorso del file scritto                              |

### Parametri

| Parametro     | Descrizione                                                               |
| ------------- | ------------------------------------------------------------------------- |
| `sources`     | un file C o un elenco; il primo è quello a cui si riferiscono le sole righe |
| `breakpoints` | dove scattare uno snapshot (vedi sotto)                                   |
| `show`        | cosa visualizzare (vedi sotto); default `CODE \| STACK \| HEAP`           |
| `output`      | file `.tex` da scrivere; se omesso il TikZ è solo nel valore restituito   |
| `stdin_file`  | file da cui il programma legge lo standard input                          |
| `stdin_text`  | alternativa a `stdin_file`: il testo dello standard input                 |
| `args`        | argomenti da riga di comando del programma                                |
| `executable`  | eseguibile già compilato con `-g`; se omesso si compila                   |
| `compiler`, `cflags` | compilatore (default `cc`) e opzioni (default `-g -O0`)            |
| `layout`      | posizioni e dimensioni dei pannelli (`Layout`)                            |
| `timeout`     | secondi massimi di esecuzione (default 30, `None` = illimitato)           |

Senza `stdin_file` né `stdin_text` il programma legge EOF: non resta mai in
attesa del terminale.

### Breakpoint

| Forma             | Significato                                |
| ----------------- | ------------------------------------------ |
| `12` o `"12"`     | riga 12 del primo sorgente                 |
| `"altro.c:12"`    | riga 12 di `altro.c`                       |
| `("altro.c", 12)` | idem, come tupla                           |
| `"main"`          | ingresso della funzione `main`             |

Ogni passaggio per un breakpoint produce uno snapshot, quindi un breakpoint in un
ciclo produce un'animazione con un passo per iterazione. Un breakpoint che non
corrisponde a codice eseguibile (es. una riga vuota) viene segnalato in
`warnings` e ignorato.

### Cosa visualizzare

`Show` è un flag combinabile con `|`: `CODE`, `STACK`, `HEAP`, `STDIN`,
`STDOUT`, `IO` (= `STDIN | STDOUT`), `ALL`. Si accettano anche stringhe o elenchi
di nomi: `"code,stack,heap"`, `["code", "stdin"]`.

| Elemento | Cosa disegna                                                                    |
| -------- | ------------------------------------------------------------------------------- |
| `CODE`   | il listato (`\lstinputlisting`) e un riquadro sulla riga corrente               |
| `STACK`  | una cella per variabile, per ogni frame del codice utente; array e struct sono appiattiti in celle scalari |
| `HEAP`   | i blocchi `malloc`/`calloc`/`realloc` ancora vivi, con i campi decodificati     |
| `STDIN`  | il buffer di input, con una freccia sul prossimo carattere da leggere           |
| `STDOUT` | il buffer di output, con una freccia sul punto di scrittura                     |

I puntatori che puntano a una cella visualizzata sono disegnati come frecce, quelli
nulli mostrano `0`, quelli a `char *` fuori dai blocchi mostrano la stringa.

### Posizioni e dimensioni

Tutte le coordinate (in cm) stanno in `Layout`, con valori di default pensati per
una slide 16:9. I principali:

```python
Layout(stack_x=14.0, stack_y=0.0,      # colonna dello stack
       cell_width=1.5, cell_height=1.0,
       heap_x=9.0, heap_y=-0.5,        # primo blocco dell'heap
       heap_dx=2.0, heap_dy=-1.6,      # passo fra i blocchi
       heap_columns=1,                 # blocchi per riga
       io_x=0.5, io_y=-4.5,            # buffer di stdin (stdout sta sotto)
       io_length=30,                   # caselle mostrate
       hide_addresses=False)
```

Se `io_y` è `None` i buffer si piazzano sotto il codice. Vedi i campi di `Layout`
in [lldb_animator/layout.py](lldb_animator/layout.py) per l'elenco completo
(listing, larghezza del codice, ecc.).

## Uso da riga di comando

```sh
lldb-animator prog.c -b 26 -b somma -s code,stack,heap --stdin prog.in -o prog-tikz.tex
```

| Opzione                    | Significato                                      |
| -------------------------- | ------------------------------------------------ |
| `SORGENTE.c ...`           | file C                                           |
| `-b`, `--breakpoint`       | breakpoint (ripetibile, obbligatorio)            |
| `-s`, `--show`             | elementi da mostrare (default `code,stack,heap`) |
| `-o`, `--output`           | file TikZ da scrivere (obbligatorio)             |
| `--stdin`, `--stdin-text`  | standard input da file o da testo                |
| `--executable`             | eseguibile già compilato con `-g`                |
| `--cc`, `--cflags`         | compilatore e opzioni (default `cc`, `-g -O0`)   |
| `--timeout`                | secondi massimi, 0 = illimitato (default 30)     |
| `--args ARG...`            | argomenti del programma (tutto ciò che segue)    |

È disponibile anche come `python -m lldb_animator`.

## Usare il risultato in Beamer

Il file generato contiene solo comandi TikZ: va incluso dentro una
`tikzpicture`, in una frame che abbia animazioni.

```latex
\begin{frame}
  \begin{tikzpicture}
    \input{prog-tikz.tex}
  \end{tikzpicture}
\end{frame}
```

Il preambolo deve caricare `tikz` con le librerie `positioning` e `arrows`/`arrows.meta`,
`listings` e definire lo stile `changed` (gli elementi nuovi o modificati rispetto
allo snapshot precedente lo ricevono). Nel progetto lo fa
[programmazione.sty](programmazione.sty), con `\tikzstyle{changed}=[red]`.

Il percorso del listato è scritto relativo alla cartella del file `output`: compila
il documento da quella cartella (o scrivi l'output accanto al `.tex` principale).

Esempi completi:

- [examples/quoziente-resto-due-var/](examples/quoziente-resto-due-var/): codice,
  stack, stdin e stdout.
- [examples/lista/](examples/lista/): lista concatenata e array sull'heap, più una
  chiamata di funzione con due frame sullo stack.

```sh
cd examples/lista
make lista.pdf
```

## Come funziona

```
programma C ──► collector ──► Snapshot ──► layout ──► Element ──► timeline ──► .tex
              (usa LLDB)     (model.py)  (layout.py)  (tikz.py)  (timeline.py)
```

1. **Compilazione** (`api.py`). Si compila con `-g`, di solito `-O0`: senza
   informazioni di debug e con ottimizzazioni le variabili non si vedono.
2. **Raccolta** (`collector.py`). Il programma viene avviato con LLDB come libreria.
   Si impostano i breakpoint richiesti; a ogni stop si legge lo stato:
   - **Stack**: si risalgono i frame e si tengono solo quelli con riga di codice
     in uno dei sorgenti dati (si escludono libc e startup). Le variabili di
     ogni frame sono appiattite in celle con indirizzo e valore.
   - **Heap**: si mettono breakpoint interni su `malloc`, `calloc`, `realloc` e
     `free`. Per ogni chiamata proveniente dal codice utente si leggono gli
     argomenti (secondo la convenzione di chiamata dell'architettura), si esce
     dalla funzione e si legge il puntatore restituito. Si tiene così un elenco
     dei blocchi vivi con la loro dimensione.
   - **Tipo dei blocchi**: il tipo di un blocco si deduce dai puntatori che lo
     puntano (variabili o campi di altri blocchi). Se la dimensione del tipo
     puntato è compatibile con quella allocata, il blocco viene decodificato
     come istanza o array di quel tipo. Si procede finché si trovano nuovi tipi,
     quindi `p->next->dato` funziona anche se solo `p` è una variabile.
   - **I/O**: si leggono dalla memoria del processo i campi di
     `_IO_2_1_stdin_` e `_IO_2_1_stdout_` (struttura `FILE` della glibc).
3. **Layout** (`layout.py`). Una `Scene` trasforma ogni snapshot in elementi TikZ
   (`Node`, `Path`) in posizioni assolute. Le celle dello stack si impilano; i blocchi
   dell'heap occupano la prima posizione libera della griglia e la mantengono per
   tutta l'animazione; le frecce dei puntatori scelgono gli angoli di uscita e
   ingresso in base alla posizione relativa.
4. **Timeline** (`timeline.py`). Gli elementi uguali in snapshot diversi vengono
   fusi in un solo comando con `\uncover<1-3,5>{...}`. Un elemento che non era
   presente nello snapshot precedente riceve lo stile `changed`.

Solo `collector.py` dipende da LLDB; il resto lavora su dati semplici
(`model.py`) ed è testabile senza debugger.

## Limiti

- L'I/O e il tracciamento dell'heap dipendono dalla glibc; l'heap è supportato su
  x86, x86-64 e aarch64.
- Il tipo di un blocco dell'heap non è deducibile se nessun puntatore visibile lo
  punta con un tipo di dimensione compatibile: in quel caso è disegnato vuoto.
- Le variabili in registro (senza indirizzo in memoria) non vengono mostrate.
- Gli array sono troncati ai primi 64 elementi.
- Un programma che termina senza passare per un breakpoint produce un'animazione
  vuota (`len(result) == 0`), senza avvisi.

## Test

```sh
pipenv run python -m pytest
```

`tests/test_pure.py` copre layout, rendering e timeline senza LLDB.
`tests/test_integration.py` compila ed esegue un programma C sotto LLDB (viene
saltato se manca il modulo `lldb` o il compilatore).
