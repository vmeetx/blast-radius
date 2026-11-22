"""Run every test on every commit, split over the number of workers that costs least.

A commit costs its busiest worker plus 2 seconds for every worker, so the split
is computed once and is the same for every commit.
"""

import json
import os
import sys

MAX_WORKERS = 8
WORKER_MS = 2000


def log(message):
    print(message, file=sys.stderr)


def milliseconds(test):
    return int(test["seconds"] * 1000 + 0.5)


def split(tests, worker_count):
    """Each test onto the worker with the least to do so far, the first such worker on a tie."""
    workers = [[] for _ in range(worker_count)]
    loads = [0] * worker_count
    for test in tests:
        lightest = loads.index(min(loads))
        workers[lightest].append(test["number"])
        loads[lightest] += milliseconds(test)
    return workers, max(loads) + WORKER_MS * worker_count


def best_split(tests):
    """The cheapest split over 1 to 8 workers. min() keeps the first, so a tie goes to fewer workers."""
    longest_first = sorted(tests, key=lambda test: (-milliseconds(test), test["number"]))
    candidates = [split(longest_first, count) for count in range(1, MAX_WORKERS + 1)]
    workers, cost = min(candidates, key=lambda candidate: candidate[1])
    log(f"{len(tests)} tests on {len(workers)} workers, {cost} ms a commit")
    return [worker for worker in workers if worker]


def one_worker(tests):
    """Every test on one worker: the answer when anything goes wrong."""
    return [[test["number"] for test in tests]] if tests else []


def main():
    data = os.environ.get("BLAST_RADIUS_DATA") or "/data"
    with open(os.path.join(data, "tests.json"), encoding="utf-8") as file:
        tests = json.load(file)["tests"]
    try:
        workers = best_split(tests)
    except Exception as error:
        log(f"split failed, using one worker: {error!r}")
        workers = one_worker(tests)
    suffix = ".patch"
    names = os.listdir(os.path.join(data, "commits"))
    for commit in sorted(name[: -len(suffix)] for name in names if name.endswith(suffix)):
        try:
            line = json.dumps({"commit": commit, "workers": workers}, separators=(",", ":"))
        except Exception as error:
            log(f"{commit}: using one worker: {error!r}")
            line = json.dumps({"commit": commit, "workers": one_worker(tests)})
        sys.stdout.write(line + "\n")


if __name__ == "__main__":
    main()
