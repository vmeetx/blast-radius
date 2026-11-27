# Research prompt: who needs a proof-based test selector, and why

## What the tool is (facts only)

A command-line program that, given a code change (a unified diff) to a Python project, prints the tests that change could possibly break, split across N workers to finish soonest. It leaves a test out only when a recorded fact proves the change could not affect it, and runs everything when it cannot prove that.

How it works:
- **Map, built once per base commit.** Every test runs in its own forked process under `sys.monitoring` (Python 3.12+). The map records, per test: the code objects it entered, files it opened or stat'ed, modules its file loads, and child processes it started. It runs under two hash seeds to catch nondeterminism.
- **Selection, per change.** The old and new versions of each changed file are compiled and compared code object by code object, ignoring line numbers. Only the tests that ran a changed body are chosen. Module or class-level edits fall back to the tests that load the module. Code that writes lasting state, settings files, new or deleted tests, renames, binary files and patches that don't apply exactly all run everything.
- **One semantic extension (v1.6):** if a change only flips declarative flags, the patched package is imported in a forked, time-limited child, and the derived structures are diffed against a snapshot. Only the tests that met the changed entries are chosen. A dead or late child turns the extension off for the rest of the batch.
- **Measured on sqlglot (about 1,600 tests, 37 s per full run):**
  - 30 sample commits: 188 s versus about 1,600 s for running everything, with 0 missed failures.
  - About 90 labelled real and mutant commits: 0 misses.
  - The selector itself adds about 2 s of CPU.
  - Fault-injected (crash, hang, out of memory, half output), it always prints a valid answer.
- **Constraints:** it needs a map rebuilt per base commit, Python 3.12+, and pytest. Today the map builder carries sqlglot-specific paths and a sqlglot-specific semantic gate.

## The question

Who, specifically, loses money, time or trust by running tests that a change could not have affected, or by skipping tests unsafely? For each candidate user, establish:

1. **Pain:** what they do today (run everything, sharding, path filters, coverage-based Test Impact Analysis, ML predictive test selection, Bazel or Pants target graphs, flaky-test retries), and what it costs them in CI minutes, wall time, queueing or missed regressions. Use numbers from public sources.
2. **Why existing tools don't already solve it.** For each existing tool or service:
   - what it actually selects on: lines, files, targets, history, or ML;
   - whether it can miss a failure, and how often by its own admission;
   - its price and lock-in;
   - whether it supports Python and pytest.
3. **Fit:** which of these properties matter to this user, and which are dealbreakers?
   - **Proof, not prediction:** no statistical exclusion, so no missed failures by construction.
   - **Code-object granularity:** comment, docstring-position and formatting-only changes select little or nothing.
   - **Offline, single binary:** runs with no network or SaaS, inside a locked-down CI container.
   - **Map rebuild cost:** one full traced run per base commit.
4. **Who adopts free tools here:** open-source maintainers with big pytest suites, monorepo platform teams, regulated industries where "the tool predicted it was safe" is unacceptable, and AI coding agents that need fast, trustworthy test feedback on every edit.
5. **Evidence it is wanted:** GitHub issues, pytest plugin downloads (pytest-testmon, pytest-incremental, and the like), conference talks, blog posts on Test Impact Analysis, and complaints about predictive test selection missing failures.

## Required output

- A ranked list of 3 to 5 user segments. For each:
  - who they are;
  - the pain, with sourced numbers;
  - what they use now;
  - why this tool is better or worse for them;
  - the smallest version of the tool that would be useful to them.
- The strongest argument that **nobody needs this**: existing tools are good enough, or the map cost kills it. Answer that argument with evidence, or concede it.
- The packaging that follows from the evidence: a pytest plugin, a CLI, a GitHub Action, or a library for agents. Include the README's first paragraph, written for the top segment.

## Rules

- At most 20 web searches. Prefer practitioner sources (engineering blogs, issue trackers, download stats) over vendor marketing.
- Label every claim [fact] (with a link) or [inference].
