# Hamilton review of RESEARCH_PROMPT.md

Reviewer stance: hostile, no stake in the tool. Evidence base: `RESEARCH_PROMPT.md`; `v16/` at 24aaf06 (`selector.py`, `README.md`, `app/`, `build/`, `map/` listing); my earlier read-only audit of v1.5; the project's own notes. No web searches were made. Anything I say about other tools comes from memory and is marked **[memory, unverified]**; the rewritten prompt makes the researcher verify it.

Part 1 (steelman) is short on purpose. The prompt is well structured, and its best features are worth keeping: it asks for the strongest "nobody needs this" argument, it demands [fact]/[inference] labels, and it has a search budget. Everything else below is attack.

---

## 1. Claims that are overstated or unsupported

Line numbers are those of `RESEARCH_PROMPT.md`.

| # | Quote | Problem | Correction |
|---|---|---|---|
| 1 | L5 "leaves a test out only when a recorded fact **proves** the change could not affect it" | A trace of one execution is not a proof. The soundness rests on assumptions the prompt never states: tests are deterministic and order-independent, they read no unrecorded environment (time, env vars, network, randomness), C extensions are absent, and the AST rule for "writes lasting state" is right. `app/state.py` itself says it "errs towards yes", which is a heuristic, not a proof. | "Leaves a test out only when the recorded trace of that test shows it never entered the changed code, under stated assumptions (list them). Unsound cases that remain: …" |
| 2 | L29 "no statistical exclusion, so **no missed failures by construction**" | Contradicted by the same document's own measurement, which is empirical (0 misses in ~120 commits). "By construction" is true only relative to the assumptions in #1. The tool also contains non-trace rules: a regex test-header check (`selector.py:27,96`), a hard-coded settings-file list (`:28-29`), an alarm-based time-out that falls back to "everything" (`:206-211`), and a forked child import for the flag extension. | Say "sound relative to the recorded trace and these assumptions; no misses in N labelled commits (95% upper bound on miss rate ≈ 3/N by the rule of three, so about 2.5% per commit at N=120)". |
| 3 | L9 "Code that writes lasting state, settings files, new or deleted tests … **all run everything**" | Wrong for the first item. README:79 says a changed body that writes lasting state, or a file that no longer compiles, chooses every test of every test file that loads the module. That is a broad set, not everything, and it is only as good as the "loaded" attribution. | State the real fallback rule for each case in a table: everything / loaders / own tests. |
| 4 | L8 "records … files it opened **or stat'ed**" | True, but narrower than it sounds. `process_facts.py:129` hooks `stat`, `lstat`, `access`. It records presence of path attempts, not file *content dependence* through every route (mmap, `os.scandir` entries, `importlib.resources`). | Keep, but list what is not hooked. |
| 5 | L8 "It runs under **two hash seeds** to catch nondeterminism" | Read as the whole map being cross-checked. README:84 and `pack_gaps.py:3` say two seeds are used only for the requirement-flag gap facts. The main map is one fork pass per seed given to `gather.py`; no source says the whole map is compared across seeds. | "Gap facts for the flag extension are recorded under two hash seeds; the main map is one pass per mode." |
| 6 | L16 "**Python 3.12+**" | The map holds marshalled code objects and refuses to load unless `sys.version` is identical (`selector.py:43-45`). The comparison also relies on 3.13 bookkeeping constants (`__firstlineno__`, `__static_attributes__`, `codes.py`). The real requirement is "the exact interpreter build the map was made with, 3.13 line". | "Map valid only for the exact Python build it was recorded on; 3.13-specific." |
| 7 | L5, L49 "**Offline, single binary**" | It is a directory of Python scripts plus a 4.9 MB `pieces.bin` and 168 KB `pieces.json` (`map/`), not a binary. It also uses `os.fork` and `signal.alarm`, so it is Linux/macOS only, and the builder needs `fork`. | "Offline Python program with a version-locked data directory; POSIX only." |
| 8 | L11-12 "Measured on sqlglot (about 1,600 tests, **37 s per full run**)" | The test recordings sum to 103.0 s over 1,620 tests (`tests.json`), and the slowest test alone is 28.8 s. 37 s is the *parallel critical path* with four workers plus start costs (28.8 + 2×4 ≈ 36.8), not a full run. A full serial run is ~103 s on the recording machine. | Give both: 103 s serial, ~37 s four-way, and note one test sets the floor. |
| 9 | L12 "188 s versus about **1,600 s** for running everything" | The only run-everything figures I can reproduce are 36.8 s per commit (≈1,104 s over 30) and 1,210.47 s for the unchanged starter. "1,600" matches the number of tests, not seconds, and looks like a unit slip. The 188 s figure is not reproducible from the files I read. It is also a cost-formula number (it includes a fixed 2 s per worker and the recorded durations of selected tests), not measured wall-clock time or CPU. | Replace with measured wall-clock and CPU on a stated machine, same patches, both arms. Say what formula produced each number. |
| 10 | L13 "About 90 labelled real and mutant commits: 0 misses" | The mutants were made by the team that built the selector, the labels by the team's own harness (one process, one order, one timeout, one hash seed). Real commits are only those that apply cleanly to the pinned base (the project's own notes say 40 of 65). The sample commits were used while developing. One repository only. | Say "0 misses on N commits from one repository; selection effects: (a) applies cleanly, (b) author-generated mutants, (c) author-chosen rules; held-out share = ?". |
| 11 | L14 "The selector itself adds about **2 s of CPU**" | Not verifiable from the code, and it moves: the v1.6 extension forks a child that imports the patched package, and the cost scales with number of changed files, the map size and the time-outs (STALLED = 2 s per commit, `selector.py:23`). | Report CPU per commit at p50/p95 and for a 10× larger map. |
| 12 | L15 "Fault-injected (crash, hang, out of memory, half output), it **always** prints a valid answer" | "Always" is wider than the tests. If the parent is OOM-killed, nothing is printed. If the commit folder is unreadable, the loop prints no lines (`selector.py:271-275`). The helper limit means that after `HELPERS = 5` lost helpers, the rest of the batch runs everything (`:288-294`), which is valid but is the point at which the claimed benefit disappears. | "In the injected cases tried, output stayed valid; degraded runs fall back to running everything." |
| 13 | L32 "Map rebuild cost: **one** full traced run per base commit" | `gather.py` has three modes (fork, order, reverse) and the gap facts need fork passes under two seeds (README:84). That is at least four traced passes, and the per-file fork sessions add start-up cost per file. | "At least four traced passes of the suite per base commit." Give the measured wall time and CPU. |
| 14 | L5 "given a code change (a unified diff) to a Python project" | The selector accepts only a diff that applies **exactly** to the mapped base commit: hunk lines must match at the stated line with zero offset (`strict_diff.patched`; README:82 "any patch that does not apply exactly run every test"). Real pull requests are made against a moving main branch. | State this limit up front. It is the biggest practical barrier (see §4). |
| 15 | L16 "map builder carries sqlglot-specific paths and a sqlglot-specific semantic gate" | Understated. The load rule also names the dialect registry (README:79), the fixed list of known paths, the pin, and the flag gate (`requirement_flags.py`) are tied to sqlglot's `arg_types`. The prompt treats this as a detail; it decides whether any other repository can use the tool at all. | Say how many sqlglot-specific parts there are, and that no second repository has been tried. |
| 16 | L9 "select little or nothing" for comment/format edits | A comment-only edit to a *test file* selects every test in that file (`selector.py:128-129`, `return numbered`). Also new or removed tests send the whole patch to "everything". Agents add tests constantly. | Say so. |
| 17 | L5 output interface | The program reads `tests.json` (numbers and recorded seconds) and prints test *numbers* in worker lists. A pytest user has neither. Without `tests.json` it falls back to one second per test (`selector.py:241-251`). | A standalone tool needs a node-id interface and its own duration source. The prompt never asks whether that is acceptable. |
| 18 | L10 "One semantic extension" | The forked child **executes the patched package**, so the claim "nothing from the patch is run" (README:74) is false for that path. Fine inside a container you already trust to run the tests; a problem as a hosted service on untrusted forks. | State it as a security property by segment. |

---

## 2. Segments: missing, wishful, and what would falsify each

### In the prompt (L33)

| Segment | Verdict | Why | Falsifier (observable, cheap) |
|---|---|---|---|
| Open-source maintainers with big pytest suites | **Wishful as stated** | Public-repository CI minutes are free on the common hosts, so the cost is wall time and flaky retries, not money. Maintainers are wary of any tool that might hide a failure, and a tool that needs an external map per base commit and exact-applying patches fits badly with fork-based pull requests. | Take 20 projects with suites over 10 min. Replay their last 100 merged PRs. If fewer than 30% of PRs get a selected set under half the suite, or more than 20% fall to "does not apply", the segment fails. |
| Monorepo platform teams | **Partly wrong** | They usually already have target graphs (Bazel/Pants) and paid infra; Python line-of-code tracing is a poor replacement for build-graph selection, and they would want integration with it, not a rival. | Ask three platform teams what they do for Python today; if all answer "target graph plus caching", the tool is not additive. |
| Regulated industries | **Wishful** | Regulated process usually requires a justified, documented regression policy and, for safety standards, a qualified tool. "Provably unaffected" is attractive, but a trace is evidence, not a qualification. Most safety-critical code is not Python. | Ask five QA leads in regulated work whether skipping any regression test is allowed on a technical argument alone, and what tool qualification costs. One "no" on the first question kills it. |
| AI coding agents | **Plausible but weak as written** | Agents' diffs apply to a fixed base, so the exact-patch rule can hold. But agents routinely add or change tests, which sends the patch to "everything" (`selector.py:96-97`); they often run a single targeted test; and the map must exist first, costing at least four traced passes. | Log 100 real agent edit sessions on one repo: fraction of edits that touch no test header, and fraction where a map exists. Under 50% on either kills it. |

### Missing from the prompt

| Segment | Why it might fit | Why it might not | Falsifier |
|---|---|---|---|
| **Mutation-testing tools** (per-mutant test selection) | Exactly "which tests ran this code" for thousands of tiny diffs against one fixed base: exact-patch rule holds, map cost is amortised, offline. | Existing mutation tools already select by coverage and the mutations are inside function bodies, where line-level coverage is as good as code-object granularity. [memory, unverified] | Same mutants, same suite: compare selected-set size and total tool time against the incumbent's coverage selection. No gain over 15% means no segment. |
| **Merge queues / pre-merge speculative builds** | Many changes per day against one base; map built once per day. | The base moves after every merge, so each queue position has a different base. | Measure the number of changes per distinct base in a real queue. Below 3 and the map cost does not amortise. |
| **Bisecting a regression** | `git bisect` with only the tests that ran each commit's changed code. | Needs a map per bisect step; bisect over history rarely applies the patch to one fixed base. | Bisect 20 historical regressions with and without; compare total time including map. |
| **Downstream/ecosystem testing** (run dependents' suites against a changed upstream library) | Selecting dependents' tests that executed the changed upstream code objects is a distinct and costly problem, and trace-based selection is the natural solution. | Needs a map per dependent; each dependent needs a working harness. | Pick three dependents of a popular library, map them, and replay 50 upstream commits. If selection is not smaller than a name- or import-based heuristic, drop it. |
| **Expensive or scarce test infrastructure** (GPU, device farm, long integration tests) | Per-test cost is high, so skipping provably unaffected tests is worth more and the map cost is relatively small. | Hardware tests often execute out-of-process or in native code the tracer cannot see (`untraced` goes to everything). | Count what fraction of such suites' time runs in untraced child processes or C code. Above 50% kills it. |
| **Local fast-feedback loops** (watch mode, pre-commit) | Developers want seconds. | This is the home turf of an incremental, self-updating tool; a per-base static map loses. | Head-to-head against the incumbent in watch mode: time to first relevant result after an edit. |
| **Dependency-bump bots** | Large volume of PRs. | The change is in a dependency, not in project source; the tool compares project source, so it cannot select anything. Likely a hard "no". | Count what share of those PRs touch only lock files: they hit "settings or unknown" and run everything. |

---

## 3. Tools the prompt is likely to under-rate, and what a fair comparison needs

The prompt lists the right names but then asks only "what it selects on" and "can it miss". That frames every competitor as a weaker proof, which is the question where this tool looks best. The questions where it looks worst are never asked.

Under-rated or missing (descriptions are **[memory, unverified]**, to be checked):

- **pytest-testmon.** Records per-test coverage and fingerprints of code blocks, stores them in a local database, and reruns tests whose blocks changed. Key difference: it updates the database incrementally as you run, so there is **no per-base map rebuild**, no exact-patch requirement, and no version-locked map. For a developer loop it is the incumbent to beat, and the prompt names it only as a place to count downloads.
- **Coverage-based test impact analysis products** (several vendors and CI platforms offer it for Python). Typically line-level, no code-object comparison, hosted. They compete on integration and maintenance, not on theory.
- **Predictive test selection services** (history/ML). The prompt treats missed failures as their defining flaw. Fair view: they also handle flaky tests, tests that fail for reasons unrelated to the diff, and non-Python changes that this tool sends to "everything". They are tuned to a target of "fraction of failures caught", and some publish that figure.
- **Build-graph systems (Bazel, Pants, and similar).** Their selection is by dependency graph at file or target granularity. They are coarser but have no map and no runtime assumptions, and are already trusted in the teams the prompt names.
- **Academic safe regression test selection** (the Rothermel–Harrold line; Ekstazi and STARTS for Java; later work on Python). The prompt never cites this literature, yet "safe" is the word it is reinventing. A fair comparison needs the assumptions those papers state (determinism, controlled environment, handling of reflection and dynamic loading), then to say which of them this tool shares.
- **Test sharding, caching and re-ordering** (xdist, split-by-duration, result caches, test-failure-first ordering). For many users the cheaper fix; some of the claimed saving here is a split-and-pack effect, not selection.

A fair comparison needs, for each tool, on the **same** patches, labels and machine:

1. Missed failures and the labelling method (one process or isolated; seed; time-out). Report with a confidence bound, not "0".
2. Selected seconds and tests as a fraction of the full run, including the distribution (median, p90, share of patches that fall to "everything").
3. **Total cost including set-up**: first-run cost, per-base or per-update cost, storage, CPU per query. Report break-even in number of changes per map.
4. Behaviour on the awkward inputs: patch against a moved base, added tests, data-file edits, module/class-level edits, conftest changes, flaky tests, tests that spawn processes.
5. Lock-in and ops: price, network need, language/runtime constraints, maintenance, who is responsible for a miss.
6. Adoption friction: lines of config to try it on a new repository, and time to first useful answer.
7. At least two more repositories besides sqlglot, one with a heavy shared core (where selection is likely to collapse to "everything").

---

## 4. The strongest case that nobody needs this

1. **The map costs more than it saves for most users.** At least four traced passes per base (item 13), and the base must match the patch exactly (item 14). On a busy main branch every merge makes the previous map useless for the next pull request. Break-even needs many changes per base. Where there are many changes per base (mutation testing, agents on a fixed checkout), incumbents already exist.
2. **The headline gain is partly an artefact.** The tool's measured advantage includes a fixed per-worker cost and a suite whose critical path is one 28.8 s test of 103 s total. On typical projects CI time is dominated by environment set-up, image pulls and dependency installs, not by test execution. Selecting tests out of the 103 s does little for the 3 minutes before them.
3. **Selection collapses where it matters.** Libraries with a heavy shared core (a change to a base class, a parser loop, an ORM layer) go to "loaders" or "everything"; sqlglot's dialect structure is unusually favourable (many small edits to one dialect). One repository cannot show otherwise.
4. **Trust is the product, and a trace is not a proof.** One flaky or order-dependent miss in a team's first month ends adoption, and the assumptions behind soundness (item 1) are exactly the ones real suites violate.
5. **Cheaper alternatives exist** for the people with real pain: sharding, caching, and an incremental tool for the local loop.

**Evidence that would settle it** (decide the thresholds before looking):

- Replay the last 200 merged changes in 10 varied public Python projects. Report per project: share of changes whose selected time is under 50% of a full run; share that "does not apply" because the base moved; share that hit "everything"; map build time as a multiple of one full run.
- Run pytest-testmon and a coverage-based selector on the same replays with the same labels. If the incumbent's mean selected time is within 20% of this tool's and needs no per-base map, the claim of added value is gone.
- Measure what fraction of those projects' CI wall time is test execution rather than set-up. Under 40% means selection cannot give a large end-to-end gain.
- Ask 10 maintainers or platform engineers, with the replay results in hand, whether they would run a free version. Count unprompted yeses.

Concede if: the median project has fewer than 30% of changes at under 50% selected time **and** the incumbent matches it; or the median map costs more than the time saved over the changes it serves.

---

## 5. Rewritten prompt

```markdown
# Research prompt: is there demand for a trace-based test selector, and from whom?

## What the tool is (facts, each tagged by how it is known)

A command-line program that reads a unified diff and a prebuilt map and prints which tests the change could affect, split into worker groups. It leaves a test out only when the recorded trace of that test shows it never entered the changed code, and it runs a wider set (the "loaders" of a module, or every test) when it cannot show that.

**How it works** [from the code, README at 24aaf06]
- **Map, built per base commit.** At least four traced passes of the full suite (three session modes: per-file forked, whole-suite in order, whole-suite reversed; plus forked passes under two hash seeds for the flag-gap facts only). Each test runs in a forked process under `sys.monitoring`. It records code objects entered, files opened, stat-ed or listed, modules loaded by the test's file, and child processes started.
- **Selection, per change.** The old and new file are compiled and compared code object by code object, ignoring line numbers. Tests that ran a changed body are chosen. Module- or class-level edits choose the tests that load the module. A changed body that writes lasting state, or a file that no longer compiles, chooses all tests of every test file that loads the module. Settings files, binary files, added/removed/renamed files, an added or removed test, and any patch that does not apply exactly to the mapped base choose every test.
- **One extension (v1.6):** when a change only flips required-argument flags of expression classes, the patched package is imported in a forked, time-limited child and the resulting differences select fewer tests. This executes the patched code. A dead or late child turns the extension off for the rest of the batch.
- **Interface today:** reads a numbered test list with recorded durations and prints test numbers, not pytest node ids. POSIX only. The map is valid only for the exact Python build it was recorded on (3.13 line).

**Measurements** [one repository, sqlglot; all numbers to be re-checked by the researcher where possible]
- 1,620 tests; 103 s recorded serial time; one test is 28.8 s, so a four-way split has a ~37 s floor.
- The cost-formula result on 30 sample commits (188 s against ~1,104 to 1,210 s for running everything) counts a fixed 2 s per worker and recorded durations; it is neither wall-clock nor CPU.
- 0 missed failures on ~90 labelled commits, with the caveats: labels come from the authors' own harness (one process, one order, one timeout, one seed); the mutants were generated by the authors; the real commits are those that apply cleanly to the pinned base; the sample commits were used in development. Rule-of-three bound at n=90: miss rate per commit below ~3% at 95% confidence.
- In the fault-injection runs tried (crash, hang, out of memory, half output) output stayed valid; degraded runs fall back to running everything. CPU cost of the selector: unreproduced, to be measured.

**Known limits** [from the code]
- Soundness is relative to assumptions: deterministic tests, no order-dependent state beyond what the AST rule catches (the rule errs towards "yes"), no untraced child processes or native code on the path, no unrecorded environment inputs.
- Needs a map per base; patches must apply with zero offset to that base; real pull requests on a moving branch may not.
- Builder and the flag gate carry sqlglot-specific parts; no second repository has been tried.

## The question

Which specific people lose time, money or trust by running tests a change could not have affected, or by skipping tests unsafely, **and** would adopt this tool instead of what they have? For each candidate segment establish:

1. **Pain, with numbers:** current practice (run everything, sharding, path filters, coverage-based impact analysis, history/ML selection, build-graph selection, flaky-test retries, caching), and what it costs in CI minutes, wall time, queueing, missed regressions. Separate test-execution time from set-up time (image pulls, installs).
2. **Incumbents, evaluated on their strongest terms.** For each: what it selects on; whether it needs a per-base map; whether it updates incrementally; missed-failure rate by its own account; price, lock-in, network need; Python/pytest support; known unsound cases. Include at least: pytest-testmon, a coverage-based impact-analysis service, a predictive-selection service, Bazel/Pants-style target selection, sharding and caching, and the academic safe-regression-selection literature. Tag any claim you cannot link [inference].
3. **Fit:** which tool properties matter or are dealbreakers: soundness under stated assumptions; code-object granularity; offline operation; map cost and staleness; exact-apply requirement; POSIX/version lock; node-id interface.
4. **Segments to test** (each with a falsifier, below): open-source maintainers; monorepo platform teams; regulated development; AI coding agents; **mutation-testing tools; merge queues; regression bisecting; downstream/ecosystem testing; expensive-infrastructure suites; local watch loops**. Add any you find.
5. **Evidence it is wanted:** issues and feature requests, download counts of selection plugins, talks and posts, complaints about missed failures, and, separately, complaints about maintaining selection tools. Distinguish "people want faster CI" from "people want this kind of tool".

## Falsifiers (state the result for each segment; do not skip a failing one)

- Maintainers/monorepo: from public histories, share of recent merged changes that would get under 50% selected time, and share that would not apply to a single mapped base.
- Regulated: whether process rules accept a technical argument for skipping any regression test, and the cost of qualifying a tool.
- Agents: share of real agent edit sessions that add or remove a test, and share with a prebuilt map available.
- Mutation testing: selected-set size and total time against the incumbent's coverage selection on the same mutants.
- Merge queues: changes per distinct base.
- Anything else: name the observation that would make you drop it.

## Required output

- A ranked list of 3 to 5 segments. For each: who; sourced pain; what they use now; where this tool is better and where worse **than the best incumbent for them**; the smallest useful version; the falsifier and its result (or "not tested, needs X").
- A comparison table of tool versus incumbents on the seven points: misses with confidence bound; selected-time distribution including share falling back to everything; total cost including set-up and break-even changes per map; awkward inputs (moved base, added tests, data files, module-level edits, flaky tests, child processes); lock-in/ops; adoption friction; evidence on more than one repository (if none exists, say so).
- The strongest argument that **nobody needs this**, answered with evidence or conceded. Use these thresholds, fixed before searching: concede if the typical project has under 30% of changes at under 50% selected time and an incumbent matches it, or if map cost exceeds the time saved over the changes a map serves, or if test execution is under 40% of CI wall time.
- The packaging that follows from the evidence (pytest plugin, CLI, CI action, library for agents), with the first paragraph of the README written for the top segment, **including its limits in the first paragraph**.
- A list of what must be built before any segment can use it (node-id interface, second-repository map builder, incremental map update, base-drift handling), in order of how much each blocks.

## Rules

- At most 20 web searches. Prefer practitioner sources (engineering blogs, issue trackers, download statistics, post-mortems) over vendor pages. Quote vendor numbers only when marked as vendor claims.
- Label every claim [fact] (with a link) or [inference]. Anything about the tool itself must be [from the code] or [measured, by whom].
- Do not repeat the tool's headline numbers as findings; they are inputs to be checked, not evidence of demand.
```
