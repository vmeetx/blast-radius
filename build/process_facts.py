"""Writes down what one process does: one fact per line, unbuffered, to the file named by FACTS.

A killed process therefore loses nothing. The first letter says what kind of fact it is:
F path:line:name   a code object was entered (its first line and qualified name)
I path:line:name   the same, below a repository module that was being imported
M path             a module's own code ran
O path             a file was opened as data, or an attempt was made
D path             a directory was listed
E path             the existence, kind or size of a file was asked for
C path:line:name   the code of a function was read as an object
S / P              this process is a watched child / this process started a child
"""
import os
import sys

REPO = "/src/"
sink = None


def send_to(target):
    """Later facts go to this file. Children started from now on inherit it."""
    global sink
    previous, sink = sink, open(target, "ab", buffering=0)
    os.environ["FACTS"] = target
    if previous:
        previous.close()


def note(letter, text):
    if sink:
        sink.write((letter + "\t" + str(text) + "\n").encode("utf-8", "surrogateescape"))


def inside(name):
    """The path below the repository, or None."""
    full = os.path.normpath(os.path.join(os.getcwd(), name)) + "/"
    return full[len(REPO):-1] if full.startswith(REPO) else None


def label(code):
    return f"{inside(code.co_filename)}:{code.co_firstlineno}:{code.co_qualname}"


def callers(depth):
    step = sys._getframe(depth)
    while step is not None:
        yield step
        step = step.f_back


def entered(code, offset):
    source = code.co_filename
    if source[:1] != "<" and inside(source):
        if code.co_name == "<module>":
            note("M", inside(source))
        else:
            below_import = any(step.f_code.co_name == "<module>" and step.f_code.co_filename.startswith(REPO) for step in callers(2))
            note("I" if below_import else "F", label(code))
    return sys.monitoring.DISABLE


def reading_to_run():
    """Is a module being read in order to run it (by the import system or by assertion rewriting)?"""
    for count, step in enumerate(callers(4)):
        if step.f_globals.get("__name__") in ("importlib._bootstrap_external", "_frozen_importlib_external", "_pytest.assertion.rewrite"):
            return True
        if count == 5:
            return False
    return False


def on_open(path, *rest):
    if isinstance(path, (str, bytes)) and inside(os.fsdecode(path)) and not reading_to_run():
        note("O", inside(os.fsdecode(path)))


def on_listing(path=".", *rest):
    if isinstance(path, (str, bytes)) and inside(os.fsdecode(path)) is not None:
        note("D", inside(os.fsdecode(path)) or ".")


def on_attribute(owner, name, *rest):
    code = getattr(owner, "__code__", None) if name == "__code__" else None
    if hasattr(code, "co_qualname") and code.co_filename.startswith(REPO):
        note("C", label(code))


WATCHED = {
    "open": on_open,
    "object.__getattr__": on_attribute,
    "glob.glob": on_listing,
    "os.listdir": on_listing,
    "os.scandir": on_listing,
}
for starter in ("os.fork", "os.forkpty", "os.posix_spawn", "subprocess.Popen"):
    WATCHED[starter] = lambda *rest, starter=starter: note("P", starter)
nested = [False]


def audit(event, values):
    reaction = WATCHED.get(event)
    if reaction and not nested[0]:
        nested[0] = True
        try:
            reaction(*values)
        finally:
            nested[0] = False


def asking(function):
    """The same function, noting which file it is asked about."""
    def ask(path, *rest, **named):
        if isinstance(path, (str, bytes, os.PathLike)):
            target = inside(os.fsdecode(path))
            if target:
                note("E", target)
        return function(path, *rest, **named)
    return ask


def begin():
    send_to(os.environ["FACTS"])
    note("S", os.getpid())
    tool, watch = sys.monitoring.PROFILER_ID, sys.monitoring
    watch.use_tool_id(tool, "facts")
    watch.set_events(tool, watch.events.PY_START)
    watch.register_callback(tool, watch.events.PY_START, entered)
    sys.addaudithook(audit)
    for name in ("stat", "lstat", "access"):
        setattr(os, name, asking(getattr(os, name)))
