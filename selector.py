"""Prints, for every commit, the tests it could break, spread over workers.

The map in map/ was recorded at the pinned commit. A test is left out only if its record shows that the
changed code or file played no part in it. Anything that cannot be read or matched runs every test.
"""
import json
import marshal
import os
import re
import select
import signal
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "app"))

import worker_piles  # noqa: E402

FORMAT = 1
LARGEST = 1000000
STALLED = 2
HELPERS = 5
NOT_PYTHON = (LookupError, MemoryError, RecursionError, SyntaxError, ValueError)
TEST_HEADER = re.compile(rb"^[ \t]*(?:(?:async[ \t]+)?def[ \t]+test|class[ \t]+Test)[^\r\n]*", re.M)
SETTINGS = {"conftest.py", "pyproject.toml", "setup.cfg", "pytest.ini", ".pytest.ini", "tox.ini", "sitecustomize.py",
            "usercustomize.py", ".gitattributes", ".gitmodules", "py.typed", "requirements.lock"}


class Everything(Exception):
    """This commit runs every test."""


class Record:
    """The map, read piece by piece."""

    def __init__(self, folder):
        pieces, listing = (open(os.path.join(folder, name), "rb") for name in ("pieces.bin", "pieces.json"))
        with listing:
            self.index = json.loads(listing.read())
        made_for = [self.index[part] for part in ("format", "python")]
        if made_for != [FORMAT, sys.version]:
            raise Everything("the map is for another program or Python")
        self.blobs = pieces

    def piece(self, name):
        offset, size = self.index["pieces"][name]
        self.blobs.seek(offset)
        return zlib.decompress(self.blobs.read(size))

    def facts(self, path):
        return json.loads(self.piece("facts:" + path))


class Chooser:
    def __init__(self, record, tests):
        self.record = record
        numbers = {test["id"]: test["number"] for test in tests}
        known = record.index["tests"]
        self.by_bit = [numbers.get(name) for name in known]
        self.unknown = {numbers[name] for name in numbers.keys() - set(known)}
        self.by_file = {name: set() for name in {test["file"] for test in tests}}
        for test in tests:
            self.by_file[test["file"]] |= {test["number"]}

    def numbers(self, mask):
        """The test numbers of a hexadecimal bit mask."""
        digits = bin(int(mask, 16))[:1:-1]
        return {self.by_bit[bit] for bit, digit in enumerate(digits) if digit == "1"} - {None}

    def commit(self, patch):
        """(tests to run, tests worth adding first when there is room)"""
        import strict_diff

        if len(patch) > LARGEST:
            raise Everything("too large to read")
        try:
            parts = strict_diff.sections(patch)
        except strict_diff.Unreadable as problem:
            raise Everything(problem) from None
        chosen, near = set(self.unknown), set()
        for path, hunks in parts:
            name = path.rsplit("/", 1)[-1]
            if name in SETTINGS or name.endswith(".pth") or path == "setup.py" or path not in self.record.index["files"]:
                raise Everything(f"{path}: settings or unknown")
            try:
                old = self.record.piece("source:" + path)
            except KeyError:
                raise Everything(f"{path}: not text at the pin") from None
            try:
                new = strict_diff.patched(old, hunks)
            except strict_diff.Unreadable as problem:
                raise Everything(f"{path}: {problem}") from None
            if sorted(TEST_HEADER.findall(old)) != sorted(TEST_HEADER.findall(new)):
                raise Everything(f"{path}: a test or test class was added or removed")
            facts = self.record.facts(path)
            if facts["always"] or b"\0" in new:
                raise Everything(f"{path}: {facts['always'] or 'binary'}")
            near |= self.numbers(facts["loaded"])
            chosen |= self.numbers(facts["opened"])
            if name.endswith(".py"):
                chosen |= self.python(path, new, facts)
        return chosen, near - chosen

    def python(self, path, new, facts):
        import codes

        numbered = self.by_file.get(path, set())
        untraced = self.numbers(self.record.index["untraced"])
        loaders = self.numbers(facts["loaded"]) | numbered | untraced
        tree, after = compiled(path, new)
        if after is None:
            return loaders
        before = marshal.loads(self.record.piece("code:" + path))
        try:
            differing = codes.changed(before, after)
        except codes.NeedLoadRule:
            return loaders
        if not differing:
            return numbered
        ran = numbered | untraced
        for mine, _theirs, _outer, enclosing_after in differing:
            entry = facts["codes"].get(codes.key(mine))
            if entry is None:
                raise Everything(f"{path}: {codes.key(mine)} is not in the map")
            mask, keeps_state = entry
            if keeps_state or self.keeps_state(tree, enclosing_after):
                return loaders
            ran = ran | self.numbers(mask)
        return ran

    def keeps_state(self, tree, code):
        """Does the new version of this outermost body write state that outlives a call?"""
        import ast

        import state

        names = frozenset(json.loads(self.record.piece("class attributes")))
        wanted = code.co_firstlineno
        bodies = [node for node in filter(state.is_body, ast.walk(tree)) if state.first_line(node) == wanted]
        return not bodies or any(state.writes_state(node, names) for node in bodies)


def compiled(path, source):
    """(tree, code) of a file's bytes, or (None, None) if it does not compile."""
    import ast
    import warnings

    warnings.simplefilter("ignore")
    try:
        tree = ast.parse(source, path)
        return tree, compile(tree, path, "exec", dont_inherit=True)
    except NOT_PYTHON:
        return None, None


def arrange(chosen, near, length, file_of):
    piles, totals = worker_piles.cheapest(chosen, length)
    if not piles:
        return []
    touched = {file_of[number] for number in chosen}

    def closeness(number):
        return (0 if number in near else 1 if file_of[number] in touched else 2, length[number], number)

    return worker_piles.top_up(piles, totals, sorted(length.keys() - chosen, key=closeness), length)


def stalled(signum, frame):
    raise Everything("took too long")


def line(name, workers):
    return json.dumps({"commit": name[:-len(".patch")], "workers": workers}) + "\n"


def helped(names, decide, full):
    """The lines a forked helper wrote for these commits, in order: fewer than asked if it was killed."""
    source, sink = os.pipe()
    sys.stderr.flush()
    helper = os.fork()
    if not helper:
        try:
            os.close(source)
            signal.signal(signal.SIGALRM, stalled)
            for name in names:
                # the alarm is for a stall: an ordinary commit takes a small part of it
                signal.alarm(STALLED)
                # this one ends the helper, should a stall be deaf to the alarm
                signal.setitimer(signal.ITIMER_VIRTUAL, STALLED * 3)
                try:
                    workers = decide(name)
                    signal.alarm(0)
                except Exception as problem:
                    signal.alarm(0)
                    workers = full
                    print(name, "everything:", problem, file=sys.stderr)
                with_room = line(name, workers).encode()
                while with_room:
                    with_room = with_room[os.write(sink, with_room):]
            os._exit(0)
        finally:
            os._exit(1)
    os.close(sink)
    told, piece = b"", None
    # the parent watches too: a helper that says nothing for this long is ended, whatever it is stuck on
    while piece != b"" and any(select.select([source], [], [], STALLED * 3)):
        piece = os.read(source, 1 << 16)
        told += piece
    os.kill(helper, signal.SIGKILL)
    os.close(source)
    os.waitpid(helper, 0)
    # the last piece is cut short if the helper died while writing it
    return [part for part in told.decode(errors="replace").splitlines(keepends=True) if part.endswith("\n")]


def numbered_tests(data, record):
    """tests.json; if it cannot be read, the tests of the map in their order, all equally long."""
    try:
        source = os.path.join(data, "tests.json")
        with open(source, encoding="utf-8") as stream:
            listed = json.load(stream)["tests"]
        return [{part: test[part] for part in ("id", "number", "file")} | {"seconds": float(test["seconds"])} for test in listed]
    except Exception as problem:
        print("no usable tests.json:", repr(problem), file=sys.stderr)
    from_the_map = record.index["tests"] if record else []
    return [dict(id=name, number=place, file=name.partition("::")[0], seconds=1.0) for place, name in enumerate(from_the_map)]


def main():
    data = os.environ.get("BLAST_RADIUS_DATA") or "/data"
    record = chooser = full = None
    try:
        record = Record(os.path.join(HERE, "map"))
    except Exception as problem:
        print("no usable map:", repr(problem), file=sys.stderr)
    tests = numbered_tests(data, record)
    length, file_of = {}, {}
    for test in tests:
        place = test["number"]
        file_of[place], length[place] = test["file"], int(test["seconds"] * 1000 + 0.5)
    try:
        chooser = Chooser(record, tests) if record else None
    except Exception as problem:
        print("no usable map:", repr(problem), file=sys.stderr)
    folder = os.path.join(data, "commits")
    try:
        names = sorted(name for name in os.listdir(folder) if name.endswith(".patch") and name != ".patch")
    except OSError as problem:
        print("no commits:", problem, file=sys.stderr)
        names = []
    full = worker_piles.cheapest(length, length)[0]

    def decide(name):
        if not chooser:
            return full
        with open(os.path.join(folder, name), "rb") as stream:
            chosen, near = chooser.commit(stream.read())
        print(name, len(chosen), "chosen", file=sys.stderr)
        return arrange(chosen, near, length, file_of)

    lost = 0
    while names:
        lines = helped(names, decide, full) if lost < HELPERS else []
        # a helper that died left the next commit without a line: that one runs everything, the rest get a new helper
        # (after a few lost helpers, the rest run everything)
        if len(lines) < len(names):
            lost += 1
            lines.append(line(names[len(lines)], full))
        sys.stdout.writelines(lines)
        sys.stdout.flush()
        names = names[len(lines):]


if __name__ == "__main__":
    main()
