"""Patches that only flip true/false flags in the requirement tables of expression classes.

The flags have one effect: class creation keeps the names whose flag is true, and validation complains about a kept
name that an instance lacks. The map knows which (class, name) each test lacked during some validation. What the
flips do to the classes is measured: the patched package is imported in a forked process and asked. Any doubt gives
None, and the caller's answer stands.
"""
import ast
import hashlib
import importlib.machinery
import json
import marshal
import os
import select
import signal
import sys

PIN = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"
TABLE = "arg_types"
BASE = ("sqlglot.expressions.core", "Expr")
SECONDS = 4
slow = []


class Shelf:
    """Imports the package from the map, with some files replaced."""

    def __init__(self, record, replaced):
        self.record, self.replaced = record, replaced
        self.places = {place for place in record.index["files"] if place.startswith("sqlglot/")}

    def find_spec(self, name, path=None, target=None):
        stem = name.replace(".", "/")
        for tail in ("/__init__.py", ".py"):
            if stem + tail in self.places:
                found = importlib.machinery.ModuleSpec(name, self, origin="/src/" + stem + tail, is_package=tail[0] == "/")
                found.has_location = True
                return found

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        place = module.__spec__.origin[len("/src/"):]
        if place in self.replaced:
            code = compile(self.replaced[place], place, "exec", dont_inherit=True)
        else:
            code = marshal.loads(self.record.piece("code:" + place))
        exec(code, module.__dict__)


def describe(modules):
    """{class: [names in order, required names]} of every expression class once these modules are imported."""
    for name in modules:
        __import__(name)
    waiting, table = [getattr(sys.modules[BASE[0]], BASE[1])], {}
    while waiting:
        kind = waiting.pop()
        title = f"{kind.__module__}.{kind.__qualname__}"
        entry = [list(getattr(kind, TABLE)), sorted(kind.required_args)]
        if table.setdefault(title, entry) != entry:
            raise ValueError(f"two classes {title}")
        waiting += type.__subclasses__(kind)
    return table


def digest(table):
    return hashlib.sha256(json.dumps(table, sort_keys=True).encode()).hexdigest()


def measured(record, replaced, modules):
    """What describe() says of the patched package, or None if it cannot be imported in time."""
    source, sink = os.pipe()
    child = os.fork()
    if not child:
        try:
            # whatever happens here ends here
            signal.setitimer(signal.ITIMER_VIRTUAL, 0)
            signal.signal(signal.SIGALRM, signal.SIG_DFL)
            signal.alarm(SECONDS + 1)
            nowhere = os.open(os.devnull, os.O_RDWR)
            for stream in range(3):
                os.dup2(nowhere, stream)
            sys.meta_path.insert(0, Shelf(record, replaced))
            with open(sink, "w", encoding="utf-8") as told:
                json.dump(describe(modules), told)
            os._exit(0)
        finally:
            os._exit(1)
    os.close(sink)
    heard, piece = b"", None
    # the alarm for a stalled commit waits; the parent process still watches
    left = signal.alarm(0)
    try:
        while piece != b"":
            ready, _, _ = select.select([source], [], [], SECONDS)
            if not ready:
                # not again in this batch
                print("the child import took too long:", *replaced, file=sys.stderr)
                slow.append(True)
                return None
            piece = os.read(source, 1 << 20)
            heard += piece
    finally:
        os.kill(child, signal.SIGKILL)
        _, status = os.waitpid(child, 0)
        os.close(source)
        signal.alarm(left)
    return json.loads(heard) if heard.endswith(b"}") else None


def without_flags(tree, module, classes):
    """The tree as text, true/false values of requirement tables of known classes blanked."""
    for holder in tree.body:
        if isinstance(holder, ast.ClassDef) and f"{module}.{holder.name}" in classes:
            for statement in holder.body:
                match statement:
                    case ast.Assign(targets=[ast.Name(id=name)], value=ast.Dict(keys=keys, values=values)) if name == TABLE:
                        pass
                    case ast.AnnAssign(target=ast.Name(id=name), value=ast.Dict(keys=keys, values=values)) if name == TABLE:
                        pass
                    case _:
                        continue
                for label, flag in zip(keys, values):
                    if label is not None and isinstance(flag, ast.Constant) and type(flag.value) is bool:
                        flag.value = "flag"
    return ast.dump(tree)


def only_flips(path, old, new, classes):
    module = path.removesuffix(".py").removesuffix("/__init__").replace("/", ".")
    return without_flags(ast.parse(old), module, classes) == without_flags(ast.parse(new), module, classes)


class Gate:
    """The answers for one patch; files is {path: (old bytes, new bytes)} of its Python files."""

    def __init__(self, record, files):
        self.record, self.files, self.known, self.mask = record, files, None, None
        if record.index["pieces"].get("requirements") is None:
            return
        known = json.loads(record.piece("requirements"))
        if known["pin"] == PIN and known["hash"] == digest(known["classes"]):
            self.known = known

    def observers(self, path):
        """Mask of the tests that may notice this file's change, or None if it is not for us to say."""
        if slow or not self.known or not path.startswith("sqlglot/"):
            return None
        old, new = self.files[path]
        if not only_flips(path, old, new, self.known["classes"]):
            return None
        if self.mask is None:
            self.mask = self.measure()
        if self.mask < 0:
            return None
        return self.mask | int(json.loads(self.record.piece("gaps"))["readers"].get(path, "0"), 16)

    def measure(self):
        """Tests that met a changed pair, or -1."""
        before = self.known["classes"]
        replaced = {path: new for path, (_, new) in self.files.items()}
        after = measured(self.record, replaced, self.known["modules"])
        if after is None or after.keys() != before.keys() or any(after[kind][0] != before[kind][0] for kind in before):
            return -1
        gaps = json.loads(self.record.piece("gaps"))
        mask = int(gaps["always"], 16)
        for kind, (_, needed) in before.items():
            for name in set(needed) ^ set(after[kind][1]):
                mask |= int(gaps["pairs"].get(f"{kind}|{name}", "0"), 16)
        return mask
