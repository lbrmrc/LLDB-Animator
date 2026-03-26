"""
animator.py — LLDB-based memory state animator for C programs.

Produces TikZ/Beamer overlay commands that visualize memory snapshots
at each breakpoint hit during program execution.

This is a standalone Python script that uses the LLDB Python bindings
as a library (no need to run inside a debugger).
"""

from collections import namedtuple
import itertools
import lldb
import copy
import os

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
    """Convert an SBValue (typically a pointer) to its decimal string."""
    return str(val.GetValueAsUnsigned())


def decValAddress(val):
    """Get the address of an SBValue as a decimal string."""
    addr = val.AddressOf()
    if addr.IsValid():
        return str(addr.GetValueAsUnsigned())
    # Fallback: try load address
    return str(val.GetAddress().GetLoadAddress(val.GetTarget()))


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


def formatCode(s):
    return "\\texttt{{{0}}}".format(s.split(' ')[0])


def nullPointer():
    return formatCode("0")


def formatAddress(s):
    return "\\texttt{{\\tiny{{{0}}}}}".format(s)


def formatChar(s):
    return "\\texttt{{\\tiny{{{0}}}}}".format(s)


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


def arrayChars(frame, expr, length, xPos, yPos, width, height):
    """Render an array of chars from an expression evaluated in the given frame."""
    elements = []
    base_val = frame.EvaluateExpression(expr)
    for i in range(length):
        child_expr = "({0})[{1}]".format(expr, i)
        v1 = frame.EvaluateExpression(child_expr)
        raw = v1.GetSummary() or v1.GetValue() or ""
        # Clean up the display value
        content = raw.replace("\\000", "\\0").replace(
            "\\", "\\textbackslash{}")
        if content.startswith("'") and content.endswith("'"):
            content = content[1:-1]
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

    def elements(self, thread):
        return []


class MemoryRenderer(Renderer):

    def __init__(self, xPos, yPos, cell_height, rotate=True, heap=None, heapTopLeft=Point(0.0, 0.0), heapPositions=[], hideAddresses=False, sourceFile=None):
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
        self.sourceFile = sourceFile

    def getHeapCoordinates(self, address):
        if address in self.heapCoordinates:
            return self.heapCoordinates[address]
        else:
            offsets = self.heapPositions.pop(0)
            coords = Point(self.heapTopLeft.x + offsets.x,
                           self.heapTopLeft.y + offsets.y)
            self.heapCoordinates[address] = coords
            return coords

    def _getBlockVariables(self, block, frame):
        """Get variables declared in a specific block (not its parents)."""
        variables = []
        # Get all variables in the frame
        all_args = frame.GetVariables(True, False, False, True)   # arguments
        all_locals = frame.GetVariables(False, True, False, True)  # locals

        for var_list in [all_args, all_locals]:
            for i in range(var_list.GetSize()):
                var = var_list.GetValueAtIndex(i)
                # Check if this variable's declaration is in the given block
                var_decl = var.GetDeclaration()
                if var_decl.IsValid():
                    variables.append(var)
                elif block is None:
                    # If we can't determine the block, include all
                    variables.append(var)
        return variables

    def frameElementsOffset(self, frame, offset):
        """Process a frame and generate TikZ elements for all its variables."""
        # Collect all variables: arguments first, then locals
        all_vars = []
        args = frame.GetVariables(True, False, False, True)
        for i in range(args.GetSize()):
            all_vars.append(args.GetValueAtIndex(i))
        locals_ = frame.GetVariables(False, True, False, True)
        for i in range(locals_.GetSize()):
            all_vars.append(locals_.GetValueAtIndex(i))

        elements = []
        newOffset = offset
        for var in all_vars:
            type_class = var.GetType().GetCanonicalType().GetTypeClass()
            if type_class == lldb.eTypeClassArray:
                varElements, newOffset = self.arrayElementsOffset(
                    var, frame, newOffset)
            else:
                varElements, newOffset = self.symbolElementsOffset(
                    var, frame, newOffset)
            elements.extend(varElements)

        if self.FUNCTION_NAMES and len(all_vars) > 0:
            name = frame.GetFunctionName()
            line_entry = frame.GetLineEntry()
            line_num = line_entry.GetLine() if line_entry.IsValid() else 0
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
                                                  " ({0})".format(str(line_num)),
                                                  position=Point(
                                                      x=x, y=(yStart + yEnd) / 2),
                                                  options=["above", "rotate=-90"] if self.rotate else ["right"])))
        return elements, newOffset

    def arrayElementsOffset(self, var, frame, offset):
        """Handle array-type variables."""
        elements = []
        symbolOffset = offset
        num_children = var.GetNumChildren()
        for i in range(num_children - 1, -1, -1):
            child = var.GetChildAtIndex(i)
            addr_val = child.AddressOf()
            if not addr_val.IsValid() or addr_val.GetValueAsUnsigned() == 0:
                continue
            address = str(addr_val.GetValueAsUnsigned())
            self.addresses.append(address)
            name = "{0}[{1}]".format(formatCode(var.GetName()), i)
            symbolElements = self.symbolElements(
                address, name, child, symbolOffset)
            elements.extend(symbolElements)
            symbolOffset = symbolOffset - self.CELL_HEIGHT

        return elements, symbolOffset

    def symbolElements(self, address, name, val, offset):
        """Generate TikZ elements for a single variable cell."""
        content = formatCode(val.GetValue() or str(val.GetValueAsUnsigned()))
        type_class = val.GetType().GetCanonicalType().GetTypeClass()

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

        is_pointer = type_class == lldb.eTypeClassPointer
        if not is_pointer:
            elements.append(Element(type="node",
                                    data=NodeData(id=None,
                                                  content=content,
                                                  position="{0}.south".format(
                                                      address),
                                                  options=["above"])))

        if is_pointer and val.GetValueAsUnsigned() == 0:
            elements.append(Element(type="node",
                                    data=NodeData(id=None,
                                                  content=nullPointer(),
                                                  position="{0}.south".format(
                                                      address),
                                                  options=["above"])))

        return elements

    def symbolElementsOffset(self, var, frame, offset):
        """Handle a scalar or pointer variable."""
        addr_val = var.AddressOf()
        if not addr_val.IsValid() or addr_val.GetValueAsUnsigned() == 0:
            # Variable has no valid memory address (register-only or optimized out)
            return [], offset
        address = str(addr_val.GetValueAsUnsigned())
        self.addresses.append(address)
        type_class = var.GetType().GetCanonicalType().GetTypeClass()
        if type_class == lldb.eTypeClassPointer:
            self.pointers.append((address, str(var.GetValueAsUnsigned())))
        name = formatCode(var.GetName())
        elements = self.symbolElements(address, name, var, offset)
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

    def elements(self, thread):
        """Collect all memory elements from the current thread state."""
        frame = thread.GetSelectedFrame()
        # Walk up the frame stack, only including frames from the user's source file
        frames = []
        for i in range(thread.GetNumFrames()):
            f = thread.GetFrameAtIndex(i)
            if not f.GetLineEntry().IsValid() or not f.GetFunction().IsValid():
                continue
            # Filter to only frames from the user's source file
            frame_file = f.GetLineEntry().GetFileSpec().GetFilename()
            if self.sourceFile and frame_file != os.path.basename(self.sourceFile):
                continue
            frames.append(f)

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
            target = thread.GetProcess().GetTarget()
            delta = 0.15
            for (type_expr, address_str) in self.heap.cells:
                self.addresses.append(address_str)
                coords = self.getHeapCoordinates(address_str)
                elements.append(Element(type="node",
                                        data=NodeData(id=address_str,
                                                      content="",
                                                      position=coords,
                                                      options=["draw",
                                                               "minimum width={0}cm".format(
                                                                   self.CELL_WIDTH),
                                                               "minimum height = {0}cm".format(self.CELL_HEIGHT)])))

                frame0 = thread.GetSelectedFrame()
                dato_expr = "(({0}){1})->dato".format(type_expr, address_str)
                dato_val = frame0.EvaluateExpression(dato_expr)
                elements.append(Element(type="node",
                                        data=NodeData(id="{0}.dato".format(address_str),
                                                      content=dato_val.GetValue() or "?",
                                                      position=Point(
                                                          coords.x - self.CELL_WIDTH / 6, coords.y),
                                                      options=["draw",
                                                               "minimum width={0}cm".format(
                                                                   2 / 3 * self.CELL_WIDTH),
                                                               "minimum height = {0}cm".format(self.CELL_HEIGHT)])))

                next_expr = "(({0}){1})->next".format(type_expr, address_str)
                next_val = frame0.EvaluateExpression(next_expr)
                nextValue = str(next_val.GetValueAsUnsigned())
                next_addr_expr = "&((({0}){1})->next)".format(type_expr, address_str)
                next_addr_val = frame0.EvaluateExpression(next_addr_expr)
                nextAddress = str(next_addr_val.GetValueAsUnsigned())

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
                if nextValue == '0':
                    elements.append(Element(type="node",
                                            data=NodeData(id=None,
                                                          content=nullPointer(),
                                                          position=Point(
                                                              coords.x + self.CELL_WIDTH / 3 - 0.5 * delta, coords.y),
                                                          options=["minimum width={0}cm".format(
                                                              self.CELL_WIDTH / 3 - delta),
                                                              "minimum height = {0}cm".format(self.CELL_HEIGHT - 2 * delta)])))

        for p, a in self.pointers:
            if a in self.addresses:
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

    def __init__(self, sourceFile=None):
        self.sourceFile = sourceFile

    def elements(self, thread):
        frame = thread.GetSelectedFrame()
        line_entry = frame.GetLineEntry()
        if not line_entry.IsValid():
            return []

        if self.sourceFile:
            filename = self.sourceFile
        else:
            filename = line_entry.GetFileSpec().fullpath

        nLines = file_len(filename)
        lineNumber = line_entry.GetLine()
        yPos = round(- self.SOURCE_OFFSET - (lineNumber - 0.5)
                     * self.SOURCE_LINE_WIDTH, 3)
        return [Element(type="node",
                        data=NodeData(id=None,
                                      content="\\lstinputlisting[{1}]{{{0}}}".format(
                                          filename, ",".join(self.LstSet)),
                                      position=Point(x=0.35, y=0),
                                      options=["below right"])),
                Element(type="node",
                        data=NodeData(id=None,
                                      content="",
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

    def streamName(self):
        return {
            "_IO_stdin": "stdin",
            "stdin": "stdin",
            "_IO_stdout": "stdout",
            "stdout": "stdout"
        }[self.name]

    def elements(self, thread):
        frame = thread.GetSelectedFrame()
        # Check if the stream buffer is initialized
        check = frame.EvaluateExpression("{0}->_IO_read_base".format(self.name))
        if not check.IsValid() or check.GetValueAsUnsigned() == 0:
            return []

        base_expr = "{0}->_IO_read_base".format(self.name)
        base_val = frame.EvaluateExpression(base_expr)
        if not base_val.IsValid():
            return []

        elements = arrayChars(frame, base_expr,
                              self.length, self.xPos, self.yPos, self.width, self.height)

        if self.readPointer:
            read_ptr = frame.EvaluateExpression("{0}->_IO_read_ptr".format(self.name))
            base_ptr = frame.EvaluateExpression(base_expr)
            offset_val = read_ptr.GetValueAsUnsigned() - base_ptr.GetValueAsUnsigned()
            elements.append(Element(type="node",
                                    data=NodeData(id=None,
                                                  content="$\\uparrow$",
                                                  position=Point(x=self.xPos + self.width * offset_val,
                                                                 y=self.yPos + self.height),
                                                  options=[])))
        if self.writePointer:
            write_ptr = frame.EvaluateExpression("{0}->_IO_write_ptr".format(self.name))
            base_ptr = frame.EvaluateExpression(base_expr)
            offset_val = write_ptr.GetValueAsUnsigned() - base_ptr.GetValueAsUnsigned()
            elements.append(Element(type="node",
                                    data=NodeData(id=None,
                                                  content="$\\downarrow$",
                                                  position=Point(x=self.xPos + self.width * offset_val,
                                                                 y=self.yPos + self.height),
                                                  options=[])))

        elements.append(Element(type="node",
                                data=NodeData(id=None,
                                              content=self.streamName(),
                                              position=Point(
                                                  x=self.xPos + self.width * (self.length - 1) / 2,
                                                  y=self.yPos - self.height),
                                              options=[])))
        return elements


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


class Heap():

    def __init__(self):
        self.cells = []

    def add(self, thread, expression):
        frame = thread.GetSelectedFrame()
        value = frame.EvaluateExpression(expression)
        type_name = value.GetType().GetName()
        formatted = str(value.GetValueAsUnsigned())
        self.cells.append((type_name, formatted))

    def remove(self, thread, expression):
        frame = thread.GetSelectedFrame()
        value = frame.EvaluateExpression(expression)
        addr = str(value.GetValueAsUnsigned())
        self.cells = [(t, v) for t, v in self.cells if v != addr]


class Animator:

    def __init__(self, program, infile, breakpoints, rends, sourceFile=None, heapExprs=[], heap=None):
        self.program = program
        self.infile = infile
        self.breakpoints = breakpoints
        self.renderers = rends
        self.snapshot_counter = 0
        self.numberedElements = []
        self.heapExpressions = heapExprs
        self.heap = heap
        self.sourceFile = sourceFile

    def snapshotNumberedElements(self, thread):
        self.snapshot_counter += 1
        elements = []
        for r in self.renderers:
            elements.extend(r.elements(thread))
        return [NumberedElement(number=self.snapshot_counter,
                                element=e) for e in elements]

    def takeSnapshot(self, thread):
        self.numberedElements.extend(self.snapshotNumberedElements(thread))

    def movie(self, outfile):
        """Creates a TikZ animation of the program run using LLDB."""
        try:
            os.remove("stdout.txt")
        except FileNotFoundError:
            pass

        # Create a debugger instance (non-interactive)
        debugger = lldb.SBDebugger.Create()
        debugger.SetAsync(False)

        # Create target from executable
        target = debugger.CreateTarget(self.program)
        if not target:
            print("Error: could not create target '{0}'".format(self.program))
            return

        # Determine the source file for breakpoints
        if self.sourceFile:
            src_file = self.sourceFile
        else:
            src_file = self.program + ".c"

        # Build sets for heap breakpoints vs regular breakpoints
        heap_bp_map = {}  # breakpoint_id -> (kind, expression)
        regular_bp_ids = set()

        # Set heap breakpoints
        for (line, kind, expr) in self.heapExpressions:
            bp = target.BreakpointCreateByLocation(src_file, int(line))
            if bp.IsValid():
                heap_bp_map[bp.GetID()] = (kind, expr)

        # Set regular (snapshot) breakpoints
        for breakpoint_line in self.breakpoints:
            bp = target.BreakpointCreateByLocation(src_file, int(breakpoint_line))
            if bp.IsValid():
                regular_bp_ids.add(bp.GetID())

        # Set up launch info
        launch_info = lldb.SBLaunchInfo(None)
        if self.infile:
            launch_info.AddOpenFileAction(0, self.infile, True, False)  # stdin
        # Redirect stdout to file
        launch_info.AddOpenFileAction(1, "stdout.txt", False, True)
        launch_info.SetWorkingDirectory(os.getcwd())

        error = lldb.SBError()
        process = target.Launch(launch_info, error)
        if not process or error.Fail():
            print("Error launching process: {0}".format(error.GetCString()))
            return

        # Main execution loop
        while True:
            state = process.GetState()
            if state == lldb.eStateExited:
                break
            if state == lldb.eStateStopped:
                thread = process.GetSelectedThread()
                stop_reason = thread.GetStopReason()
                if stop_reason == lldb.eStopReasonBreakpoint:
                    bp_id = thread.GetStopReasonDataAtIndex(0)
                    if bp_id in heap_bp_map:
                        kind, expr = heap_bp_map[bp_id]
                        if kind == "malloc":
                            self.heap.add(thread, expr)
                        else:
                            self.heap.remove(thread, expr)
                    if bp_id in regular_bp_ids:
                        self.takeSnapshot(thread)
                process.Continue()
            else:
                # Process crashed or something unexpected
                print("Process stopped with state: {0}".format(state))
                break

        # Generate TikZ output
        tikz_string = ""
        emphasizedChanged = markChanged(self.numberedElements)
        for group in groupByElement(emphasizedChanged):
            tikz_string += (renderIntervals(list2intervalList(group.numbers)) +
                            "{" + renderElement(group.element) + ";}\n")
        with open(outfile, "w") as text_file:
            text_file.write(tikz_string)

        lldb.SBDebugger.Destroy(debugger)
