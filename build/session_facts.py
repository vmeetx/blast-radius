"""pytest plugin that separates the facts of each test.

MODE=fork: the session holds one test file. It is imported once, then every test runs in a fork of that state.
MODE=order / MODE=reverse: all tests in one process, in tests.json order or backwards.
Every memo that can be reached is emptied before each test, and every code object reports again.
What happens before the first test belongs to all tests of the session. RESULT names the output.
"""
import functools
import gc
import json
import os
import sys

import pytest
from _pytest import runner

import process_facts

MODE, RESULT = os.environ["MODE"], os.environ["RESULT"]
verdict = {"failed": set(), "skipped": set()}
collected = {"before_pytest": None, "before_tests": None, "tests": {}}
current = {"facts": os.environ["FACTS"]}


def take(facts):
    """Read a facts file into {letter: sorted values} and delete it."""
    by_letter = {}
    with open(facts, "rb") as stream:
        for row in stream.read().decode("utf-8", "surrogateescape").splitlines():
            by_letter.setdefault(row[0], set()).add(row[2:])
    os.remove(facts)
    return {letter: sorted(values) for letter, values in by_letter.items()}


def redirect(suffix):
    finished, current["facts"] = current["facts"], f"{RESULT}.{os.getpid()}.{suffix}"
    process_facts.send_to(current["facts"])
    return finished


def forget():
    """Empty functools caches and module- or class-level dictionaries whose name says cache."""
    for thing in gc.get_objects():
        if isinstance(thing, functools._lru_cache_wrapper):
            thing.cache_clear()
    for module in [m for n, m in sys.modules.items() if n.split(".")[0] == "sqlglot" and m]:
        for holder in [module] + [c for c in vars(module).values() if isinstance(c, type)]:
            for name, value in list(vars(holder).items()):
                if "cache" in name.lower() and isinstance(value, (dict, list, set)):
                    value.clear()


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart():
    collected["before_pytest"] = take(redirect("collect"))
    sys.monitoring.restart_events()


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(items):
    if MODE != "fork":
        with open("/tests.json", encoding="utf-8") as stream:
            place = {row["id"]: row["number"] for row in json.load(stream)["tests"]}
        # a test that is not numbered keeps running, after the numbered ones of its order
        items.sort(key=lambda item: place.get(item.nodeid, len(place)), reverse=MODE == "reverse")


def pytest_collectreport(report):
    if report.failed:
        verdict["failed"].add(report.nodeid)


def pytest_runtest_logreport(report):
    if report.failed:
        verdict["failed"].add(report.nodeid)
    if report.skipped and type(report) is runner.TestReport:
        verdict["skipped"].add(report.nodeid)


def in_fork(item, facts):
    child = os.fork()
    if not child:
        try:
            process_facts.send_to(facts)
            runner.runtestprotocol(item, nextitem=None)
            os._exit(1 if verdict["failed"] else 2 if verdict["skipped"] else 0)
        finally:
            os._exit(3)
    return ("passed", "failed", "skipped", "broken")[min(os.waitstatus_to_exitcode(os.waitpid(child, 0)[1]) % 256, 3)]


def in_this_process(item, nextitem, facts):
    process_facts.send_to(facts)
    runner.runtestprotocol(item, nextitem=nextitem)
    process_facts.send_to(current["facts"])
    return next((kind for kind in ("failed", "skipped") if item.nodeid in verdict[kind]), "passed")


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    if collected["before_tests"] is None:
        collected["before_tests"] = take(redirect("rest"))
    forget()
    facts = f"{RESULT}.{os.getpid()}.{len(collected['tests'])}"
    sys.monitoring.restart_events()
    outcome = in_fork(item, facts) if MODE == "fork" else in_this_process(item, nextitem, facts)
    collected["tests"][item.nodeid] = {"outcome": outcome, **take(facts)}
    return True


@pytest.hookimpl(trylast=True)
def pytest_unconfigure():
    if collected["tests"]:
        collected["after"] = take(current["facts"])
        process_facts.sink = None
        with open(RESULT + ".part", "w", encoding="utf-8", errors="surrogateescape") as stream:
            json.dump({**collected, **{kind: sorted(ids) for kind, ids in verdict.items()}}, stream)
        os.rename(RESULT + ".part", RESULT)
