"""Compares two compiled versions of a file, code object by code object, without running either."""
import opcode
import types

OPS = opcode.opmap
LOAD, STORE, EXTEND = OPS["LOAD_CONST"], OPS["STORE_NAME"], OPS["EXTENDED_ARG"]
OWN_LOCALS = 0x02
# generator, coroutine, iterable coroutine, async generator: calling one of these runs nothing yet
DELAYED = 0x20 | 0x80 | 0x100 | 0x200
BOOKKEEPING = ("__firstlineno__", "__static_attributes__")


class NeedLoadRule(Exception):
    """The difference is not confined to bodies that only run when called."""


def key(code):
    """How the map names a code object of a file."""
    place = code.co_firstlineno
    return "%d:%s" % (place, code.co_qualname)


def position_constants(code):
    """Indexes of constants a class body stores only as its line number or attribute list."""
    if code.co_flags & OWN_LOCALS:
        return ()
    wide, loaded, uses, hidden = 0, None, {}, set()
    raw = code.co_code
    for at in range(0, len(raw), 2):
        operation, argument = raw[at], raw[at + 1] | wide
        wide = argument << 8 if operation == EXTEND else 0
        if operation == LOAD:
            uses[argument] = uses.get(argument, 0) + 1
            loaded = argument
        elif operation == STORE and loaded is not None and code.co_names[argument] in BOOKKEEPING:
            hidden.add(loaded)
        elif operation != EXTEND:
            loaded = None
    return {index for index in hidden if uses[index] == 1}


def exact(value):
    """Equal only for constants of the same type and spelling: 1, 1.0 and True differ, so do 0.0 and -0.0."""
    if type(value) is tuple:
        return tuple(map(exact, value))
    if type(value) is frozenset:
        return frozenset, frozenset(map(exact, value))
    return type(value), repr(value)


def own_part(code):
    """What the code object itself does, line numbers and inner code objects aside."""
    hidden = position_constants(code)
    constants = tuple(
        None if index in hidden else types.CodeType if type(value) is types.CodeType else exact(value)
        for index, value in enumerate(code.co_consts)
    )
    return (code.co_code, code.co_exceptiontable, code.co_names, code.co_varnames, code.co_cellvars, code.co_freevars, code.co_flags, constants) + binding(code)


def binding(code):
    """How a call binds its arguments, and what kind of call it is."""
    count = code.co_argcount + code.co_kwonlyargcount + bool(code.co_flags & 0x04) + bool(code.co_flags & 0x08)
    return (code.co_argcount, code.co_posonlyargcount, code.co_kwonlyargcount, code.co_flags & (0x0C | DELAYED), code.co_varnames[:count], code.co_freevars)


def inner(code):
    return [value for value in code.co_consts if type(value) is types.CodeType]


def changed(old, new):
    """[(old code, new code, outermost old, outermost new)] of changed bodies; [] if only line numbers differ."""
    found = []
    walk(old, new, None, found)
    return found


def walk(old, new, outermost, found):
    in_function = bool(old.co_flags & OWN_LOCALS)
    if outermost is None and in_function:
        outermost = (old, new)
    left, right = inner(old), inner(new)
    parts_line_up = [part.co_qualname for part in left] == [part.co_qualname for part in right]
    if own_part(old) != own_part(new) or not parts_line_up:
        if outermost is None:
            raise NeedLoadRule("module or class level")
        if in_function and binding(old) != binding(new):
            raise NeedLoadRule("the way it is called")
        # a class body inside a function runs with that function
        found.append((old, new) + outermost if in_function else outermost * 2)
    if parts_line_up:
        for before, after in zip(left, right):
            walk(before, after, outermost, found)
