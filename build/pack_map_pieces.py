"""pack_map_pieces.py <map folder> <base image digest> <facts folder>...   Inside the map image: facts -> map/.

Facts folders are named fork*, order*, reverse*. Only fork sessions say which modules a test file loads; the two
whole-suite sessions add what single tests ran or read.
"""
import ast
import hashlib
import json
import marshal
import pathlib
import re
import sqlite3
import sys
import warnings
import zlib

sys.path.insert(0, "/app")
import codes
import state

warnings.simplefilter("ignore")
SRC = pathlib.Path("/src")
PIN = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"
out, digest, folders = pathlib.Path(sys.argv[1]), sys.argv[2], [pathlib.Path(name) for name in sys.argv[3:]]
rows = json.loads(pathlib.Path("/tests.json").read_text(encoding="utf-8"))["tests"]
ids = [row["id"] for row in rows]
bit = {name: 1 << place for place, name in enumerate(ids)}
of_file = {}
for row in rows:
    of_file[row["file"]] = of_file.get(row["file"], 0) | bit[row["id"]]
everyone = sum(bit.values())

loaded, ran, opened, listed, session = {}, {}, {}, {}, set()
untraced = 0
problems = []
LOOKS_AT_CODE = re.compile(r"__code__|\bco_[a-z]+|\binspect\.|getsource|\bdis\.|__wrapped__")


def credit(table, names, mask):
    for name in names:
        table[name] = table.get(name, 0) | mask


seen = {}
for folder in folders:
    alone = folder.name.startswith("fork")
    for result in sorted(folder.glob("*.json")):
        facts = json.loads(result.read_text(encoding="utf-8", errors="surrogateescape"))
        session.update(facts["before_pytest"].get("O", ()))
        owners = of_file[result.stem.replace("~", "/")] if alone else 0
        for part in ("before_tests", "after"):
            # with one session for everything this belongs to no test in particular; fork sessions cover it
            common = facts[part]
            for letter in "FIC":
                credit(ran, common.get(letter, ()), owners)
            credit(loaded, common.get("M", ()), owners)
            credit(opened, common.get("O", ()), owners)
            credit(opened, common.get("E", ()), owners)
            credit(listed, common.get("D", ()), owners)
        for name, one in facts["tests"].items():
            mask = bit.get(name, 0)
            if not mask:
                continue
            seen.setdefault(folder.name, set()).add(name)
            if one["outcome"] != "passed":
                problems.append(f"{folder.name}: {name} {one['outcome']}")
            for letter in "FIC":
                credit(ran, one.get(letter, ()), mask)
            credit(opened, one.get("O", ()), mask)
            credit(opened, one.get("E", ()), mask)
            # a test that looks at the code of a function counts as reading the file
            if LOOKS_AT_CODE.search((SRC / name.split("::")[0]).read_text(encoding="utf-8")):
                credit(opened, {place.split(":")[0] for place in one.get("C", ())}, mask)
            credit(listed, one.get("D", ()), mask)
            # what runs while a module is imported belongs to every test of a file that imports it
            credit(loaded, one.get("M", ()), owners | mask)
            credit(ran, one.get("I", ()), owners | mask)
            if alone and one.get("P"):
                # any edit to a module its children import counts, whatever of it they ran
                credit(opened, one.get("M", ()), mask)
                if not one.get("S"):
                    untraced |= mask

for folder in folders:
    missing = set(ids) - seen.get(folder.name, set())
    if missing:
        problems.append(f"{folder.name}: {len(missing)} tests without a record, such as {sorted(missing)[0]}")
count = lambda mask: mask.bit_count()
helpers = {name: mask for name, mask in ran.items() if name.startswith("sqlglot/parser.py:") and name.split(":", 2)[2] in ("Parser._parse", "Parser.parse", "Parser._advance")}
for name, mask in helpers.items():
    print("helper", name, count(mask), "tests")
if len(helpers) != 3 or any(count(mask) < 0.8 * len(ids) for mask in helpers.values()):
    problems.append("core helpers are not recorded for nearly every test")
if not opened.get("tests/fixtures/jsonpath/cts.json", 0) & bit["tests/test_jsonpath.py::TestJsonpath::test_cts_file"]:
    problems.append("the opening of cts.json was not seen")
if not loaded.get("sqlglotc/setup.py", 0):
    problems.append("the run of sqlglotc/setup.py was not seen")
typing_test = bit["tests/test_typing.py::TestTyping::test_no_redundant_expression_metadata"]
if not opened.get("sqlglot/typing/duckdb.py", 0) & typing_test:
    problems.append("the reading of sqlglot/typing was not seen")

pieces, index = {}, {}
blobs = bytearray()


def keep(name, content):
    packed = zlib.compress(content, 9)
    index[name] = (len(blobs), len(packed))
    blobs.extend(packed)


def flatten(code):
    yield code
    for part in codes.inner(code):
        yield from flatten(part)


paths = sorted(p.relative_to(SRC).as_posix() for p in SRC.rglob("*") if p.is_file() and not p.is_symlink() and "__pycache__" not in p.parts)
trees = {}
for path in paths:
    if path.endswith(".py"):
        trees[path] = ast.parse((SRC / path).read_bytes(), path)
attributes = sorted(state.class_attribute_names([tree for path, tree in trees.items() if path.startswith(("sqlglot/", "tests/"))]))
keep("class attributes", json.dumps(attributes).encode())
hexed = lambda mask: format(mask, "x")
OURS = {"sqlglot", "sqlglotc", "tests", "sqlglot-integration-tests"}
writers = total = 0
for path in paths:
    content = (SRC / path).read_bytes()
    top, name = path.split("/")[0], path.split("/")[-1]
    python = path.endswith(".py")
    reasons = {
        "read before any test": path in session,
        "a test file without numbered tests": python and top == "tests" and "/" in path and name[:5] == "test_" and not {path} & (of_file.keys() | loaded.keys()),
        "not known to be read by a test": not python and path not in opened and top in OURS,
    }
    always = next((reason for reason, applies in reasons.items() if applies), "")
    facts = {"always": always, "opened": hexed(opened.get(path, 0)), "loaded": hexed(loaded.get(path, 0)), "codes": {}}
    if b"\0" not in content:
        keep("source:" + path, content)
    if path in trees:
        # the fixed image compiles the tree the same way the selector does
        code = compile(trees[path], path, "exec", dont_inherit=True)
        if codes.changed(compile(content, path, "exec", dont_inherit=True), code):
            problems.append(f"{path}: compiling the tree and the bytes differ")
        keep("code:" + path, marshal.dumps(code))
        bodies = [(state.first_line(node), node.end_lineno, node) for node in state.outermost_bodies(trees[path])]
        writing = {node for first, last, node in bodies if state.writes_state(node, frozenset(attributes))}
        # what a writer of state calls by name in the same file computes what is kept: it counts as a writer too
        named = {}
        for first, last, node in bodies:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                named.setdefault(node.name, set()).add(node)
        waiting = list(writing)
        while waiting:
            for call in ast.walk(waiting.pop()):
                match call:
                    case ast.Call(func=ast.Name(id=called)):
                        helpers_of = named.get(called, set()) - writing
                        writing |= helpers_of
                        waiting.extend(helpers_of)
        marked = [(first, last) for first, last, node in bodies if node in writing]
        for part in flatten(code):
            if part.co_flags & codes.OWN_LOCALS:
                name = codes.key(part)
                flag = any(first <= part.co_firstlineno <= last for first, last in marked)
                earlier = facts["codes"].get(name, (0, False))
                facts["codes"][name] = (ran.get(f"{path}:{name}", 0), flag or earlier[1])
                writers += flag
                total += 1
        facts["codes"] = {name: (hexed(mask), flag) for name, (mask, flag) in facts["codes"].items()}
    keep("facts:" + path, json.dumps(facts, separators=(",", ":")).encode())

known = {f"{path}:{name}" for path in trees for name in json.loads(zlib.decompress(bytes(blobs[index["facts:" + path][0]:sum(index["facts:" + path])])))["codes"]}
stray = [name for name in ran if name.split(":")[0] in trees and name not in known and not name.split(":", 2)[2].startswith("@")]
# class bodies are not functions: the load rule covers them
bodies_only = set()
for path, tree in trees.items():
    for part in flatten(compile(tree, path, "exec", dont_inherit=True)):
        if not part.co_flags & codes.OWN_LOCALS:
            bodies_only.add(f"{path}:{codes.key(part)}")
stray = [name for name in stray if name not in bodies_only]
if stray:
    problems.append(f"{len(stray)} recorded code objects are not in the compiled files, such as {stray[:3]}")
print(f"{len(paths)} files, {total} code objects, {writers} marked as keeping state, {count(untraced)} untraced tests, {len(listed)} listed folders")
for problem in problems[:20]:
    print("PROBLEM", problem)
if problems:
    sys.exit(1)

out.mkdir(exist_ok=True)
(out / "pieces.bin").write_bytes(bytes(blobs))
(out / "pieces.json").write_text(json.dumps({"format": 1, "python": sys.version, "tests": ids, "untraced": hexed(untraced), "files": paths, "pieces": index}, separators=(",", ":")), encoding="utf-8", newline="\n")
import importlib.metadata

sha = lambda path: hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
origin = {
    "base_image_digest": digest, "python_version": sys.version, "sqlite_version": sqlite3.sqlite_version,
    "pytest_version": importlib.metadata.version("pytest"), "sqlglot_commit": PIN, "requirements_lock_sha256": sha("/requirements.lock"),
    "map_builder": {f"build/{p.name}": sha(p) for p in sorted(pathlib.Path("/build").iterdir()) if p.is_file()} | {f"app/{n}": sha(f"/app/{n}") for n in ("codes.py", "state.py")},
    "map_files": {f"map/{n}": sha(out / n) for n in ("pieces.json", "pieces.bin")},
    "test_ids_count": len(ids), "test_ids_sha256": hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest(), "test_ids": ids,
}
(out / "MAP_ORIGIN.json").write_text(json.dumps(origin, indent=1) + "\n", encoding="utf-8", newline="\n")
print("map", sum(p.stat().st_size for p in out.iterdir()), "bytes")
