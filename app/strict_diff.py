"""Reads a unified diff of in-place modifications. Anything else raises Unreadable, and the caller runs every test.

Everything stays bytes. Hunks must match the pinned file at the stated line, with exact counts.
"""
import re

RANGE = re.compile(rb"@@ -(\d{1,9})(?:,(\d{1,9}))? \+(\d{1,9})(?:,(\d{1,9}))? @@")
INDEX = re.compile(rb"index [0-9a-f]{4,64}\.\.[0-9a-f]{4,64}(?: 100(?:644|755))?")


class Unreadable(Exception):
    pass


def demand(condition, problem):
    if not condition:
        raise Unreadable(problem)


def pathname(line, marker, side):
    """The path of a '--- a/...' or '+++ b/...' line."""
    demand(line.startswith(marker + side), "unexpected file header")
    raw = line[len(marker) + len(side):].split(b"\t")[0]
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        raise Unreadable("path is not plain ASCII") from None
    parts = text.split("/")
    demand(text and text.isprintable() and not set(text) & set('"\\') and not {"", ".", ".."} & set(parts), "odd path")
    return text


def sections(patch):
    """[(path, [(old start, new start, rows)])]; a row is (sign, content with its own line end)."""
    demand(patch.endswith(b"\n"), "empty or cut off")
    lines = patch.split(b"\n")[:-1]
    found, at, promised, described = [], 0, None, False
    while at < len(lines):
        line = lines[at]
        if line.startswith(b"diff --git "):
            demand(promised is None, "a header without content")
            promised, described = line, False
            at += 1
        elif line.startswith(b"index "):
            demand(promised is not None and not described and INDEX.fullmatch(line), "unexpected index line")
            described = True
            at += 1
        elif line.startswith(b"--- "):
            demand(at + 1 < len(lines), "cut off after ---")
            path = pathname(line, b"--- ", b"a/")
            demand(pathname(lines[at + 1], b"+++ ", b"b/") == path, "two names")
            demand(promised == f"diff --git a/{path} b/{path}".encode(), "no header of this file, or another one")
            demand(path not in [earlier for earlier, _ in found], "file named twice")
            promised = None
            at, hunks = hunk_list(lines, at + 2)
            found.append((path, hunks))
        else:
            raise Unreadable("unexpected line")
    demand(found and promised is None, "nothing changed")
    return found


def hunk_range(line):
    """The four numbers of a hunk header, or None if the line does not start a hunk."""
    if not line.startswith(b"@@"):
        return None
    head = RANGE.match(line)
    demand(head, "bad hunk header")
    # a count that is not written is 1
    return [1 if text is None else int(text) for text in head.groups()]


def hunk_list(lines, at):
    hunks = []
    while numbers := hunk_range(lines[at] if at < len(lines) else b""):
        old_start, gone, new_start, come = numbers
        left = {b"-": gone, b"+": come}
        at, rows = at + 1, []
        while left[b"-"] or left[b"+"] or (at < len(lines) and lines[at].startswith(b"\\")):
            demand(at < len(lines), "hunk cut off")
            sign, content = lines[at][:1], lines[at][1:]
            if sign == b"\\":
                demand(content.startswith(b" No newline") and rows, "bad newline marker")
                kind, text = rows.pop()
                demand(text.endswith(b"\n"), "bad newline marker")
                rows.append((kind, text.removesuffix(b"\n")))
            else:
                demand(sign in (b" ", b"+", b"-") and sign, "bad hunk line")
                for side in (b"-", b"+"):
                    if sign != {b"-": b"+", b"+": b"-"}[side]:
                        left[side] -= 1
                        demand(left[side] >= 0, "too many lines in a hunk")
                rows.append((sign, content + b"\n"))
            at += 1
        demand(any(sign != b" " for sign, _ in rows), "a hunk without a change")
        hunks.append((old_start, new_start, rows))
    demand(hunks, "no hunks")
    return at, hunks


def patched(old, hunks):
    """The new content, or Unreadable if any hunk does not fit exactly where it says."""
    source = [row + b"\n" for row in old.split(b"\n")]
    # what follows the last line end is a line only if there is something
    source[-1:] = [source[-1][:-1]] if source[-1] != b"\n" else []
    result, done = [], 0
    for old_start, new_start, rows in hunks:
        before = [content for sign, content in rows if sign != b"+"]
        after = [content for sign, content in rows if sign != b"-"]
        place = old_start - 1 if before else old_start
        demand(done <= place <= len(source), "hunks overlap or lie outside the file")
        demand(source[place:place + len(before)] == before, "the pinned file differs")
        result += source[done:place]
        demand(len(result) == (new_start - 1 if after else new_start), "line numbers disagree")
        result += after
        done = place + len(before)
    result += source[done:]
    demand(all(part.endswith(b"\n") for part in result[:-1]), "a line without an end inside the file")
    return b"".join(result)
