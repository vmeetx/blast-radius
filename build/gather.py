"""gather.py <folder> <fork|order|reverse> <hash seed>   In the map image: run the suite under observation.

fork starts one session per test file, several at a time; order and reverse start one session for everything.
"""
import json
import multiprocessing.pool
import os
import pathlib
import subprocess
import sys


def session(job):
    """Run one pytest session; give back the end of its output if it left no result."""
    folder, mode, seed, targets, title = job
    result = folder / (title.replace("/", "~") + ".json")
    settings = {"MODE": mode, "RESULT": str(result), "FACTS": f"{result}.start", "PYTHONHASHSEED": seed, "SKIP_INTEGRATION": "0"}
    settings |= {"PYTHONPATH": "/src:/build", "PYTHONDONTWRITEBYTECODE": "1", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
    command = [sys.executable, "-m", "pytest", "-q", "--tb=short", "-p", "session_facts", "-p", "no:cacheprovider", "-p", "no:xdist", *targets]
    done = subprocess.run(command, cwd="/src", env=os.environ | settings, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return title, "ok" if result.exists() else done.stdout[-3000:].decode(errors="replace")


if __name__ == "__main__":
    folder, mode, seed = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    weight = {}
    for row in json.loads(pathlib.Path("/tests.json").read_text(encoding="utf-8"))["tests"]:
        weight[row["file"]] = weight.get(row["file"], 0) + row["seconds"]
    heaviest_first = sorted(weight, key=lambda name: -weight[name])
    if mode == "fork":
        jobs = [(folder, mode, seed, [name], name) for name in heaviest_first]
    else:
        jobs = [(folder, mode, seed, sorted(weight), "suite")]
    with multiprocessing.pool.ThreadPool(int(os.environ.get("AT_ONCE", 3))) as crew:
        for title, remark in crew.imap_unordered(session, jobs):
            print(title, remark, flush=True)
