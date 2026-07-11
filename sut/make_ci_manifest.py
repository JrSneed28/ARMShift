#!/usr/bin/env python3
"""Assemble the retained W0.5 CI hash manifest.

Walks the per-run output tree and records SHA-256 for the pipeline's retained
artifacts (build logs, transcripts, JUnit, result sets, diff reports) plus the
rebuilt QEMU binary. "Retained green pipeline with logs and hashes" (plan
section 3 W0.5) means the pipeline is evidence: this manifest is the hash index
of that evidence, uploaded with the artifact bundle.
"""
import argparse
import glob
import hashlib
import json
import os


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="per-run output root (.w05)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    patterns = [
        "qemu/build/qemu-system-aarch64",
        "qemu/logs/*.json",
        "qemu/logs/*.log",
        "fw/*.fd",
        "smoke/boot-transcript.log",
        "smoke/boot-transcript.json",
        "smoke/smoke-junit.xml",
        "smoke/run-result.json",
        "corpus/boot-transcript.log",
        "corpus/runner-raw.sut.txt",
        "corpus/results-sut.json",
        "corpus/results-sut-noseed.json",
        "corpus/diff-report.json",
        "corpus/diff-report.txt",
        "corpus/diff-report-negctrl.json",
        "corpus/run-result.json",
        "seed-smoke.iso",
        "seed-corpus.iso",
        "dl/alpine-aarch64.qcow2",
    ]
    hashes = {}
    for pat in patterns:
        for p in sorted(glob.glob(os.path.join(a.root, pat))):
            if os.path.isfile(p):
                rel = os.path.relpath(p, a.root).replace(os.sep, "/")
                hashes[rel] = {"sha256": sha256(p), "bytes": os.path.getsize(p)}

    manifest = {
        "schema": "gae-ci/hash-manifest@1",
        "work_item": "W0.5",
        "engine_internal_name": "generic-arm64-engine",
        "runner": "github-actions ubuntu-latest (public hosted)",
        "note": "SHA-256 index of the retained per-change pipeline artifacts (logs + hashes).",
        "artifacts": hashes,
    }
    with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    print("wrote %s (%d artifacts hashed)" % (a.out, len(hashes)))


if __name__ == "__main__":
    main()
