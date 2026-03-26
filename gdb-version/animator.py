"Asd"

from collections import namedtuple
import itertools
import gdb
import copy
import os
import signal

Symbol = namedtuple("Symbol", "ordinal address name type value")
Block = namedtuple("Block", "ordinal symbols")
Frame = namedtuple("Frame", "ordinal blocks")
Snapshot = namedtuple("Snapshot", "ordinal frames")

Point = namedtuple("Point", "x y")
NodeData = namedtuple("NodeData", "id content position options")
LineData = namedtuple("LineData", "points options outin")
Element = namedtuple("Element", "type data")
NumberedElement = namedtuple("NumberedElement", "number element")
NumberListedElement = namedtuple("NumberListedElement", "numbers element")

def decVal(val):
    #print(str(int(str(val).split(' ')[0],0)))
    return str(int(str(val).split(' ')[0],0))

def decValAddress(val):
    #print(str(int(str(val.address).split(' ')[0],0)))
    return str(int(str(val.address).split(' ')[0],0))

def markChanged(numberedElements):
    emphasized = []
    for number, element in numberedElements:
        elementCopy = Element(**(copy.deepcopy(element._asdict())))
        if number != 1 and not ((number - 1, element) in numberedElements):
            try:
                elementCopy.data.options.append("changed")
            except Exception as e:
                print(e)
        emphasized.append(NumberedElement(number, elementCopy))
    return emphasized


def groupByElement(numberedElements):
    grouped = []
    for ne in numberedElements:
        found = False
        for gr in grouped:
            if gr.element == ne.element:
                gr.numbers.append(ne.number)
                found = True
                break
        if not found:
            grouped.append(NumberListedElement(numbers=[ne.number],
                                               element=ne.element))
    return grouped


def file_len(fname):
    with open(fname) as f:
        for i, l in enumerate(f):
            pass
    return i + 1


def formatCode(str):
    return "\\texttt{{{0}}}".format(str.split(' ')[0])

def nullPointer():
    return formatCode("0")

def formatAddress(str):
    return "\\texttt{{\\tiny{{{0}}}}}".format(str)

def formatChar(str):
    return "\\texttt{{\\tiny{{{0}}}}}".format(str)

def renderNodeId(id):
    if id is None:
        return ""
    else:
        return "({0})".format(str(id))


def renderPoint(p):
    try:
        return "({0},{1})".format(p.x, p.y)
    except AttributeError:
        return "({0})".format(p)


def renderNodePosition(pos):
    if pos is None:
        return ""
    else:
        return "at {0}".format(renderPoint(pos))


def renderElement(element):
    d = element.data
    if element.type == "node":
        return "\\node [{0}] {1} {2} {{{3}}}".format(",".join(d.options),
                                                     renderNodePosition(
            d.position),
            renderNodeId(d.id),
            d.content)
    elif element.type == "line":
        if not d.outin is None:
            l = []
            if not d.outin[0] is None:
                l.append("out={0}".format(d.outin[0]))
            if not d.outin[1] is None:
                l.append("in={0}".format(d.outin[1]))
            outin = "to[" + ",".join(l) + "]"
        return "\\draw [{0}] {1}".format(",".join(d.options), (" {0} ".format("--" if d.outin is None else outin).join(renderPoint(p) for p in d.points)))


def arrayChars(expr, length, xPos, yPos, width, height):
    # print(expr)
    elements = []
    for i in range(length):
        v1 = expr + i
        content = str(v1.dereference()).replace("\\000", "\\0").replace(
            "\\", "\\textbackslash{}").split(" ")[-1]
        elements.append(Element(type="node",
                                data=NodeData(id=None,
                                              content=formatChar(content),
                                              position=Point(x=xPos, y=yPos),
                                              options=["draw",
                                                       "text width={0}cm".format(
                                                           width),
                                                       "align=center",
                                                       "inner sep=0pt",
                                                       "minimum height={0}cm".format(height)])))
        xPos += width
    return elements


class Renderer():

    def elements(self):
        return []


class MemoryRenderer(Renderer):

    def __init__(self, xPos, yPos, cell_height, rotate=True, heap=None, heapTopLeft=Point(0.0, 0.0), heapPositions=[], hideAddresses=False):
        self.CELL_HEIGHT = cell_height
        self.xPos = xPos
        self.yPos = yPos
        self.CELL_WIDTH = 1.5
        self.FUNCTION_NAMES = True
        self.rotate = rotate
        self.heap = heap
        self.heapTopLeft = heapTopLeft
        self.heapPositions = heapPositions
        self.heapCoordinates = {}
        self.hideAddresses = hideAddresses

    def getHeapCoordinates(self, address):
        if address in self.heapCoordinates:
            return self.heapCoordinates[address]
        else:
            offsets = self.heapPositions.pop(0)
            coords = Point(self.heapTopLeft.x + offsets.x,
                           self.heapTopLeft.y + offsets.y)
            self.heapCoordinates[address] = coords
            return coords

    def frameElementsOffset(self, frame, offset):
        bl = frame.block()
        blocks = []
        while bl != None:
            blocks.append(bl)
            bl = bl.superblock
        blocks.reverse()
        elements = []
        newOffset = offset
        for bl in blocks:
            els, newOffset = self.blockElementsOffset(
                bl, frame, newOffset)
            elements.extend(els)
        if self.FUNCTION_NAMES:
            name = frame.name()
            yStart = offset + self.CELL_HEIGHT / 2 - 0.1
            yEnd = newOffset + self.CELL_HEIGHT / 2 + 0.1
            x = self.xPos + self.CELL_WIDTH / 2 + 0.2
            elements.append(Element(type="line",
                                    data=LineData(points=[Point(x, yStart), Point(x, yEnd)],
                                                  options=[],
                                                  outin=None)))
            elements.append(Element(type="node",
                                    data=NodeData(id=None,
                                                  content=name +
                                                  " ({0})".format(
                                                      str(frame.find_sal().line)),
                                                  position=Point(
                                                      x=x, y=(yStart + yEnd) / 2),
                                                  options=["above", "rotate=-90"] if self.rotate else ["right"])))
        return elements, newOffset

    def blockElementsOffset(self, block, frame, offset):
        elements = []
        symbolOffset = offset
        for symbol in block:
            if symbol.is_variable or symbol.is_argument:
                if symbol.type.code == gdb.TYPE_CODE_ARRAY:
                    symbolElements, symbolOffset = self.arrayElementsOffset(
                        symbol, block, frame, symbolOffset)
                else:
                    symbolElements, symbolOffset = self.symbolElementsOffset(
                        symbol, block, frame, symbolOffset)
                elements.extend(symbolElements)
        return elements, symbolOffset

    def arrayElementsOffset(self, symbol, block, frame, offset):
        elements = []
        symbolOffset = offset
        for i in range(symbol.type.range()[1], symbol.type.range()[0] - 1, -1):
            # print("{0} ".format(i))
            val = symbol.value(frame)[i]
            content = formatCode(str(val))
            address = decValAddress(val)
            self.addresses.append(address)
            name = "{0}[{1}]".format(formatCode(symbol.name), i)
            symbolElements = self.symbolElements(
                address, name, val, symbolOffset)
            elements.extend(symbolElements)
            symbolOffset = symbolOffset - self.CELL_HEIGHT

        return elements, symbolOffset

    def symbolElements(self,  address, name, val, offset):
        content = formatCode(str(val))
        elements = [Element(type="node",
                            data=NodeData(id=address,
                                          content="",
                                          position=Point(
                                              x=self.xPos, y=offset),
                                          options=["draw",
                                                   "minimum width={0}cm".format(
                                                       self.CELL_WIDTH),
                                                   "minimum height = {0}cm".format(self.CELL_HEIGHT)])),
                    Element(type="node",
                            data=NodeData(id=None,
                                          content=name,
                                          position=None,
                                          options=["left=0.0cm of {0}".format(address)]))]
        if not self.hideAddresses:
            elements.append(Element(type="node",
                                    data=NodeData(id=None,
                                                  content=formatAddress(
                                                      address),
                                                  position="{0}.north east".format(
                                                      address),
                                                  options=["below left"])))
        if not val.type.strip_typedefs().code == gdb.TYPE_CODE_PTR:
            elements.append(Element(type="node",
                                    data=NodeData(id=None,
                                                  content=content,
                                                  position="{0}.south".format(
                                                      address),
                                                  options=["above"])))
        if val.type.strip_typedefs().code == gdb.TYPE_CODE_PTR and str(val) == '0x0':
            elements.append(Element(type="node",
                                    data=NodeData(id=None,
                                                  content=nullPointer(),
                                                  position="{0}.south".format(
                                                      address),
                                                  options=["above"])))

        return elements

    def symbolElementsOffset(self, symbol, block, frame, offset):
        # print(offset)
        val = symbol.value(frame)
        #print(val)
        #print(val.address)
        address = decValAddress(val)
        self.addresses.append(address)
        if val.type.strip_typedefs().code in [gdb.TYPE_CODE_PTR]:
            #print(str(val))
            self.pointers.append((address, decVal(val)))
        name = formatCode(symbol.name)
        type = str(val.type)
        options = []
        elements = self.symbolElements(address, name, val, offset)

        return elements, offset - self.CELL_HEIGHT

    def findElementPosition(self, elements, start):
        return next(filter((lambda element: element.type == 'node' and element.data.id == start), elements)).data.position


    def getOutIn(self, elements, start, end):
        sPos = self.findElementPosition(elements, start)
        ePos = self.findElementPosition(elements, end)
        dx, dy = ePos.x - sPos.x, ePos.y - sPos.y
        if dx == 0:
            if dy >= 0:
                out = 45
            else:
                out = 225
        elif dx > 0 and dy >= 0:
            out = 45
        elif dx < 0 and dy >= 0:
            out = 135
        elif dx > 0 and dy < 0:
            out = 315
        else:
            out = 225
        if dx == 0:
            if dy > 0:
                in_ = 315
            else:
                in_ = 135
        elif dx > 0 and abs(dx) >= 2 * abs(dy):
            in_ = 180
        elif dx < 0 and abs(dx) >= 2 * abs(dy):
            in_ = 0
        elif dy > 0:
            in_ = 270
        else:
            in_ = 90
        return out, in_

    def elements(self):
        fr = gdb.selected_frame()
        frames = [fr]
        while not (fr.older() is None):
            fr = fr.older()
            frames.append(fr)

        elements = []
        self.pointers = []
        self.addresses = []
        offset = self.yPos
        frames.reverse()
        for frame in frames:
            newElements, offset = self.frameElementsOffset(
                frame, offset)
            elements.extend(newElements)

        if not (self.heap is None):
            delta = 0.15
            for (type, address) in self.heap.cells:
                self.addresses.append(decVal(address))
                coords = self.getHeapCoordinates(
                    decVal(address))
                elements.append(Element(type="node",
                                        data=NodeData(id=decVal(address),
                                                      content="",
                                                      position=coords,
                                                      options=["draw",
                                                               "minimum width={0}cm".format(
                                                                   self.CELL_WIDTH),
                                                               "minimum height = {0}cm".format(self.CELL_HEIGHT)])))

                elements.append(Element(type="node",
                                        data=NodeData(id="{0}.dato".format(address),
                                                      content=str(gdb.Value(int(address, 0)).cast(
                                                          type).dereference()['dato']),
                                                      position=Point(
                                                          coords.x - self.CELL_WIDTH / 6, coords.y),
                                                      options=["draw",
                                                               "minimum width={0}cm".format(
                                                                   2 / 3 * self.CELL_WIDTH),
                                                               "minimum height = {0}cm".format(self.CELL_HEIGHT)])))

                nextField = gdb.Value(int(address, 0)).cast(
                    type).dereference()['next']
                nextValue = decVal(str(nextField))
                nextAddress = decVal(str(nextField.address))

                self.pointers.append((nextAddress, nextValue))
                self.addresses.append(nextAddress)

                elements.append(Element(type="node",
                                        data=NodeData(id=nextAddress,
                                                      content="",
                                                      position=Point(
                                                          coords.x + self.CELL_WIDTH / 3 - 0.5 * delta, coords.y),
                                                      options=["draw",
                                                               "minimum width={0}cm".format(
                                                                   self.CELL_WIDTH / 3 - delta),
                                                               "minimum height = {0}cm".format(self.CELL_HEIGHT - 2 * delta)])))
                if nextValue == '0x0':
                    elements.append(Element(type="node",
                                            data=NodeData(id=None,
                                                          content=nullPointer(),
                                                          position=Point(
                                                              coords.x + self.CELL_WIDTH / 3 - 0.5 * delta, coords.y),
                                                          options=["minimum width={0}cm".format(
                                                              self.CELL_WIDTH / 3 - delta),
                                                              "minimum height = {0}cm".format(self.CELL_HEIGHT - 2 * delta)])))
        
        print(self.pointers)
        print(self.addresses)
        for p, a in self.pointers:
            if a in self.addresses:
                print("trovato")
                elements.append(Element(type="line",
                                        data=LineData(points=["{0}.center".format(p), "{0}".format(a)],
                                                      options=["*->"],
                                                      outin=self.getOutIn(elements, p, a))))
        return elements


class SourceRenderer(Renderer):

    LstSet = ["language=C",
              "basicstyle=\\ttfamily\\scriptsize",
              "numbers=left",
              "numberstyle=\\scriptsize",
              "breakatwhitespace=false",
              "breaklines=false",
              "showstringspaces=false",
              "commentstyle=\\color{purple}\\ttfamily"]

    SOURCE_LINE_WIDTH = 0.3348
    SOURCE_OFFSET = 0.2

    def elements(self):
        symtline = gdb.selected_frame().find_sal()
        nLines = file_len(symtline.symtab.filename)
        lineNumber = symtline.line
        yPos = round(- self.SOURCE_OFFSET - (lineNumber - 0.5)
                     * self.SOURCE_LINE_WIDTH, 3)
        return [Element(type="node",
                        data=NodeData(id=None,
                                      content="\\lstinputlisting[{1}]{{{0}}}".format(
                                          symtline.symtab.filename, ",".join(self.LstSet)),
                                      position=Point(x=0.35, y=0),
                                      options=["below right"])),
                Element(type="node",
                        data=NodeData(id=None,
                                      content="",  # "$\\Rightarrow$",
                                      position=Point(x=0.2, y=yPos),
                                      options=["draw",
                                               "minimum width=0.4cm",
                                               "minimum height=0.35cm",
                                               "left"]))]


class IORenderer(Renderer):

    def __init__(self, width, height, xPos, yPos, readPointer, writePointer, length, name):
        self.width = width
        self.height = height
        self.xPos = xPos
        self.yPos = yPos
        self.name = name
        self.length = length
        self.readPointer = readPointer
        self.writePointer = writePointer
        self.prevPointer = gdb.Value(0)

    def streamName(self):
        return {
            "_IO_stdin": "stdin",
            "stdin": "stdin",
            "_IO_stdout": "stdout",
            "stdout": "stdout"
        }[self.name]

    def elements(self):
        if str(gdb.parse_and_eval("{0}->_IO_read_base".format(self.name))) != "0x0":
            # if self.readPointer:
            #     basePointer = self.prevPointer if self.prevPointer != 0 else gdb.parse_and_eval(
            #         "{0}->_IO_read_base".format(self.name))
            # else:
            #     basePointer = self.prevPointer if self.prevPointer != 0 else gdb.parse_and_eval(
            #         "{0}->_IO_write_base".format(self.name))

            basePointer = gdb.parse_and_eval(
                "{0}->_IO_read_base".format(self.name))

            elements = arrayChars(basePointer,
                                  self.length, self.xPos, self.yPos, self.width, self.height)
            if self.readPointer:
                elements.append(Element(type="node",
                                        data=NodeData(id=None,
                                                      content="$\\uparrow$",
                                                      position=Point(x=self.xPos + self.width * int(gdb.parse_and_eval(
                                                          "{0}->_IO_read_ptr".format(self.name)) - basePointer), y=self.yPos + self.height),
                                                      options=[])))
            if self.writePointer:
                elements.append(Element(type="node",
                                        data=NodeData(id=None,
                                                      content="$\\downarrow$",
                                                      position=Point(x=self.xPos + self.width * int(gdb.parse_and_eval(
                                                          "{0}->_IO_write_ptr".format(self.name)) - basePointer), y=self.yPos + self.height),
                                                      options=[])))
            elements.append(Element(type="node",
                                    data=NodeData(id=None,
                                                  content=self.streamName(),
                                                  position=Point(
                                                      x=self.xPos + self.width * (self.length - 1) / 2, y=self.yPos - self.height),
                                                  options=[])))
            if self.readPointer:
                self.prevPointer = gdb.parse_and_eval(
                    "{0}->_IO_read_ptr".format(self.name))
            # else:
                # print(self.prevPointer)
                # self.prevPointer =
                # gdb.parse_and_eval("{0}->_IO_write_ptr".format(self.name))

            return elements
        else:
            return []


def list2intervalList(l):
    intervals = []
    if len(l) > 0:
        l1 = sorted(l)
        intervals.append((l1[0], l1[0]))
        for item in sorted(l)[1:]:
            if intervals[-1][1] == item - 1:
                intervals[-1] = (intervals[-1][0], item)
            else:
                intervals.append((item, item))
    return intervals


def renderIntervals(intervals):
    interval_strings = []
    for interval in intervals:
        if interval[0] == interval[1]:
            interval_strings.append(str(interval[0]))
        else:
            interval_strings.append("{0}-{1}".format(interval[0], interval[1]))
    return "\\uncover<" + ",".join(interval_strings) + ">"

# Snapshots = []


class MyBreakpoint(gdb.Breakpoint):
    "Breakpoint that takes a snapshot when it is hit"

    def __init__(self, animator, line):
        self.animator = animator
        super().__init__(line)

    def stop(self):
        "Called when breakpoint is hit"
        self.animator.takeSnapshot()
        return False


class Heap():

    def __init__(self):
        self.cells = []

    def add(self, expression):
        value = gdb.parse_and_eval(expression)
      #  print(value.type.strip_typedefs().code)
        # if value.type.strip_typedefs().code in [gdb.TYPE_CODE_PTR]:
        #     formatted = decValAddress(value)
        # else:    
        #     formatted = str(value)
        formatted = str(value)
        #print(formatted)
        self.cells.append((value.type, formatted))

    def remove(self, expression):
        value = gdb.parse_and_eval(expression)
        self.cells = [(t, v) for t, v in self.cells if v != str(value)]

class HeapBreakpoint(gdb.Breakpoint):
    "Breakpoint that takes a snapshot when it is hit"

    def __init__(self, line, kind, expression, heap):
        self.kind = kind
        self.expr = expression
        self.heap = heap
        super().__init__(line)

    def stop(self):
        "Called when breakpoint is hit"

        if self.kind == "malloc":
            self.heap.add(self.expr)
        else:
            self.heap.remove(self.expr)
        return False


class Animator:

    def __init__(self, program, infile, breakpoints, rends, heapExprs=[], heap=None):
        self.program = program
        self.infile = infile
        self.breakpoints = breakpoints
        self.renderers = rends
        self.snapshot_counter = 0
        self.numberedElements = []
        self.heapExpressions = heapExprs
        self.heap = heap

    def snapshotNumberedElements(self):
        self.snapshot_counter += 1
        elements = []
        for r in self.renderers:
            elements.extend(r.elements())
        return [NumberedElement(number=self.snapshot_counter,
                                element=e) for e in elements]

    def takeSnapshot(self):
        self.numberedElements.extend(self.snapshotNumberedElements())

    def movie(self, outfile):
     "creates a TiKZ animation of the program run"
     try:
            os.remove("stdout.txt")
     except FileNotFoundError:
            pass
     
     
        
     gdb.execute("file {0}".format(self.program))
     for (line, kind, expr) in self.heapExpressions:
            HeapBreakpoint(line, kind, expr, self.heap)
     for breakpoint in self.breakpoints:
            MyBreakpoint(self, breakpoint)
     command = "run {0} >stdout.txt".format("< {0}".format(
            self.infile) if not (self.infile is None) else "")
           # print(command)
     gdb.execute(command)
     tikz_string = ""
     emphasizedChanged = markChanged(self.numberedElements)
     for group in groupByElement(emphasizedChanged):
            tikz_string += (renderIntervals(list2intervalList(group.numbers)) +
                            "{" + renderElement(group.element) + ";}\n")
     with open(outfile, "w") as text_file:
            text_file.write(tikz_string)
    
     
def do_nothing(*args):
    pass