#!/usr/bin/env python3
"""Extract the corpus_runner raw output from the SUT corpus-boot transcript.

The guest emits, over the serial console, sentinel-bracketed lines:
    === GAE-CORPUS BEGIN ===
    GAE-CORPUS-B64 <base64 of the 22-line tab-separated runner output>
    === GAE-CORPUS END rc=<n> ===

This reads the transcript, requires BEGIN + END(rc=0), base64-decodes the payload,
and writes the raw tab-separated lines to --out (consumed by collect_results.py).
Fail-closed: aborts non-zero if a sentinel is missing, rc != 0, decode fails, or
the line count is not the expected 22.
"""
import argparse
import base64
import re
import sys

ANSI_RE = re.compile(r"\x1b\[[0-9;?=]*[A-Za-z]|\x1b[()][A-Za-z0-9]|\x1b[=>]")
BEGIN_RE = re.compile(r"^\s*=== GAE-CORPUS BEGIN ===\s*$")
END_RE = re.compile(r"^\s*=== GAE-CORPUS END rc=(-?\d+) ===\s*$")
B64_RE = re.compile(r"^\s*GAE-CORPUS-B64\s+(\S+)\s*$")


def normalize(raw: bytes):
    text = raw.decode("latin-1").replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = ANSI_RE.sub("", text)
    return text.split("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--expect-lines", type=int, default=22)
    a = ap.parse_args()

    with open(a.transcript, "rb") as fh:
        lines = normalize(fh.read())

    saw_begin = any(BEGIN_RE.search(ln) for ln in lines)
    rc = None
    for ln in lines:
        m = END_RE.search(ln)
        if m:
            rc = int(m.group(1))
            break
    payload = None
    for ln in lines:
        m = B64_RE.search(ln)
        if m:
            payload = m.group(1)
            break

    if not saw_begin:
        print("FAIL: GAE-CORPUS BEGIN sentinel not found", file=sys.stderr); return 1
    if rc is None:
        print("FAIL: GAE-CORPUS END sentinel not found", file=sys.stderr); return 1
    if rc != 0:
        print("FAIL: corpus_runner rc=%d (expected 0)" % rc, file=sys.stderr); return 1
    if not payload:
        print("FAIL: GAE-CORPUS-B64 payload line not found", file=sys.stderr); return 1

    try:
        raw = base64.b64decode(payload)
    except Exception as e:
        print("FAIL: base64 decode error: %s" % e, file=sys.stderr); return 1

    text = raw.decode("utf-8", errors="strict")
    out_lines = [l for l in text.split("\n") if l.strip()]
    if len(out_lines) != a.expect_lines:
        print("FAIL: extracted %d lines, expected %d" % (len(out_lines), a.expect_lines),
              file=sys.stderr)
        for l in out_lines:
            print("  " + l, file=sys.stderr)
        return 1

    with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out_lines) + "\n")
    print("wrote %s (%d lines, corpus_runner rc=0)" % (a.out, len(out_lines)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
