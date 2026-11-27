# blast-radius

**Run only the Python tests a change could have affected, and know why the rest were skipped.** blast-radius traces every test once against a base commit. When a code change comes in, it compiles the old and new files and compares them function by function. It then picks only the tests that actually ran something that changed, and splits them across parallel workers so the batch finishes soonest. It is built for workloads that make many changes against one fixed base: AI coding agents working in a checkout, mutation testing, and replaying commits for research.

Built for RWX's Blast Radius track at Builders Buildathon 2026. The task was to choose which of [sqlglot](https://github.com/tobymao/sqlglot)'s 1,620 tests to run for each code change, without missing a failing test. This repository keeps that entry's full history and grows it into a standalone tool. MIT licensed.

**Limits:**
- The map must be rebuilt for each base commit, and a change must apply exactly to that base.
- The map only works with the exact Python build it was recorded on (3.13).
- It runs on Linux and macOS only.
- Skipping a test is safe only if your tests are deterministic and don't depend on state left by other tests.

## Results (sqlglot at `eb11aec`, 1,620 tests)

| | All tests | blast-radius |
|---|---|---|
| Simulated test time, 30 sample changes | 1,104.5 s | **188.0 s (83% less)** |
| Missed failures, 30 sample changes | 0 | **0** |
| Missed failures, about 130 labelled changes | n/a | **0** (miss rate under about 2.5% per change at 95% confidence, by the rule of three) |

- **Simulated time:** for each change, the busiest worker's recorded test seconds plus 2 s per worker, as defined in [SCORING.md](SCORING.md). It is not wall-clock time.
- **Labelled changes:** real upstream commits, the samples, and generated mutants.
- **Selector cost:** about 2 s of CPU for a batch.
- **Robustness:** it always printed a valid answer under injected crashes, hangs, memory exhaustion, truncated output and stalled child processes.

To reproduce: `make sample` (needs Docker, make and Python 3.9+).

## How it decides

- **The map (built once per base commit).** Each test runs in its own forked process, traced with `sys.monitoring`. The map records, per test:
  - the code objects it entered;
  - the files it opened, listed or checked for;
  - the modules its test file loads;
  - whether it started child processes.
- **Function-body changes.** If only function bodies changed, the tests that ran those bodies are chosen. Line-number shifts change nothing.
- **Module- or class-level changes.** The tests that load that module are chosen. A changed body that writes lasting state, or a file that no longer compiles, chooses every test of every test file that loads the module.
- **Flag-only changes (sqlglot-specific).** If a change only flips true/false entries in sqlglot's `arg_types` tables, the patched package is imported in a forked child process.
  - The child has one 4 s deadline. Only the tests that validated a class without one of the changed arguments are chosen.
  - A child that dies or is late turns this path off for the rest of the batch, and no child starts after 90 s.
  - **This path runs the patched code.**
- **Anything uncertain runs everything:** settings files, renames, binary files, added or removed tests, patches that don't apply exactly, and anything the map doesn't cover.

`app/state.py` decides what writes lasting state, and errs towards yes.

## Use it

```sh
docker build -t blast-radius .
# data/commits/*.patch: unified diffs against the mapped base
# data/tests.json: {"tests": [{"id": ..., "number": ..., "file": ..., "seconds": ...}]}
docker run --rm --network none -v "$PWD/data:/data:ro" blast-radius
```

The output is one JSON line per change: `{"commit": "<name>", "workers": [[test numbers], ...]}`, with up to 8 workers. Lines are printed as soon as each change is decided. `BLAST_RADIUS_DATA` changes the data folder.

**Rebuilding the map:**
1. Build `build/Dockerfile`.
2. Run `build/gather.py` in modes `fork`, `order` and `reverse`.
3. Run `build/pack_map_pieces.py`.
4. Run `build/pack_gaps.py` with the fork passes of hash seeds 0 and 1.

`map/MAP_ORIGIN.json` records what the map was built from.

## Repository layout

| Path | What it is |
|---|---|
| `selector.py`, `app/` | The selector: diff reading, code-object comparison, state rules, the flag gate, worker packing |
| `build/` | The map builder: the per-test tracer, session runner and packers |
| `map/` | The example map for sqlglot at `eb11aec` |
| `Makefile`, `score.py`, `SCORING.md`, `sample/` | The track's benchmark kit: 30 sample changes with known failing tests, and the scorer |
| `docs/POSITIONING.md` | Who needs a tool like this and how it compares with the alternatives, with sources |
| `docs/RESEARCH_PROMPT*.md` | The research prompt behind that document, and the critical review that rewrote it |

## Roadmap (what blocks general use, most important first)

1. A pytest node-id interface: accept a diff and print node ids, with no numbered test list needed.
2. A generic map builder for any repository, with the sqlglot flag gate as an optional plugin.
3. An added test selects itself plus the normal rules, instead of everything.
4. Base drift: handle a diff made against a newer commit, or update the map incrementally.
5. Maps and measurements for more repositories, including one with a heavy shared core.
6. Wall-clock and CPU comparisons against pytest-testmon and coverage-based selection.

## How it compares

- **[pytest-testmon](https://pypi.org/project/pytest-testmon):** coverage blocks with an incremental local database. It is better for a developer's local loop on a moving branch.
- **Hosted test impact analysis services:** select by covered files and history, need a network connection, and by their own documentation can skip tests when data files or dependencies change.
- **Predictive (ML) selection:** trades a known share of missed failures for speed.
- **Line-level coverage selection:** a Python study found it missed 16–24% of faults.

blast-radius sits between file-level and line-level selection: safe under its assumptions, finer than files, and offline. [docs/POSITIONING.md](docs/POSITIONING.md) has the details and sources.
