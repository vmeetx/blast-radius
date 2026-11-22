"""pack_gaps.py <map folder> <facts folder> <facts folder>   After pack_map_pieces.py, in the map image: adds gaps and requirements.

The two folders are fork passes under two hash seeds; a test's gaps are the union. Says which tests differ.
"""
import dis
import hashlib
import json
import marshal
import os
import pathlib
import re
import subprocess
import sys
import zlib

sys.path.insert(0, "/app")
import codes
import requirement_flags as flags

out, passes = pathlib.Path(sys.argv[1]), [pathlib.Path(name) for name in sys.argv[2:]]
index = json.loads((out / "pieces.json").read_text(encoding="utf-8"))
blobs = bytearray((out / "pieces.bin").read_bytes())
bit = {name: 1 << place for place, name in enumerate(index["tests"])}
INSPECTS = re.compile(r"__code__|\bco_[a-z]+|\binspect\.|getsource|\bdis\.|__wrapped__")
WATCHED = {flags.TABLE, "required_args"}


def inflate(name):
    offset, size = index["pieces"][name]
    return zlib.decompress(bytes(blobs[offset:offset + size]))


def add(name, value):
    packed = zlib.compress(json.dumps(value, separators=(",", ":")).encode(), 9)
    index["pieces"][name] = [len(blobs), len(packed)]
    blobs.extend(packed)


readers = {}


def looked_at(facts, letters="OE"):
    """Files whose text or existence (or function code) was looked at; importing one is not looking."""
    return {value.split(":")[0] for letter in letters for value in facts.get(letter, ())}


def letters_for(test_file):
    """Function code counts for tests that look at code, as in pack_map_pieces.py."""
    return "OEC" if INSPECTS.search(pathlib.Path("/src", test_file).read_text(encoding="utf-8")) else "OE"


def one_pass(folder):
    """{test: its gaps, those of the shared part of its session included}, and tests without a sound record."""
    gaps, sound = {}, set()
    for result in sorted(folder.glob("*.json")):
        facts = json.loads(result.read_text(encoding="utf-8", errors="surrogateescape"))
        shared = set().union(*(facts[part].get("V", ()) for part in ("before_pytest", "before_tests", "after")))
        seen = set().union(*(looked_at(facts[part]) for part in ("before_tests", "after")))
        for name, one in facts["tests"].items():
            for place in seen | looked_at(one, letters_for(name.split("::")[0])):
                if place.startswith("sqlglot/"):
                    readers[place] = readers.get(place, 0) | bit.get(name, 0)
            gaps[name] = shared.union(one.get("V", ()))
            if one["outcome"] == "passed" and (not one.get("P") or one.get("S")):
                sound.add(name)
    return gaps, bit.keys() - sound


first, second = map(one_pass, passes)
unlike = sorted(name for name in bit if first[0].get(name) != second[0].get(name))
print(len(unlike), "tests differ between the two seeds", unlike[:10])
always = sum(bit[name] for name in first[1] | second[1])
print(always.bit_count(), "tests without a sound record")
pairs = {}
for gaps, _ in (first, second):
    for name, met in gaps.items():
        for pair in met:
            pairs[pair] = pairs.get(pair, 0) | bit.get(name, 0)


def nested(code):
    yield code
    for value in code.co_consts:
        if hasattr(value, "co_code"):
            yield from nested(value)


# tests whose own code looks at a table or a required set
for place in index["files"]:
    if place.startswith("tests/") and "code:" + place in index["pieces"]:
        facts = json.loads(inflate("facts:" + place))
        for code in nested(marshal.loads(inflate("code:" + place))):
            reads = {step.argval for step in dis.get_instructions(code) if step.opname in ("LOAD_ATTR", "LOAD_SUPER_ATTR")}
            if WATCHED & (reads | {value for value in code.co_consts if isinstance(value, str)}):
                mask = facts["codes"][codes.key(code)][0] if code.co_flags & codes.OWN_LOCALS else facts["loaded"]
                print("looks at a table:", place, code.co_qualname, int(mask, 16).bit_count(), "tests")
                always |= int(mask, 16)

modules = sorted(
    place.removesuffix(".py").removesuffix("/__init__").replace("/", ".")
    for place in index["files"] if place.startswith("sqlglot/") and place.endswith(".py") and not place.endswith("__main__.py")
)
# the same question to the tree the tests ran on, with every package installed, and to the map in a bare interpreter
ASK = "import json, sys; sys.path.insert(0, '/app'); import requirement_flags as f\n"
TREE = ASK + "t = f.describe(json.load(sys.stdin)); import sqlglot.expressions.core as c; assert c.__file__.endswith('.py'); print(json.dumps(t))"
LEFT = ASK + "\n".join((
    "good = []", "for m in json.load(sys.stdin):", "    try:", "        __import__(m); good.append(m)", "    except ImportError as e:", "        print(m, repr(e), file=sys.stderr)", "print(json.dumps(good))"))
quiet = dict(os.environ, PYTHONPATH="/src", PYTHONDONTWRITEBYTECODE="1")


def ask(program, options, given):
    return json.loads(subprocess.run([sys.executable, *options, "-c", program], input=json.dumps(given), stdout=subprocess.PIPE, text=True, env=quiet, check=True).stdout)


bare = ask("import sys; sys.path.insert(0, '/src')\n" + LEFT, ["-S", "-E"], modules)
print(len(modules), "modules,", len(bare), "import without other packages")
classes = ask(TREE, [], bare)
everything = ask(TREE, [], ask(LEFT, [], modules))
if classes != everything:
    sys.exit("PROBLEM other modules change the classes")


class Map:
    def __init__(self):
        self.index = index

    def piece(self, name):
        return inflate(name)


flags.SECONDS = 60
if flags.measured(Map(), {}, bare) != classes:
    sys.exit("PROBLEM the map's own copy of the package gives other classes")
strangers = sorted({pair.split("|")[0] for pair in pairs} - classes.keys())
print("tests that look at files of the package, most per file:", sorted(((mask.bit_count(), place) for place, mask in readers.items()), reverse=True)[:4])
print(len(classes), "classes,", len(pairs), "pairs met, by classes unknown:", strangers[:10])
if strangers:
    sys.exit("PROBLEM gaps of classes that are not in the snapshot")
add("gaps", {"always": format(always, "x"), "readers": {place: format(mask, "x") for place, mask in sorted(readers.items())}, "pairs": {pair: format(mask, "x") for pair, mask in sorted(pairs.items())}})
add("requirements", {"pin": flags.PIN, "hash": flags.digest(classes), "modules": bare, "classes": classes})

(out / "pieces.bin").write_bytes(bytes(blobs))
(out / "pieces.json").write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8", newline="\n")
origin = json.loads((out / "MAP_ORIGIN.json").read_text(encoding="utf-8"))
for name in origin["map_files"]:
    origin["map_files"][name] = hashlib.sha256((out / name.removeprefix("map/")).read_bytes()).hexdigest()
origin["map_builder"]["app/requirement_flags.py"] = hashlib.sha256(pathlib.Path(flags.__file__).read_bytes()).hexdigest()
(out / "MAP_ORIGIN.json").write_text(json.dumps(origin, indent=1) + "\n", encoding="utf-8", newline="\n")
print("map", sum(part.stat().st_size for part in out.iterdir()), "bytes")
