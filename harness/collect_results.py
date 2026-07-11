#!/usr/bin/env python3
"""W0.4 differential harness -- result collector.

Wraps the raw stdout of corpus_runner (lines "<id>\\t<canonical>") into a
gae-diff/results@1 result set bound to the exact corpus-manifest.json bytes.

Runs on either side of the differential:
  * reference : the ARM64-hardware run.  --side reference   (never seeded)
  * SUT       : the qemu-system-aarch64 (TCG) run.  --side sut [--seed]

In seed mode (--side sut --seed) it injects the ONE documented negative-control
mutation -- flip bit 0 of the seed entry's 64-bit result -- on the SUT side only,
exactly as corpus-manifest.json's seed_policy specifies. The reference is never
mutated (the collector refuses --side reference --seed).

Usage:
  corpus_runner > raw.txt
  python collect_results.py --manifest corpus-manifest.json --raw raw.txt \\
      --side sut --seed --engine-json '{"qemu_sha256":"...","host":"..."}' --out results-sut.json
"""
import argparse
import hashlib
import json
import sys


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(path):
    with open(path, "r", encoding="utf-8") as fh:
        m = json.load(fh)
    if m.get("schema") != "gae-diff/corpus-manifest@1":
        raise SystemExit(f"manifest {path}: unexpected schema {m.get('schema')!r}")
    ids = [t["id"] for t in m["tests"]]
    seed_ids = [t["id"] for t in m["tests"] if t.get("seed_mismatch") is True]
    return m, ids, seed_ids


def parse_raw(raw_text):
    results = {}
    for lineno, line in enumerate(raw_text.splitlines(), 1):
        line = line.rstrip("\r")
        if not line.strip():
            continue
        if "\t" not in line:
            raise SystemExit(f"raw line {lineno}: no tab separator: {line!r}")
        tid, output = line.split("\t", 1)
        tid = tid.strip()
        output = output.strip()
        if tid in results:
            raise SystemExit(f"raw line {lineno}: duplicate id {tid!r}")
        results[tid] = output
    return results


def mutate(output):
    """Flip bit 0 of the leading 64-bit hex result, preserving any nzcv suffix."""
    parts = output.split(" ", 1)
    val = int(parts[0], 16) ^ 0x1
    head = "0x%016x" % val
    return head if len(parts) == 1 else head + " " + parts[1]


def main(argv=None):
    ap = argparse.ArgumentParser(description="W0.4 result collector")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--raw", required=True, help="runner stdout capture, or - for stdin")
    ap.add_argument("--side", required=True, choices=["sut", "reference"])
    ap.add_argument("--seed", action="store_true", help="SUT only: inject the seed mutation")
    ap.add_argument("--engine-json", default="{}", help="provenance JSON (host/qemu hash or ARM64 profile)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    if args.side == "reference" and args.seed:
        raise SystemExit("refusing --side reference --seed: the reference run is never mutated")

    manifest, ids, seed_ids = load_manifest(args.manifest)
    manifest_sha = sha256_file(args.manifest)

    raw_text = sys.stdin.read() if args.raw == "-" else open(args.raw, "r", encoding="utf-8").read()
    results = parse_raw(raw_text)

    missing = [i for i in ids if i not in results]
    extra = [i for i in results if i not in ids]
    if missing:
        raise SystemExit(f"runner output missing ids: {missing}")
    if extra:
        raise SystemExit(f"runner output has unknown ids: {extra}")

    if args.side == "sut" and args.seed:
        for sid in seed_ids:
            results[sid] = mutate(results[sid])

    try:
        engine = json.loads(args.engine_json)
    except json.JSONDecodeError as e:
        raise SystemExit(f"--engine-json is not valid JSON: {e}")

    out = {
        "schema": "gae-diff/results@1",
        "side": args.side,
        "corpus_manifest_version": manifest["version"],
        "corpus_manifest_sha256": manifest_sha,
        "seed_active": bool(args.side == "sut" and args.seed),
        "engine": engine,
        "results": {i: results[i] for i in ids},
    }
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=2)
        fh.write("\n")
    sys.stderr.write(f"wrote {args.out}: side={args.side} seed_active={out['seed_active']} "
                     f"tests={len(ids)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
