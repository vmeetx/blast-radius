"""One more kind of fact: V class|name, an argument an expression lacked, or had as an empty list, when it was validated.

Watches the start of the validation method, for every call, and looks at all declared names, required or not. The
method itself is untouched. A class made by a test counts as each sqlglot class it derives from.
"""
import sys

import process_facts

METHOD = "error_messages"
FILE = "/src/sqlglot/expressions/core.py"
told = {"sink": None, "pairs": set()}


def kinds(made):
    """The class itself if sqlglot has it at module level, otherwise all such classes it derives from."""
    lasting = [kind for kind in made.__mro__ if kind.__module__.startswith("sqlglot.") and "<locals>" not in kind.__qualname__]
    return lasting[:1] if lasting[:1] == [made] else lasting


def blank(value):
    return value is None or (isinstance(value, list) and not value)


def validated(code, offset):
    if code.co_name != METHOD or code.co_filename != FILE:
        return sys.monitoring.DISABLE
    subject = sys._getframe(1).f_locals["self"]
    if told["sink"] is not process_facts.sink:
        told["sink"], told["pairs"] = process_facts.sink, set()
    lacking = [name for name in subject.arg_types if blank(subject.args.get(name))]
    for kind in kinds(type(subject)) if lacking else ():
        for name in lacking:
            pair = f"{kind.__module__}.{kind.__qualname__}|{name}"
            if pair not in told["pairs"]:
                told["pairs"].add(pair)
                process_facts.note("V", pair)


def begin():
    tool, watch = sys.monitoring.OPTIMIZER_ID, sys.monitoring
    watch.use_tool_id(tool, "gaps")
    watch.set_events(tool, watch.events.PY_START)
    watch.register_callback(tool, watch.events.PY_START, validated)
