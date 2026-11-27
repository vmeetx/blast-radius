# Who needs blast-radius, and how to offer it

Method:
1. A research prompt (`RESEARCH_PROMPT.md`).
2. A hostile review that rewrote it (`RESEARCH_PROMPT_hamilton.md`).
3. 16 web searches against the rewritten prompt.

Claims are tagged [fact] with a link, [from the code], or [inference].

## 1. What the tool honestly is

A trace-based **safe regression test selector** for Python: given a diff against a mapped base commit, it prints the tests that ran any changed code. When it can't tell, it falls back to wider sets ("loaders" of a module, or everything).

- **Sound only under stated assumptions** [from the code]:
  - tests are deterministic;
  - no order-dependent state beyond what the AST rule catches (that rule errs towards "yes");
  - no untraced child processes or native code on the path;
  - no unrecorded environment inputs.
- **Measured on one repository (sqlglot, 1,620 tests)** [measured by the author]:
  - 0 misses on about 90 labelled commits (rule of three: under about 3% per commit at 95% confidence);
  - on 30 sample commits, a cost-model total of 188 s against about 1,100–1,200 s for running everything. That figure includes 2 s per worker and is not wall-clock time.
- **Limits** [from the code]:
  - the map is per base commit and costs at least four traced passes;
  - patches must apply with zero offset;
  - the map is locked to one exact Python build;
  - POSIX only;
  - output is test numbers, not pytest node ids;
  - sqlglot-specific parts remain in the map builder and the flag gate;
  - no second repository has been tried.

## 2. The landscape (what people use today)

| Approach | Selects on | Can miss? | Needs per-base map? | Notes |
|---|---|---|---|---|
| [pytest-testmon](https://pypi.org/project/pytest-testmon) | Coverage.py blocks per test, local database, updated incrementally | Yes: data files, library updates and some global/class-variable changes are not tracked ([issues](https://redirect.github.com/tarpas/pytest-testmon/issues)) | No, it updates as you run | The incumbent for local loops. Used in CI by caching the database ([experience report](https://medium.com/@boxed/vastly-faster-python-integration-tests-9d8106b3693c)) [fact] |
| [Datadog Test Impact Analysis](https://docs.datadoghq.com/tests/test_impact_analysis/how_it_works/) | Files covered per test; skips if a pass exists on a commit with identical covered files | Yes, by its own docs: dependency, data-file and external-service changes | No, history-based, hosted | Paid SaaS; incompatible with pytest-cov [fact] |
| Predictive selection ([Meta](https://engineering.fb.com/developer-tools/predictive-test-selection/), [paper](https://arxiv.org/pdf/1810.05286.pdf), CloudBees, BrowserStack) | ML on history | Yes, by design: Meta keeps about 95% of individual failures and over 99.9% of faulty changes, at half the cost [fact] | No | Also handles flaky and non-code failures |
| Static/import graph ([pytest-impacted](https://pypi.org/project/pytest-impacted), [chisel](https://pypi.org/project/chisel-test-impact/), [gerenuk](https://pypi.org/project/gerenuk/)) | AST imports, git diff | Yes: dynamic dispatch, registries | No | Cheap, imprecise; chisel targets AI agents via MCP [fact] |
| Academic Python RTS: [NameRTS](https://arxiv.org/pdf/2605.25356) (2026), [Kauhanen et al.](https://core.ac.uk/download/479167931.pdf), [Pöyry thesis](https://core.ac.uk/download/132598588.pdf) | Names graph; coverage at file or line level | NameRTS: 99.6% safety rate, skips 69.9% of test files. Kauhanen: 0–2% missed faults at file level, **16–24% at line level** [fact] | Varies | No production tool came out of these |
| Java dynamic RTS ([Ekstazi](https://typeset.io/pdf/practical-regression-test-selection-with-dynamic-file-28si4g2dlc.pdf)) | Class/file dependencies, traced | Safe by argument | Yes, refreshed per run | About 15× fewer tests and 8× less time, reported for Java [fact] |
| Build graphs (Bazel, Pants) | Targets | Rarely | No | Coarse; teams that have them won't swap [inference] |

**What this says** [inference]:
- The gap blast-radius can fill is real but narrow: **dynamic, safe selection at code-object granularity, offline, for Python**. Line-level coverage tools miss failures (16–24% in Kauhanen et al.). File-level tools are safe but select a lot. Every production tool in the table either predicts, which can miss by design, or is coarse.
- Code-object comparison is the middle path the literature points to, and nobody ships it for Python.

## 3. Segments, ranked by fit and evidence

### 1. AI coding agents and the harnesses that run them (best fit)

- **Pain.** CI load from agents is exploding: Anthropic reports a [25× rise in CI jobs in six months](https://claude.com/resources/articles/agentic-coding-is-straining-ci-heres-how-we-scaled-test-impact-analysis-at-anthropic) and needed to rebuild its test impact service [fact]. Practitioners say agents run whatever full command is documented ([flaviocopes](https://flaviocopes.com/fast-tests-for-agents/)) [fact].
- **Why it fits.** Agents edit a fixed checkout, so a map built once per checkout serves many edits, and the exact-apply rule holds [inference]. Existing agent tools ([chisel](https://pypi.org/project/chisel-test-impact/), TDAD) are static import graphs [fact]. A traced, safe answer is a better thing for an agent to trust [inference].
- **Worse than the incumbents.** Agents add tests often, and an added test currently selects everything [from the code]. The map must exist before the first edit.
- **Smallest useful version.** `blast-radius select --diff -` printing pytest node ids, plus an MCP tool wrapper. The map is built once per checkout.
- **Falsifier.** Log 100 agent edit sessions. If more than half add or remove a test, or have no map available, this segment fails. Not tested yet.

### 2. Mutation-testing tools (per-mutant selection)

- **Pain.** Running the suite per mutant is the cost. Tools cut it with line-coverage selection: [fest](https://pypi.org/project/fest-mutate/) and [pytest-gremlins](https://dev.to/mikelane/announcing-pytest-gremlins-v130-53ka) claim 10–100× fewer executions, and [mutmut](https://mutmut.readthedocs.io) supports coverage filtering [fact, vendor claims].
- **Why it fits.** Thousands of tiny diffs against one base: the map amortises fully, and exact-apply always holds [inference].
- **Worse.** Mutants sit inside function bodies, where line coverage is about as good as code-object selection. The gain is mainly for module- and class-level mutants and declarative tables, as in the flag gate [inference].
- **Smallest useful version.** A library call `select(base_map, old_source, new_source) -> node ids`.
- **Falsifier.** On the same mutants, if total tool time is no more than 15% better than coverage selection, drop this segment.

### 3. Python test-selection research (artifact and baseline)

- **Why it fits.** The 2026 NameRTS paper built the first Python RTS dataset with ground truth ([arXiv](https://arxiv.org/pdf/2605.25356)) [fact]. A dynamic, code-object, safe-by-construction baseline that is open and reproducible is something papers in this area need [inference].
- **Worse.** Researchers need multiple repositories, and today the builder is tied to sqlglot.
- **Smallest useful version.** The tool, the sqlglot map, the labelled commits and the evaluation harness, as a citable artifact.

### 4. Maintainers with slow PR suites (weak today)

- **Pain is real but often mis-aimed.** Studies find install time dominates without caching and tests dominate with it ([Gallaba et al.](https://rebels.cs.uwaterloo.ca/papers/tse2020_gallaba.pdf), practitioner reports) [fact]. Public-repository CI minutes are often free [inference].
- **Blocker.** Pull requests are made against a moving main branch, so exact-apply to one mapped base fails. pytest-testmon already serves this case without a per-base map [fact].
- **Verdict.** Not a target until base drift is handled.

### Dropped

- **Regulated industries:** a trace is evidence, not tool qualification [inference].
- **Dependency-bump bots:** lock-file changes run everything by design [from the code].

## 4. The strongest case that nobody needs this, answered

- **Case.**
  - Incumbents are good enough. Testmon is free and incremental. Datadog and predictive selection are integrated and handle flaky tests (order dependency causes 59% of flaky Python tests, [Gruber et al.](https://arxiv.org/pdf/2101.09077)) [fact].
  - The map costs at least four traced passes per base.
  - On a moving branch the map is stale after every merge.
- **Answer.**
  - **For general CI on a moving branch: conceded.** Use testmon or a hosted impact service.
  - **For fixed-base workloads, the case fails** (agents on a checkout, mutation testing, research replays). There the map amortises, exact-apply holds, and the incumbents are either line-level, which misses failures (Kauhanen et al.), or static, which is imprecise.
  - This is narrower than "every Python team", and it should be marketed that way.

## 5. Packaging that follows

- **Form:** a free, MIT-licensed **library + CLI** first, with an MCP wrapper for agents second. No SaaS.
- **README first paragraph** (written for segment 1, limits included): see `README.md`.
- **What must be built before anyone outside can use it**, most blocking first:
  1. **pytest node-id interface:** accept a diff and print node ids, with no numbered `tests.json` needed.
  2. **Generic map builder:** remove sqlglot paths and the dialect-registry rule; make the flag gate an optional plugin.
  3. **Added tests:** select the new test plus the normal rules, instead of everything.
  4. **Base drift:** rebase the diff onto the mapped base, or rebuild the map incrementally per merge.
  5. **A second and third repository,** one with a heavy shared core, to show where selection collapses.
  6. **Measured wall-clock and CPU** against testmon on the same replays.

## Sources

[pytest-testmon](https://pypi.org/project/pytest-testmon) · [testmon issues](https://redirect.github.com/tarpas/pytest-testmon/issues) · [testmon in CI](https://medium.com/@boxed/vastly-faster-python-integration-tests-9d8106b3693c) · [Datadog TIA](https://docs.datadoghq.com/tests/test_impact_analysis/how_it_works/) · [Meta PTS](https://engineering.fb.com/developer-tools/predictive-test-selection/) · [PTS paper](https://arxiv.org/pdf/1810.05286.pdf) · [pytest-impacted](https://pypi.org/project/pytest-impacted) · [chisel](https://pypi.org/project/chisel-test-impact/) · [gerenuk](https://pypi.org/project/gerenuk/) · [NameRTS](https://arxiv.org/pdf/2605.25356) · [Kauhanen et al.](https://core.ac.uk/download/479167931.pdf) · [Pöyry](https://core.ac.uk/download/132598588.pdf) · [Ekstazi](https://typeset.io/pdf/practical-regression-test-selection-with-dynamic-file-28si4g2dlc.pdf) · [Anthropic TIA](https://claude.com/resources/articles/agentic-coding-is-straining-ci-heres-how-we-scaled-test-impact-analysis-at-anthropic) · [fast tests for agents](https://flaviocopes.com/fast-tests-for-agents/) · [mutmut](https://mutmut.readthedocs.io) · [fest](https://pypi.org/project/fest-mutate/) · [pytest-gremlins](https://dev.to/mikelane/announcing-pytest-gremlins-v130-53ka) · [Gallaba et al.](https://rebels.cs.uwaterloo.ca/papers/tse2020_gallaba.pdf) · [Gruber et al.](https://arxiv.org/pdf/2101.09077) · [downstream testing](https://nesbitt.io/2026/03/01/downstream-testing)
